"""
诊断脚本：全面检查地址 0x5668... 的数据完整性。
检查 trades、positions、closed-positions、activity 各端点返回情况。
"""

import asyncio
import httpx
import pandas as pd
from collections import Counter

ADDRESS = "0x56687bf447db6ffa42ffe2204a05edaa20f55839"
DATA_API = "https://data-api.polymarket.com"


async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:

        # ── 1. 交易记录：测试不同 limit 和分页 ─────────────
        print("=" * 70)
        print("1️⃣  交易记录 (trades) 分页测试")
        print("=" * 70)

        # 先看 API 最大 limit 能给多少
        for limit in [100, 500, 1000, 5000, 10000]:
            r = await client.get(
                f"{DATA_API}/trades",
                params={"user": ADDRESS, "limit": limit, "offset": 0},
            )
            data = r.json()
            print(f"  limit={limit:>5d}, offset=0 → 返回 {len(data)} 条")

        # 完整分页拉取
        print("\n  完整分页拉取 (limit=5000):")
        all_trades = []
        offset = 0
        while True:
            r = await client.get(
                f"{DATA_API}/trades",
                params={"user": ADDRESS, "limit": 5000, "offset": offset},
            )
            batch = r.json()
            if not batch:
                break
            all_trades.extend(batch)
            print(f"    offset={offset:>5d} → 本页 {len(batch)} 条, 累计 {len(all_trades)}")
            if len(batch) < 5000:
                break
            offset += 5000

        print(f"\n  ✅ 总交易数: {len(all_trades)}")

        if all_trades:
            df = pd.DataFrame(all_trades)
            df["size"] = pd.to_numeric(df["size"], errors="coerce")
            df["price"] = pd.to_numeric(df["price"], errors="coerce")
            df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)

            print(f"  字段: {list(df.columns)}")
            print(f"  时间范围: {df['datetime'].min()} → {df['datetime'].max()}")
            print(f"  涉及市场数 (conditionId): {df['conditionId'].nunique()}")
            print(f"  涉及事件数 (eventSlug): {df['eventSlug'].nunique()}")

            # BUY/SELL 分布
            side_counts = df["side"].value_counts().to_dict()
            print(f"  BUY/SELL 分布: {side_counts}")

            # 按市场统计
            print(f"\n  📊 按市场统计:")
            market_stats = (
                df.groupby(["title", "outcome"])
                .agg(
                    trades=("side", "count"),
                    buys=("side", lambda x: (x == "BUY").sum()),
                    sells=("side", lambda x: (x == "SELL").sum()),
                    total_size=("size", "sum"),
                    first_trade=("datetime", "min"),
                    last_trade=("datetime", "max"),
                )
                .sort_values("total_size", ascending=False)
            )
            for (title, outcome), row in market_stats.iterrows():
                print(
                    f"    {title[:45]:45s} | {outcome:12s} | "
                    f"交易={row['trades']:>3.0f} (B:{row['buys']:.0f}/S:{row['sells']:.0f}) | "
                    f"金额=${row['total_size']:>14,.2f} | "
                    f"{str(row['first_trade'])[:10]} → {str(row['last_trade'])[:10]}"
                )

        # ── 2. 当前持仓 ──────────────────────────────────
        print("\n" + "=" * 70)
        print("2️⃣  当前持仓 (positions)")
        print("=" * 70)
        r = await client.get(f"{DATA_API}/positions", params={"user": ADDRESS})
        positions = r.json()
        print(f"  未平仓头寸: {len(positions)} 条")
        for p in positions:
            print(
                f"    {p.get('title', '?')[:45]:45s} | {p.get('outcome', '?'):8s} | "
                f"size={p.get('size', '?')}"
            )

        # ── 3. 已平仓 ────────────────────────────────────
        print("\n" + "=" * 70)
        print("3️⃣  已平仓 (closed-positions)")
        print("=" * 70)
        r = await client.get(f"{DATA_API}/closed-positions", params={"user": ADDRESS})
        closed = r.json()
        print(f"  已平仓头寸: {len(closed)} 条")
        total_api_pnl = 0
        for p in closed:
            pnl = float(p.get("realizedPnl", 0))
            total_api_pnl += pnl
            print(
                f"    {p.get('title', '?')[:45]:45s} | {p.get('outcome', '?'):12s} | "
                f"avgPrice={float(p.get('avgPrice', 0)):.4f} | "
                f"curPrice={p.get('curPrice')} | "
                f"PnL=${pnl:>+14,.2f} | "
                f"bought=${float(p.get('totalBought', 0)):>14,.2f}"
            )
        print(f"\n  API 总 PnL: ${total_api_pnl:+,.2f}")

        # ── 4. Activity ──────────────────────────────────
        print("\n" + "=" * 70)
        print("4️⃣  链上活动 (activity)")
        print("=" * 70)
        all_activity = []
        offset = 0
        while True:
            r = await client.get(
                f"{DATA_API}/activity",
                params={"user": ADDRESS, "limit": 1000, "offset": offset},
            )
            batch = r.json()
            if not batch:
                break
            all_activity.extend(batch)
            if len(batch) < 1000:
                break
            offset += 1000

        print(f"  活动记录: {len(all_activity)} 条")
        if all_activity:
            # 过滤出 dict 类型的记录
            dict_items = [a for a in all_activity if isinstance(a, dict)]
            other_items = [a for a in all_activity if not isinstance(a, dict)]
            print(f"  dict 记录: {len(dict_items)}, 其他: {len(other_items)}")

            if dict_items:
                # 找出字段名
                sample_keys = list(dict_items[0].keys())
                print(f"  字段: {sample_keys}")

                # 尝试找 type 字段（可能叫别的名字）
                type_field = None
                for k in ["type", "action", "event_type", "activity_type"]:
                    if k in dict_items[0]:
                        type_field = k
                        break

                if type_field:
                    types = Counter(a.get(type_field, "unknown") for a in dict_items)
                    print(f"  {type_field} 分布: {dict(types)}")
                else:
                    print(f"  样本: {dict_items[0]}")

            if other_items:
                print(f"  非 dict 样本: {other_items[:3]}")

        # ── 5. 数据缺口分析 ──────────────────────────────
        print("\n" + "=" * 70)
        print("5️⃣  数据缺口分析")
        print("=" * 70)
        if all_trades:
            trade_cids = set(df["conditionId"].unique())
            closed_cids = set(p["conditionId"] for p in closed)
            only_in_trades = trade_cids - closed_cids
            only_in_closed = closed_cids - trade_cids
            print(f"  trades 中的市场数: {len(trade_cids)}")
            print(f"  closed-positions 中的市场数: {len(closed_cids)}")
            print(f"  仅在 trades 中: {len(only_in_trades)} 个")
            print(f"  仅在 closed 中: {len(only_in_closed)} 个")

            if only_in_closed:
                print(f"\n  ⚠️ closed-positions 有但 trades 没有的市场:")
                for cid in only_in_closed:
                    match = [p for p in closed if p["conditionId"] == cid]
                    for m in match:
                        print(
                            f"    {m.get('title', '?')[:50]} | "
                            f"bought=${float(m.get('totalBought', 0)):,.2f}"
                        )


if __name__ == "__main__":
    asyncio.run(main())
