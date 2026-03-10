"""
PolymarketFetcher v3 全面功能测试

测试项:
  1. 上下文管理器
  2. 时间锚点分页 — 突破 4000 条限制
  3. 限流机制
  4. closed-positions
  5. positions
  6. fetch_all 并发
  7. 边界情况（空地址）
  8. Parquet 导出/加载
  9. 数据一致性
"""

import asyncio
import sys
import time
import shutil
from pathlib import Path

sys.path.insert(0, ".")

from polycopilot.fetcher import PolymarketFetcher

ADDR = "0x56687bf447db6ffa42ffe2204a05edaa20f55839"
EMPTY_ADDR = "0x0000000000000000000000000000000000000000"
TEST_DATA_DIR = "data/_test_output"

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name} — {detail}")


async def test_context_manager():
    print("\n── 1. 上下文管理器 ──────────────────────────────")
    async with PolymarketFetcher() as fetcher:
        check("客户端已创建", fetcher._client is not None)
    check("退出后客户端已关闭", fetcher._client.is_closed)

    bare = PolymarketFetcher()
    try:
        await bare._get("https://httpbin.org/get")
        check("未进入上下文应报错", False, "没有抛出异常")
    except RuntimeError as e:
        check("未进入上下文应报错", "async with" in str(e))


async def test_time_anchor_pagination():
    """核心测试：时间锚点分页突破 4000 条限制。"""
    print("\n── 2. 时间锚点分页 ─────────────────────────────")

    async with PolymarketFetcher() as fetcher:
        t0 = time.time()
        df = await fetcher.get_all_activity(ADDR)
        elapsed = time.time() - t0

    check("返回 DataFrame", hasattr(df, "shape"))
    check(f"数据量 > 4000 ({len(df)} 行)", len(df) > 4000,
          f"只有 {len(df)} 条，时间锚点可能未生效")
    check(f"耗时合理 ({elapsed:.1f}s < 60s)", elapsed < 60)

    # 必须字段
    required = ["type", "side", "size", "usdcSize", "price", "timestamp",
                 "conditionId", "title", "eventSlug", "outcome", "transactionHash"]
    missing = [c for c in required if c not in df.columns]
    check(f"必须字段完整 ({len(required)} 个)", len(missing) == 0, f"缺少: {missing}")

    # 类型覆盖
    types = set(df["type"].unique())
    check("包含 TRADE", "TRADE" in types)
    check("包含 REDEEM", "REDEEM" in types)
    check("包含 MERGE", "MERGE" in types)

    # 去重验证
    tx_keys = df.apply(
        lambda r: str(r.get("transactionHash", "")) + str(r.get("timestamp", "")) + str(r.get("type", "")),
        axis=1,
    )
    check(f"无重复记录", tx_keys.nunique() == len(df),
          f"有 {len(df) - tx_keys.nunique()} 条重复")

    # 时间跨度
    ts = df["timestamp"].astype(float)
    oldest = ts.min()
    newest = ts.max()
    from datetime import datetime, timezone
    oldest_dt = datetime.fromtimestamp(oldest, tz=timezone.utc)
    newest_dt = datetime.fromtimestamp(newest, tz=timezone.utc)
    span_days = (newest_dt - oldest_dt).days
    check(f"时间跨度 > 7 天 ({span_days} 天)", span_days > 7)
    print(f"      时间范围: {oldest_dt.strftime('%Y-%m-%d')} → {newest_dt.strftime('%Y-%m-%d')}")

    return df


async def test_rate_limiting():
    """验证限流机制。"""
    print("\n── 3. 限流机制 ─────────────────────────────────")

    async with PolymarketFetcher() as fetcher:
        # 快速发 6 次请求，第 5 次后应有 sleep
        t0 = time.time()
        for i in range(6):
            await fetcher._rate_limit()
        elapsed = time.time() - t0

        check(f"6 次请求后有限流延迟 ({elapsed:.2f}s >= 1s)", elapsed >= 0.9)
        check(f"请求计数器正确 ({fetcher._req_count})", fetcher._req_count == 6)


async def test_closed_positions():
    print("\n── 4. closed-positions ─────────────────────────")

    async with PolymarketFetcher() as fetcher:
        df = await fetcher.get_closed_positions(ADDR)

    check(f"有已平仓记录 ({len(df)} 条)", len(df) > 0)

    required = ["conditionId", "outcome", "avgPrice", "curPrice", "realizedPnl", "totalBought"]
    missing = [c for c in required if c not in df.columns]
    check("必须字段完整", len(missing) == 0, f"缺少: {missing}")

    prices = df["curPrice"].astype(float)
    check("结算价全为 0 或 1", all(p in (0, 1) for p in prices))

    total_pnl = df["realizedPnl"].astype(float).sum()
    check(f"PnL 量级正确 (~$22M, 实际 ${total_pnl/1e6:.1f}M)", total_pnl > 20_000_000)

    return df


