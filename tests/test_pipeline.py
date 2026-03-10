"""
端到端测试：fetcher → processor → analyzer → JSON 报告

默认地址: 0x56687bf447db6ffa42ffe2204a05edaa20f55839 (Theo4)
"""

import asyncio
import json
import sys

sys.path.insert(0, ".")

from polycopilot.fetcher import PolymarketFetcher
from polycopilot.processor import TradeProcessor
from polycopilot.analyzer import WalletAnalyzer

DEFAULT_ADDR = "0x56687bf447db6ffa42ffe2204a05edaa20f55839"
SEP = "=" * 80


async def run(address: str):
    # ── 1. 数据采集 ───────────────────────────────────────
    print(f"\n{SEP}")
    print(f"  目标地址: {address}")
    print(SEP)

    async with PolymarketFetcher() as fetcher:
        data = await fetcher.fetch_all(address)

    activity = data["activity"]
    closed = data["closed_positions"]

    if activity.empty:
        print("该地址无活动记录")
        return

    # ── 2. 数据处理 ───────────────────────────────────────
    processor = TradeProcessor(activity, closed)
    processor.clean()
    reports = processor.build_reports()

    # ── 3. 量化分析 ───────────────────────────────────────
    analyzer = WalletAnalyzer(reports, address=address)
    report = analyzer.generate_report()

    # ── 4. 打印报告 ───────────────────────────────────────
    s = report["summary"]
    print(f"\n{SEP}")
    print(f"  总览")
    print(SEP)
    print(f"  总 PnL:     ${s['total_pnl']:>+14,.2f}")
    print(f"  总投入:     ${s['total_invested']:>14,.2f}")
    print(f"  ROI:        {s['roi_pct']:>+13.1f}%")
    print(f"  胜率:       {s['win_rate_pct']:>13.1f}%  ({s['wins']}胜/{s['losses']}负)")
    print(f"  已结算:     {s['markets_closed']:>13d} 个市场")
    print(f"  未结算:     {s['markets_open']:>13d} 个市场")
    print(f"  活跃期:     {s['active_period']} ({s['active_days']}天)")

    # 入场时机
    et = report["entry_timing"]
    print(f"\n{SEP}")
    print(f"  入场时机 (Alpha Timing)")
    print(SEP)
    print(f"  平均 Alpha: {et['avg_alpha_timing']:.4f} (越低越强)")
    print(f"  最强:       {et['best_alpha_market']}")
    print(f"  最弱:       {et['worst_alpha_market']}")

    # 分类
    print(f"\n{SEP}")
    print(f"  分类利润贡献")
    print(SEP)
    for cat in report["category_breakdown"]:
        print(f"  {cat['category']:15s} | PnL: ${cat['pnl']:>+14,.2f} ({cat['pnl_share_pct']:>5.1f}%) | "
              f"胜率: {cat['win_rate_pct']:>5.1f}% | ROI: {cat['avg_roi_pct']:>+6.1f}% | "
              f"市场: {cat['market_count']}")

    # 压力测试
    pt = report["pressure_test"]
    print(f"\n{SEP}")
    print(f"  跟单压力测试")
    print(SEP)
    print(f"  最大资金占用:   ${pt['max_notional_exposure']:>14,.2f}")
    print(f"  建议起步资金:   ${pt['recommended_min_capital']:>14,.2f}")
    print(f"  资金周转率:     {pt['capital_velocity']:>14.2f}x")

    # 评分
    cs = report["copy_trading_score"]
    print(f"\n{SEP}")
    print(f"  跟单推荐指数: {cs['total']}/100 ({cs['grade']})")
    print(SEP)
    bd = cs["breakdown"]
    print(f"  胜率:         {bd['win_rate']:>+6.1f} / 25")
    print(f"  ROI 稳定性:   {bd['roi_stability']:>+6.1f} / 20")
    print(f"  Alpha Timing: {bd['alpha_timing']:>+6.1f} / 20")
    print(f"  样本量:       {bd['sample_size']:>+6.1f} / 15")
    print(f"  分散度:       {bd['diversification']:>+6.1f} / 10")
    print(f"  滑点惩罚:     {bd['slippage_penalty']:>+6.1f}")

    if cs["risk_warnings"]:
        print(f"\n  风险提示:")
        for w in cs["risk_warnings"]:
            print(f"    - {w}")

    # ── 5. 保存 JSON ─────────────────────────────────────
    path = analyzer.save_report()
    print(f"\n{SEP}")
    print(f"  JSON 报告已保存: {path}")
    print(SEP)

    # ── 6. 验证 ──────────────────────────────────────────
    print(f"\n{SEP}")
    print(f"  数据验证")
    print(SEP)

    # PnL 应与 closed-positions API 一致
    api_pnl = closed["realizedPnl"].astype(float).sum()
    our_pnl = s["total_pnl"]
    pnl_match = abs(api_pnl - our_pnl) < 1
    print(f"  PnL 一致性:  {'PASS' if pnl_match else 'FAIL'} (API=${api_pnl:+,.2f} vs 报告=${our_pnl:+,.2f})")

    # 评分范围
    score_valid = 0 <= cs["total"] <= 100
    print(f"  评分范围:    {'PASS' if score_valid else 'FAIL'} ({cs['total']})")

    # 等级映射
    grade_valid = cs["grade"] in ("S", "A", "B", "C", "D")
    print(f"  等级有效:    {'PASS' if grade_valid else 'FAIL'} ({cs['grade']})")

    # JSON 必须字段
    required_keys = ["address", "summary", "entry_timing", "category_breakdown",
                     "pressure_test", "copy_trading_score"]
    missing = [k for k in required_keys if k not in report]
    json_valid = len(missing) == 0
    print(f"  JSON 完整性: {'PASS' if json_valid else 'FAIL'} (缺少: {missing})")

    all_pass = pnl_match and score_valid and grade_valid and json_valid
    print(f"\n  {'ALL PASS' if all_pass else 'SOME FAILED'}")
    print(SEP)


if __name__ == "__main__":
    addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDR
    asyncio.run(run(addr))
