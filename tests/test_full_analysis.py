"""
全方位分析测试 v2.1 — Theo4 地址深度画像

串联 fetcher → processor → analyzer 三个模块，
对默认地址进行完整的数据采集、处理和量化分析。
所有分析逻辑统一由 analyzer 模块输出，测试文件不承载业务逻辑。
"""

import asyncio
import json
import sys

sys.path.insert(0, ".")

from polycopilot.fetcher import PolymarketFetcher
from polycopilot.processor import TradeProcessor
from polycopilot.analyzer import WalletAnalyzer

ADDR = "0x25e28169faea17421fcd4cc361f6436d1e449a09"
# "0xd0d6053c3c37e727402d84c14069780d360993aa" #高频地址
#"0xaa7a74b8c754e8aacc1ac2dedb699af0a3224d23"
SEP = "=" * 80
LINE = "─" * 80


def _bar(value, max_val, width=50):
    filled = int(value / max(max_val, 1) * width)
    return "█" * filled + "░" * (width - filled)


async def main():
    # ══════════════════════════════════════════════════════
    # 1. 数据采集
    # ══════════════════════════════════════════════════════
    print(f"\n{SEP}")
    print(f"  Theo4 钱包全方位分析 v2.2")
    print(f"  地址: {ADDR}")
    print(SEP)

    async with PolymarketFetcher() as fetcher:
        data = await fetcher.fetch_all(ADDR)

    activity = data["activity"]
    closed = data["closed_positions"]
    positions = data["positions"]
    freq_check = data.get("freq_check")

    # ── 高频预检结果展示 ──
    if freq_check and freq_check.get("is_high_freq"):
        print(f"\n{'╔' + '═'*58 + '╗'}")
        print(f"║{'':2s}🚨 高频地址预检命中 — 疑似做市商/机器人{'':8s}║")
        print(f"║{'':2s}交易频率: {freq_check['trades_per_hour']} 笔/小时{'':28s}║")
        span = freq_check.get('sample_time_span_hours', 0)
        print(f"║{'':2s}100 笔 TRADE 仅覆盖 {span:.1f} 小时{'':24s}║")
        print(f"║{'':2s}已跳过全量 activity 拉取，仅分析 closed-positions{'':2s}║")
        print(f"║{'':2s}结论: 不适合跟单{'':36s}║")
        print(f"{'╚' + '═'*58 + '╝'}")

    print(f"\n  数据采集完成:")
    print(f"    activity:          {len(activity):>5d} 条{'  (预检采样)' if freq_check and freq_check.get('is_high_freq') else ''}")
    print(f"    closed-positions:  {len(closed):>5d} 条")
    print(f"    positions:         {len(positions):>5d} 条")

    # ══════════════════════════════════════════════════════
    # 2. 数据处理
    # ══════════════════════════════════════════════════════
    proc = TradeProcessor(activity, closed)
    proc.clean()
    reports = proc.build_reports()

    # ══════════════════════════════════════════════════════
    # 3. 量化分析 (统一由 analyzer 输出)
    # ══════════════════════════════════════════════════════
    analyzer = WalletAnalyzer(reports, address=ADDR, raw_activity=activity, freq_check=freq_check)
    report = analyzer.generate_report()

    # ══════════════════════════════════════════════════════
    # 4. 逐市场详细分析
    # ══════════════════════════════════════════════════════
    print(f"\n{SEP}")
    print(f"  逐市场详细分析 ({len(reports)} 个头寸)")
    print(SEP)

    for i, r in enumerate(reports, 1):
        icon = "✅" if r.win_loss == "Win" else "❌" if r.win_loss == "Loss" else "⏳"
        print(f"\n{LINE}")
        print(f"  [{i:>2d}] {icon} {r.title}")
        print(f"      方向: {r.outcome} | 分类: {r.category} | 状态: {r.status}")
        print(f"      投入:     $ {r.total_invested:>14,.2f}")
        print(f"      PnL:      $ {r.realized_pnl:>+14,.2f}")
        print(f"      ROI:      {r.roi:>+12.1f}%")
        print(f"      均价:     {r.avg_entry_price:.4f} → 结算价: {r.settlement_price}")
        print(f"      Entry Edge: {r.entry_edge:+.4f} | 共识偏离: {r.consensus_deviation:+.4f}")
        print(f"      Timing:   {r.wallet_entry_timing_pct:.4f} (0=最早, 1=最晚)")
        print(f"      交易:     {r.trade_count} 笔 (BUY:{r.buy_count} / SELL:{r.sell_count})")
        print(f"      价格区间: [{r.price_min:.4f} ~ {r.price_max:.4f}]")
        if r.first_trade:
            ft = r.first_trade.strftime("%Y-%m-%d %H:%M:%S")
            lt = r.last_trade.strftime("%Y-%m-%d %H:%M:%S") if r.last_trade else "N/A"
            print(f"      时间:     {ft} → {lt} ({r.holding_hours:.1f}h)")
        if r.redeem_time:
            print(f"      REDEEM:   $ {r.redeem_usdc:>14,.2f} @ {r.redeem_time.strftime('%Y-%m-%d %H:%M:%S')}")
        if r.merge_usdc > 0:
            print(f"      MERGE:    $ {r.merge_usdc:>14,.2f}")

    # ══════════════════════════════════════════════════════
    # 5. 总览 (双口径)
    # ══════════════════════════════════════════════════════
    summary = report["summary"]
    oc = summary["outcome_level"]
    ev = summary["event_level"]

    print(f"\n{SEP}")
    print(f"  总览")
    print(SEP)
    print(f"  ── Outcome 级 ({oc['markets_closed']} 个头寸) ──")
    print(f"  总 PnL:       ${oc['total_pnl']:>+16,.2f}")
    print(f"  总投入:       $ {oc['total_invested']:>15,.2f}")
    print(f"  ROI:          {oc['roi_pct']:>+12.1f}%  ({oc['roi_note']})")
    print(f"  胜率:         {oc['win_rate_pct']:>12.1f}%  ({oc['wins']}胜 / {oc['losses']}负)")

    print(f"\n  ── Event 级 ({ev['event_count']} 个事件) ──")
    print(f"  总 PnL:       ${ev['event_total_pnl']:>+16,.2f}")
    print(f"  总投入:       $ {ev['event_total_invested']:>15,.2f}")
    print(f"  ROI:          {ev['event_roi_pct']:>+12.1f}%")
    print(f"  原始胜率:     {ev['raw_event_win_rate']*100:>12.1f}%  ({ev['event_wins']}胜 / {ev['event_losses']}负)")
    print(f"  Bayesian胜率: {ev['bayesian_event_win_rate']*100:>12.1f}%")
    print(f"\n  活跃期:       {summary['active_period']} ({summary['active_days']}天)")

    # ══════════════════════════════════════════════════════
    # 6. Event 级聚合
    # ══════════════════════════════════════════════════════
    print(f"\n{SEP}")
    print(f"  Event 级聚合 ({len(report['events'])} 个事件)")
    print(SEP)

    for e in report["events"]:
        icon = "✅" if e["event_win_flag"] else "❌"
        print(f"  {icon} {e['event_title'][:50]:50s}")
        print(f"     slug: {e['event_slug'][:45]}")
        print(f"     PnL: ${e['event_pnl']:>+14,.2f} | 投入: ${e['event_total_bought']:>14,.2f} | ROI: {e['event_roi']:>+.1f}%")
        print(f"     outcomes: {e['outcome_count']} | edge: {e['weighted_entry_edge']:+.4f} | cat: {e['category']}")

    # ══════════════════════════════════════════════════════
    # 7. 入场优势分析
    # ══════════════════════════════════════════════════════
    et = report["entry_timing"]
    print(f"\n{SEP}")
    print(f"  入场优势分析 (Entry Edge)")
    print(SEP)
    print(f"  加权 Entry Edge: {et['weighted_avg_entry_edge']:+.4f}")
    print(f"  简单 Entry Edge: {et['simple_avg_entry_edge']:+.4f}")
    print(f"  最强: {et['best_edge_market']}")
    print(f"  最弱: {et['worst_edge_market']}")

    print(f"\n  各市场 Entry Edge 排名:")
    for m in et["markets"]:
        icon = "✅" if m["win_loss"] == "Win" else "❌"
        print(f"    {icon} {m['entry_edge']:+.4f} | {m['title'][:40]:40s} | {m['outcome']:12s} | "
              f"入场={m['avg_entry_price']:.4f} → 结算={m['settlement_price']}")

    # ══════════════════════════════════════════════════════
    # 8. 分类利润贡献
    # ══════════════════════════════════════════════════════
    print(f"\n{SEP}")
    print(f"  分类利润贡献")
    print(SEP)

    cats = report["category_breakdown"]
    max_pnl = max(abs(c["pnl"]) for c in cats) if cats else 1
    for c in cats:
        bar = _bar(abs(c["pnl"]), max_pnl)
        print(f"  {c['category']:15s} | ${c['pnl']:>+16,.2f} | {c['pnl_share_pct']:>5.1f}% {bar}")
        print(f"  {'':15s} | 投入: ${c['total_invested']:>14,.2f} | 胜率: {c['win_rate_pct']:.0f}% | ROI: {c['avg_roi_pct']:+.1f}% | {c['market_count']} 个市场")

    # ══════════════════════════════════════════════════════
    # 9. 跟单压力测试 (三套情景)
    # ══════════════════════════════════════════════════════
    pt = report["pressure_test"]
    print(f"\n{SEP}")
    print(f"  跟单压力测试 (三套情景)")
    print(SEP)

    for name, scenario in pt.items():
        print(f"\n  ── {name} ──")
        print(f"  假设: {scenario['assumption_text']}")
        print(f"  峰值资金占用:   $ {scenario['peak_capital']:>14,.2f}")
        print(f"  建议起步资金:   $ {scenario['recommended_starting_capital']:>14,.2f}")
        print(f"  资金周转率:     {scenario['turnover']:>12.2f}x")

    # ══════════════════════════════════════════════════════
    # 10. 交易行为深度分析
    # ══════════════════════════════════════════════════════
    bh = report["behavior"]
    print(f"\n{SEP}")
    print(f"  交易行为深度分析")
    print(SEP)

    print(f"  策略类型:     {bh['strategy_type']}")
    print(f"  总交易笔数:   {bh['total_trades']} (BUY:{bh['total_buys']} / SELL:{bh['total_sells']})")

    hs = bh["holding_time_stats"]
    print(f"\n  持仓时长:")
    print(f"    最短: {hs['min_hours']:.1f}h | 最长: {hs['max_hours']:.1f}h | 中位: {hs['median_hours']:.1f}h | 均值: {hs['mean_hours']:.1f}h")

    # 持仓时间风险分析
    hr = bh.get("holding_risk", {})
    if hr:
        severity_icon = {
            "critical": "🚨", "high": "⚠️", "medium": "⚡", "low": "✅", "info": "ℹ️"
        }.get(hr.get("severity", "info"), "ℹ️")
        label_cn = {
            "market_maker_suspect": "做市商嫌疑",
            "scalper": "快进快出型",
            "short_term_trader": "短线交易者",
            "normal": "正常",
            "unknown": "未知",
        }.get(hr.get("label", "unknown"), hr.get("label", ""))

        print(f"\n  {severity_icon} 持仓时间风险评估:")
        print(f"    标签:       {label_cn} ({hr.get('label', '')})")
        print(f"    严重程度:   {hr.get('severity', 'unknown')}")
        print(f"    中位持仓:   {hr.get('median_hours', 0):.1f}h | 均值: {hr.get('mean_hours', 0):.1f}h")
        print(f"    < 1h 占比:  {hr.get('pct_under_1h', 0):.1f}%")
        print(f"    < 6h 占比:  {hr.get('pct_under_6h', 0):.1f}%")
        print(f"    < 24h 占比: {hr.get('pct_under_24h', 0):.1f}%")
        print(f"    每头寸交易: {hr.get('avg_trades_per_position', 0):.1f} 笔")
        print(f"    SELL 占比:  {hr.get('sell_ratio_pct', 0):.1f}%")

        signals = hr.get("signals", [])
        if signals:
            print(f"\n    检测到 {len(signals)} 个风险信号:")
            for sig in signals:
                s_icon = {"critical": "🚨", "high": "⚠️", "medium": "⚡"}.get(sig["severity"], "ℹ️")
                print(f"      {s_icon} [{sig['id']}] {sig['name']}: {sig['detail']}")

        print(f"\n    结论: {hr.get('verdict', '')}")

    pd_ = bh["position_distribution"]
    print(f"\n  仓位分布:")
    print(f"    最小: ${pd_['min']:>14,.2f} | 最大: ${pd_['max']:>14,.2f}")
    print(f"    中位: ${pd_['median']:>14,.2f} | 均值: ${pd_['mean']:>14,.2f}")
    print(f"    前3大仓位占比: {pd_['top3_share_pct']:.1f}%")

    wl = bh["win_loss_comparison"]
    print(f"\n  胜负对比:")
    print(f"    胜场 ({wl['win_count']}): 平均ROI={wl['win_avg_roi']:+.1f}% | 平均投入=${wl['win_avg_invested']:>14,.2f} | 总盈利=${wl['win_total_pnl']:>+14,.2f}")
    print(f"    败场 ({wl['loss_count']}): 平均ROI={wl['loss_avg_roi']:+.1f}% | 平均投入=${wl['loss_avg_invested']:>14,.2f} | 总亏损=${wl['loss_total_pnl']:>+14,.2f}")
    print(f"    盈亏比: {wl['profit_factor']}x")

    cc = bh["capital_concentration"]
    print(f"\n  PnL 集中度:")
    print(f"    Top 1 贡献: {cc['top1_pnl_share_pct']:.1f}%")
    print(f"    Top 3 贡献: {cc['top3_pnl_share_pct']:.1f}%")
    print(f"    Top 20% 贡献: {cc['top20pct_pnl_share_pct']:.1f}%")

    sz = bh["position_sizing_analysis"]
    print(f"\n  仓位分桶分析:")
    for bucket_name, label in [("top20pct", "大仓 top20%"), ("mid60pct", "中仓 mid60%"), ("bottom20pct", "小仓 bot20%")]:
        b = sz[bucket_name]
        print(f"    {label}: {b['count']}个 | ROI={b['avg_roi']:+.1f}% | 胜率={b['win_rate_pct']:.1f}%")

    wr = bh["weighted_roi_stats"]
    print(f"\n  ROI 统计 (加权 vs 简单):")
    print(f"    加权均值: {wr['weighted_mean_roi']:+.2f}% | 加权标准差: {wr['weighted_std_roi']:.2f}% | 加权MAD: {wr['weighted_mad_roi']:.2f}%")
    print(f"    简单均值: {wr['simple_mean_roi']:+.2f}% | 简单标准差: {wr['simple_std_roi']:.2f}%")

    # 入场价格分布
    epd = bh.get("entry_price_distribution", [])
    if epd:
        print(f"\n  入场价格分布:")
        print(f"    {'价格区间':10s} | {'数量':>5s} | {'胜率':>6s} | {'ROI':>8s} | {'总PnL':>12s}")
        print(f"    {'─'*10} | {'─'*5} | {'─'*6} | {'─'*8} | {'─'*12}")
        for b in epd:
            print(f"    {b['range']:10s} | {b['count']:>5d} | {b['win_rate_pct']:>5.1f}% | {b['avg_roi_pct']:>+7.1f}% | ${b['total_pnl']:>+11,.2f}")

    # ══════════════════════════════════════════════════════
    # 10.5 信心加权分析
    # ══════════════════════════════════════════════════════
    conv = report.get("conviction_analysis", {})
    if conv.get("status") == "ok":
        print(f"\n{SEP}")
        print(f"  信心加权分析 (仓位管理能力)")
        print(SEP)

        print(f"  中位投入: ${conv['median_investment']:>14,.2f} | 均值: ${conv['mean_investment']:>14,.2f}")
        print(f"  金额离散度: {conv['sizing_dispersion']:.1f}x (最大/最小)")
        print(f"  信心等级: {conv['conviction_grade']}")

        bks = conv["buckets"]
        print(f"\n  {'仓位档':10s} | {'事件数':>5s} | {'胜率':>6s} | {'ROI':>7s} | {'均投入':>12s} | {'均edge':>8s} | {'总PnL':>12s}")
        print(f"  {'─'*10} | {'─'*5} | {'─'*6} | {'─'*7} | {'─'*12} | {'─'*8} | {'─'*12}")
        for key in ["heavy", "medium", "light"]:
            b = bks[key]
            label_cn = {"heavy": "重仓 >2x", "medium": "中仓 0.5~2x", "light": "轻仓 <0.5x"}[key]
            if b["count"] == 0:
                print(f"  {label_cn:10s} | {'无':>5s} |")
            else:
                print(f"  {label_cn:10s} | {b['count']:>5d} | {b['win_rate_pct']:>5.1f}% | {b['roi_pct']:>+6.1f}% | ${b['avg_invested']:>11,.0f} | {b['avg_entry_edge']:>+7.4f} | ${b['total_pnl']:>+11,.0f}")

        spread = conv.get("conviction_spread_pp")
        if spread is not None:
            icon = "✅" if spread > 10 else "⚠️" if spread < -5 else "➖"
            print(f"\n  {icon} 信心价差: {spread:+.1f}pp (重仓胜率 - 轻仓胜率)")

        hlr = conv.get("heavy_loss_rate_pct")
        if hlr is not None:
            icon = "✅" if hlr < 20 else "⚠️"
            print(f"  {icon} 重仓亏损率: {hlr:.1f}%")
            for d in conv.get("heavy_loss_details", []):
                print(f"     ↳ ${d['invested']:>10,.0f} | {d['roi_pct']:>+6.1f}% | PnL ${d['pnl']:>+10,.0f} | {d['title']}")

        print(f"\n  跟单建议阈值: ${conv['follow_threshold']:>14,.2f} (> 1.5x 中位投入时跟单)")
        print(f"\n  结论: {conv['verdict']}")

    # ══════════════════════════════════════════════════════
    # 11. 跟单推荐指数
    # ══════════════════════════════════════════════════════
    cs = report["copy_trading_score"]
    bd = cs["breakdown"]
    si = cs["scoring_inputs"]

    print(f"\n{SEP}")
    print(f"  跟单推荐指数")
    print(SEP)
    print(f"  总分: {cs['total']}/100  等级: {cs['grade']}")

    dims = [
        ("胜率", bd["win_rate"], 20),
        ("ROI 稳定性", bd["roi_stability"], 15),
        ("Entry Edge", bd["entry_edge"], 20),
        ("样本量", bd["sample_size"], 15),
        ("分散度", bd["diversification"], 10),
        ("盈亏比", bd["profit_factor"], 10),
    ]
    for name, score, max_s in dims:
        bar = _bar(score, max_s, 20)
        print(f"\n  {name:15s} [{bar}] {score:>+5.1f} / {max_s}")
    print(f"\n  滑点惩罚{'':25s} {bd['slippage_penalty']:>+5.1f}")
    print(f"  持仓时间惩罚{'':21s} {bd.get('holding_time_penalty', 0):>+5.1f}")

    print(f"\n  评分输入:")
    print(f"    Bayesian event 胜率: {si['bayesian_event_win_rate']*100:.1f}%")
    print(f"    原始 event 胜率:     {si['raw_event_win_rate']*100:.1f}%")
    print(f"    event 数量:          {si['event_count']}")
    print(f"    活跃天数:            {si['active_days']}")
    print(f"    分类数:              {si['category_count']}")
    print(f"    加权 entry edge:     {si['weighted_avg_entry_edge']:+.4f}")
    print(f"    加权 MAD ROI:        {si['weighted_mad_roi']:.2f}%")
    print(f"    盈亏比 (PF):         {si['profit_factor']:.2f}x")
    print(f"    持仓风险标签:        {si.get('holding_risk_label', 'N/A')} ({si.get('holding_risk_severity', 'N/A')})")
    print(f"    中位持仓时间:        {si.get('median_holding_hours', 0):.1f}h")

    print(f"\n  风险提示:")
    for w in cs["risk_warnings"]:
        print(f"    ⚠️  {w}")

    # ══════════════════════════════════════════════════════
    # 12. 数据校验
    # ══════════════════════════════════════════════════════
    print(f"\n{SEP}")
    print(f"  数据校验")
    print(SEP)

    for v in report["validation"]:
        icon = {"pass": "✅", "warn": "⚠️", "fail": "❌", "unknown": "❓", "info": "ℹ️"}.get(v.get("status", ""), "?")
        print(f"\n  {icon} [{v['id']}] {v['name']}")
        if "detail" in v:
            print(f"     {v['detail']}")
        if "note" in v:
            print(f"     → {v['note']}")
        if "items" in v:
            for item in v["items"][:5]:
                print(f"       {item['title']:35s} | {item['outcome']:5s} | "
                      f"act=${item['activity_sum']:>12,.2f} vs closed=${item['closed_total']:>12,.2f} | "
                      f"覆盖={item['coverage_pct']:.1f}%")
            if len(v["items"]) > 5:
                print(f"       ... 共 {len(v['items'])} 项")
        if "field_assumptions" in v:
            for fa in v["field_assumptions"]:
                print(f"       {fa['field']:15s} | {fa['assumption']:45s} | {fa['status']:20s} | risk={fa['risk']}")
        if "top_issues" in v:
            for issue in v["top_issues"]:
                print(f"       {issue['title']:50s} | gap={issue['gap_hours']:>8.1f}h | endDate={issue['end_date']}")

    # ══════════════════════════════════════════════════════
    # 13. 保存报告
    # ══════════════════════════════════════════════════════
    path = analyzer.save_report()
    print(f"\n{SEP}")
    print(f"  JSON 报告: {path}")
    print(SEP)


if __name__ == "__main__":
    asyncio.run(main())