async def test_positions():
    print("\n── 5. positions ────────────────────────────────")

    async with PolymarketFetcher() as fetcher:
        df = await fetcher.get_positions(ADDR)

    check("返回 DataFrame", hasattr(df, "shape"))
    check("当前无持仓 (已知)", df.empty)


async def test_fetch_all():
    print("\n── 6. fetch_all 并发获取 ───────────────────────")

    async with PolymarketFetcher() as fetcher:
        t0 = time.time()
        data = await fetcher.fetch_all(ADDR)
        elapsed = time.time() - t0

    check("返回 dict 含 3 个 key", set(data.keys()) == {"activity", "closed_positions", "positions"})
    check(f"activity > 4000 条 ({len(data['activity'])})", len(data["activity"]) > 4000)
    check(f"closed_positions 非空", not data["closed_positions"].empty)
    check(f"耗时合理 ({elapsed:.1f}s)", elapsed < 60)

    return data


async def test_empty_address():
    print("\n── 7. 边界情况（空地址） ────────────────────────")

    async with PolymarketFetcher() as fetcher:
        df = await fetcher.get_all_activity(EMPTY_ADDR)
        check("零地址 activity 为空", df.empty)

        df2 = await fetcher.get_closed_positions(EMPTY_ADDR)
        check("零地址 closed-positions 为空", df2.empty)

        df3 = await fetcher.get_positions(EMPTY_ADDR)
        check("零地址 positions 为空", df3.empty)


async def test_parquet(data: dict):
    print("\n── 8. Parquet 导出/加载 ────────────────────────")

    # 清理测试目录
    test_dir = Path(TEST_DATA_DIR)
    if test_dir.exists():
        shutil.rmtree(test_dir)

    # 导出
    saved = PolymarketFetcher.save_parquet(data, ADDR, output_dir=TEST_DATA_DIR)
    check(f"导出文件数 >= 2", len(saved) >= 2, f"只有 {len(saved)} 个")

    for key, path in saved.items():
        check(f"{key} 文件存在 ({path.stat().st_size / 1024:.0f} KB)", path.exists())

    # 加载
    loaded = PolymarketFetcher.load_parquet(ADDR, output_dir=TEST_DATA_DIR)
    check("加载 activity 行数一致",
          len(loaded.get("activity", [])) == len(data["activity"]),
          f"{len(loaded.get('activity', []))} vs {len(data['activity'])}")
    check("加载 closed_positions 行数一致",
          len(loaded.get("closed_positions", [])) == len(data["closed_positions"]))

    # 清理
    shutil.rmtree(test_dir, ignore_errors=True)


async def test_data_consistency(activity_df, closed_df):
    print("\n── 9. 数据一致性 ──────────────────────────────")

    closed_cids = set(closed_df["conditionId"].unique())
    activity_cids = set(activity_df["conditionId"].unique())

    overlap = closed_cids & activity_cids
    check(f"closed 市场在 activity 中有记录 ({len(overlap)}/{len(closed_cids)})",
          len(overlap) == len(closed_cids),
          f"缺失 {len(closed_cids) - len(overlap)} 个")

    # REDEEM 数 >= closed 数
    redeem_count = (activity_df["type"] == "REDEEM").sum()
    check(f"REDEEM 数 ({redeem_count}) >= closed 数 ({len(closed_df)})",
          redeem_count >= len(closed_df))

    # TRADE 无空 conditionId
    trades = activity_df[activity_df["type"] == "TRADE"]
    empty_cid = (trades["conditionId"] == "").sum()
    check("TRADE 无空 conditionId", empty_cid == 0, f"{empty_cid} 条为空")


async def main():
    global passed, failed

    print("=" * 60)
    print("  PolymarketFetcher v3 全面功能测试")
    print(f"  目标地址: {ADDR}")
    print("=" * 60)

    await test_context_manager()
    activity_df = await test_time_anchor_pagination()
    await test_rate_limiting()
    closed_df = await test_closed_positions()
    await test_positions()
    data = await test_fetch_all()
    await test_empty_address()
    await test_parquet(data)
    await test_data_consistency(activity_df, closed_df)

    print("\n" + "=" * 60)
    total = passed + failed
    print(f"  结果: {passed}/{total} 通过", end="")
    if failed:
        print(f" | {failed} 失败 ❌")
    else:
        print(" | 全部通过 🎉")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
