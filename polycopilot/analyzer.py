"""
WalletAnalyzer — 量化分析与跟单评分模块 v2.1

基于 processor 输出的 MarketReport 列表，执行：
1. Event 级聚合（outcome → event）
2. 入场优势分析（entry_edge + wallet_entry_timing_pct）
3. 分类利润贡献度
4. 跟单压力测试（三套假设驱动情景）
5. 交易行为深度分析
6. 跟单推荐指数（event 级六维评分）
7. 数据校验（7 项程序化 + 1 项 assumption audit）
8. JSON 报告输出（双口径：outcome 级 + event 级）
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from polycopilot.processor import MarketReport


# ═══════════════════════════════════════════════════════════
# WalletAnalyzer
# ═══════════════════════════════════════════════════════════

class WalletAnalyzer:
    """钱包量化分析器 v2.1。"""

    def __init__(
        self,
        reports: list[MarketReport],
        address: str = "",
        raw_activity: pd.DataFrame | None = None,
        freq_check: dict | None = None,
    ):
        self._reports = reports
        self._address = address
        self._raw_activity = raw_activity  # 用于 validate()
        self._freq_check = freq_check  # 高频预检结果
        self._closed = [r for r in reports if r.status == "Closed"]
        self._open = [r for r in reports if r.status == "Open"]
        self._events: list[dict] | None = None  # lazy

    # ── 0. Event 级聚合 ───────────────────────────────────

    def _aggregate_events(self) -> list[dict]:
        """按 event_slug 聚合 outcome 为 event 级数据。"""
        if self._events is not None:
            return self._events

        groups: dict[str, list[MarketReport]] = defaultdict(list)
        for r in self._closed:
            groups[r.event_slug or f"_orphan_{r.condition_id}"].append(r)

        events = []
        for slug, outcomes in groups.items():
            pnl = sum(r.realized_pnl for r in outcomes)
            invested = sum(r.total_invested for r in outcomes)
            # event_title = 投入最大的 outcome 的 title
            primary = max(outcomes, key=lambda r: r.total_invested)
            events.append({
                "event_slug": slug,
                "event_title": primary.title,
                "category": primary.category,
                "event_pnl": round(pnl, 2),
                "event_total_bought": round(invested, 2),
                "event_roi": round(pnl / invested * 100, 2) if invested > 0 else 0.0,
                "event_win_flag": pnl > 0,
                "outcome_count": len(outcomes),
                "outcomes": outcomes,
                # 加权 entry_edge (按投入加权)
                "weighted_entry_edge": round(
                    sum(r.entry_edge * r.total_invested for r in outcomes) / invested
                    if invested > 0 else 0.0, 6
                ),
            })

        self._events = sorted(events, key=lambda e: e["event_pnl"], reverse=True)
        return self._events

    @property
    def events(self) -> list[dict]:
        return self._aggregate_events()

    # ── 1. 入场优势分析 ───────────────────────────────────

    def analyze_entry_timing(self) -> dict:
        """
        双指标入场分析：
        - entry_edge: settlement_price - avg_entry_price (统一定义)
        - wallet_entry_timing_pct: 钱包在事件上的入场时间位置
        """
        if not self._closed:
            return {"avg_entry_edge": 0, "markets": []}

        markets = []
        for r in self._closed:
            markets.append({
                "title": r.title,
                "outcome": r.outcome,
                "avg_entry_price": r.avg_entry_price,
                "settlement_price": r.settlement_price,
                "entry_edge": r.entry_edge,
                "wallet_entry_timing_pct": r.wallet_entry_timing_pct,
                "win_loss": r.win_loss,
                "total_invested": r.total_invested,
            })

        markets.sort(key=lambda m: m["entry_edge"], reverse=True)

        # 加权 entry_edge
        total_inv = sum(r.total_invested for r in self._closed)
        weighted_edge = (
            sum(r.entry_edge * r.total_invested for r in self._closed) / total_inv
            if total_inv > 0 else 0.0
        )
        simple_edge = np.mean([r.entry_edge for r in self._closed])

        best = max(self._closed, key=lambda r: r.entry_edge)
        worst = min(self._closed, key=lambda r: r.entry_edge)

        return {
            "weighted_avg_entry_edge": round(weighted_edge, 4),
            "simple_avg_entry_edge": round(float(simple_edge), 4),
            "best_edge_market": f"{best.title} ({best.outcome}, edge={best.entry_edge:+.4f})",
            "worst_edge_market": f"{worst.title} ({worst.outcome}, edge={worst.entry_edge:+.4f})",
            "markets": markets,
        }

    # ── 2. 分类利润贡献 ───────────────────────────────────

    def analyze_categories(self) -> list[dict]:
        if not self._closed:
            return []

        cats: dict[str, list[MarketReport]] = defaultdict(list)
        for r in self._closed:
            cats[r.category].append(r)

        total_pnl = sum(r.realized_pnl for r in self._closed)
        result = []
        for cat, markets in sorted(cats.items(), key=lambda x: sum(r.realized_pnl for r in x[1]), reverse=True):
            pnl = sum(r.realized_pnl for r in markets)
            invested = sum(r.total_invested for r in markets)
            wins = sum(1 for r in markets if r.win_loss == "Win")
            result.append({
                "category": cat,
                "pnl": round(pnl, 2),
                "total_invested": round(invested, 2),
                "pnl_share_pct": round(pnl / total_pnl * 100, 1) if total_pnl else 0,
                "win_rate_pct": round(wins / len(markets) * 100, 1),
                "avg_roi_pct": round(np.mean([r.roi for r in markets]), 1),
                "market_count": len(markets),
            })
        return result

    # ── 3. 跟单压力测试（三套假设驱动情景） ────────────────

    def analyze_pressure(self) -> dict:
        """
        三套资金占用情景：
        - redeem_based: 按 REDEEM 时间释放
        - resolution_based: 按 endDate + 24h 释放
        - time_based_estimate: 按 endDate 释放
        """
        if not self._closed:
            empty = {"peak_capital": 0, "recommended_starting_capital": 0,
                     "turnover": 0, "assumption_text": "无数据"}
            return {"redeem_based": empty, "resolution_based": empty,
                    "time_based_estimate": empty}

        total_invested = sum(r.total_invested for r in self._closed)

        def _calc_scenario(release_fn) -> dict:
            events: list[tuple[pd.Timestamp, float]] = []
            for r in self._closed:
                amount = r.total_invested
                if amount <= 0:
                    continue
                # 锁定：第一笔 BUY 时间
                lock_time = r.first_trade
                if lock_time is None:
                    continue
                events.append((lock_time, amount))
                # 释放
                release_time = release_fn(r)
                if release_time is not None:
                    events.append((release_time, -amount))

            if not events:
                return {"peak_capital": 0, "recommended_starting_capital": 0,
                        "turnover": 0, "assumption_text": ""}

            events.sort(key=lambda x: x[0])
            running = 0.0
            peak = 0.0
            for _, delta in events:
                running += delta
                peak = max(peak, running)

            turnover = round(total_invested / peak, 2) if peak > 0 else 0
            return {
                "peak_capital": round(peak, 2),
                "recommended_starting_capital": round(peak * 1.2, 2),
                "turnover": turnover,
            }

        # 情景 1: REDEEM 时间释放
        def _release_redeem(r: MarketReport):
            if r.redeem_time is not None:
                return r.redeem_time
            if r.end_date:
                try:
                    return pd.Timestamp(r.end_date) + timedelta(hours=24)
                except Exception:
                    pass
            return None

        # 情景 2: endDate + 24h 释放
        def _release_resolution(r: MarketReport):
            if r.end_date:
                try:
                    return pd.Timestamp(r.end_date) + timedelta(hours=24)
                except Exception:
                    pass
            return r.redeem_time

        # 情景 3: endDate 释放
        def _release_time(r: MarketReport):
            if r.end_date:
                try:
                    return pd.Timestamp(r.end_date)
                except Exception:
                    pass
            return r.redeem_time

        s1 = _calc_scenario(_release_redeem)
        s1["assumption_text"] = "资金在 REDEEM 链上操作完成后释放（最保守）"

        s2 = _calc_scenario(_release_resolution)
        s2["assumption_text"] = "资金在事件 endDate + 24h 后释放（结果明确后安全余量）"

        s3 = _calc_scenario(_release_time)
        s3["assumption_text"] = "资金在事件 endDate 到期后立即释放（最乐观）"

        return {
            "redeem_based": s1,
            "resolution_based": s2,
            "time_based_estimate": s3,
        }

    # ── 3.5 信心加权分析 ──────────────────────────────────

    def analyze_conviction(self) -> dict:
        """
        分析聪明钱在不同事件上的下注金额差异，判断其仓位管理能力。

        核心逻辑：
        - 按投入金额分三档（重仓 >2x中位、中仓 0.5x~2x中位、轻仓 <0.5x中位）
        - 对比各档的胜率、ROI、entry edge
        - 如果重仓胜率 > 轻仓胜率，说明该地址"知道什么时候该重仓"
        - 输出跟单建议阈值
        """
        events = self.events
        if len(events) < 5:
            return {
                "status": "insufficient_data",
                "detail": f"仅 {len(events)} 个事件，不足以分析仓位信心",
            }

        invs = [e["event_total_bought"] for e in events]
        median_inv = float(np.median(invs))
        mean_inv = float(np.mean(invs))

        # 分三档
        heavy = [e for e in events if e["event_total_bought"] > median_inv * 2]
        medium = [e for e in events if median_inv * 0.5 <= e["event_total_bought"] <= median_inv * 2]
        light = [e for e in events if e["event_total_bought"] < median_inv * 0.5]

        def _bucket_stats(group: list[dict], label: str) -> dict:
            if not group:
                return {"label": label, "count": 0}
            wins = sum(1 for e in group if e["event_win_flag"])
            total_inv = sum(e["event_total_bought"] for e in group)
            total_pnl = sum(e["event_pnl"] for e in group)
            edges = [e["weighted_entry_edge"] for e in group]
            return {
                "label": label,
                "count": len(group),
                "wins": wins,
                "win_rate_pct": round(wins / len(group) * 100, 1),
                "total_invested": round(total_inv, 2),
                "total_pnl": round(total_pnl, 2),
                "roi_pct": round(total_pnl / total_inv * 100, 1) if total_inv > 0 else 0,
                "avg_invested": round(total_inv / len(group), 2),
                "avg_entry_edge": round(float(np.mean(edges)), 4) if edges else 0,
            }

        heavy_stats = _bucket_stats(heavy, "heavy")
        medium_stats = _bucket_stats(medium, "medium")
        light_stats = _bucket_stats(light, "light")

        # ── 信心加权评分 ──
        # 重仓胜率 vs 轻仓胜率差值
        heavy_wr = heavy_stats.get("win_rate_pct", 0) if heavy_stats["count"] > 0 else None
        light_wr = light_stats.get("win_rate_pct", 0) if light_stats["count"] > 0 else None

        if heavy_wr is not None and light_wr is not None:
            conviction_spread = round(heavy_wr - light_wr, 1)
        else:
            conviction_spread = None

        # 重仓亏损率
        heavy_losses = [e for e in heavy if not e["event_win_flag"]]
        heavy_loss_rate = round(len(heavy_losses) / len(heavy) * 100, 1) if heavy else None
        heavy_loss_details = [
            {
                "title": e["event_title"][:60],
                "invested": e["event_total_bought"],
                "pnl": e["event_pnl"],
                "roi_pct": e["event_roi"],
            }
            for e in sorted(heavy_losses, key=lambda x: x["event_pnl"])
        ] if heavy_losses else []

        # 金额离散度
        max_inv = max(invs)
        min_inv = min(invs) if min(invs) > 0 else 1
        sizing_dispersion = round(max_inv / min_inv, 1)

        # 跟单建议阈值：中位数的 1.5 倍
        follow_threshold = round(median_inv * 1.5, 2)

        # ── 综合判定 ──
        if conviction_spread is not None and conviction_spread > 10 and heavy_loss_rate is not None and heavy_loss_rate < 20:
            verdict = (
                f"该地址具备优秀的仓位管理能力：重仓胜率高于轻仓 {conviction_spread}pp，"
                f"重仓亏损率仅 {heavy_loss_rate}%。"
                f"建议跟单其投入 > ${follow_threshold:,.0f} 的交易（信心信号强）。"
            )
            conviction_grade = "strong"
        elif conviction_spread is not None and conviction_spread > 0:
            verdict = (
                f"该地址重仓胜率略高于轻仓 ({conviction_spread}pp)，"
                f"仓位管理能力一般。跟单时不必区分金额大小。"
            )
            conviction_grade = "moderate"
        elif conviction_spread is not None and conviction_spread < -5:
            verdict = (
                f"⚠️ 该地址重仓胜率反而低于轻仓 ({conviction_spread}pp)，"
                f"说明其在高信心时判断力更差。跟单大额交易风险更高。"
            )
            conviction_grade = "weak"
        else:
            verdict = "数据不足或重仓/轻仓样本太少，无法判定仓位管理能力。"
            conviction_grade = "unknown"

        return {
            "status": "ok",
            "conviction_grade": conviction_grade,
            "median_investment": round(median_inv, 2),
            "mean_investment": round(mean_inv, 2),
            "sizing_dispersion": sizing_dispersion,
            "follow_threshold": follow_threshold,
            "conviction_spread_pp": conviction_spread,
            "heavy_loss_rate_pct": heavy_loss_rate,
            "heavy_loss_details": heavy_loss_details,
            "buckets": {
                "heavy": heavy_stats,
                "medium": medium_stats,
                "light": light_stats,
            },
            "verdict": verdict,
        }

    # ── 4. 交易行为深度分析 ────────────────────────────────

    def analyze_behavior(self) -> dict:
        """统一的行为分析，输出结构化 dict。"""
        closed = self._closed
        if not closed:
            return {}

        total_buys = sum(r.buy_count for r in closed)
        total_sells = sum(r.sell_count for r in closed)
        total_trades = total_buys + total_sells

        # 策略特征
        if total_sells == 0:
            strategy = "buy_and_hold"
        elif total_sells / max(total_trades, 1) < 0.1:
            strategy = "mixed"
        else:
            strategy = "active_trading"

        # 持仓时长
        hours = [r.holding_hours for r in closed if r.holding_hours > 0]
        holding_stats = {
            "min_hours": round(min(hours), 1) if hours else 0,
            "max_hours": round(max(hours), 1) if hours else 0,
            "median_hours": round(float(np.median(hours)), 1) if hours else 0,
            "mean_hours": round(float(np.mean(hours)), 1) if hours else 0,
        }

        # 仓位分布
        investments = sorted([r.total_invested for r in closed], reverse=True)
        top3_share = sum(investments[:3]) / sum(investments) * 100 if investments else 0
        position_dist = {
            "min": round(min(investments), 2) if investments else 0,
            "max": round(max(investments), 2) if investments else 0,
            "median": round(float(np.median(investments)), 2) if investments else 0,
            "mean": round(float(np.mean(investments)), 2) if investments else 0,
            "top3_share_pct": round(top3_share, 1),
        }

        # 胜负对比
        wins = [r for r in closed if r.win_loss == "Win"]
        losses = [r for r in closed if r.win_loss == "Loss"]
        win_pnl = sum(r.realized_pnl for r in wins)
        loss_pnl = abs(sum(r.realized_pnl for r in losses))
        profit_factor = round(win_pnl / loss_pnl, 1) if loss_pnl > 0 else float("inf")

        win_loss_comp = {
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_avg_roi": round(float(np.mean([r.roi for r in wins])), 1) if wins else 0,
            "loss_avg_roi": round(float(np.mean([r.roi for r in losses])), 1) if losses else 0,
            "win_avg_invested": round(float(np.mean([r.total_invested for r in wins])), 2) if wins else 0,
            "loss_avg_invested": round(float(np.mean([r.total_invested for r in losses])), 2) if losses else 0,
            "win_total_pnl": round(win_pnl, 2),
            "loss_total_pnl": round(-loss_pnl, 2),
            "profit_factor": profit_factor,
        }

        # 资金集中度 (PnL 贡献)
        total_pnl = sum(r.realized_pnl for r in closed)
        sorted_by_pnl = sorted(closed, key=lambda r: r.realized_pnl, reverse=True)
        top1_pnl = sorted_by_pnl[0].realized_pnl if sorted_by_pnl else 0
        top3_pnl = sum(r.realized_pnl for r in sorted_by_pnl[:3])
        n20 = max(1, len(closed) // 5)
        top20_pnl = sum(r.realized_pnl for r in sorted_by_pnl[:n20])

        capital_concentration = {
            "top1_pnl_share_pct": round(top1_pnl / total_pnl * 100, 1) if total_pnl else 0,
            "top3_pnl_share_pct": round(top3_pnl / total_pnl * 100, 1) if total_pnl else 0,
            "top20pct_pnl_share_pct": round(top20_pnl / total_pnl * 100, 1) if total_pnl else 0,
        }

        # 分桶分析 (按投入金额排序)
        sorted_by_inv = sorted(closed, key=lambda r: r.total_invested, reverse=True)
        n = len(sorted_by_inv)
        n_top = max(1, n // 5)
        n_bot = max(1, n // 5)
        top_bucket = sorted_by_inv[:n_top]
        bot_bucket = sorted_by_inv[-n_bot:] if n_bot < n else sorted_by_inv[-1:]
        mid_bucket = sorted_by_inv[n_top:n - n_bot] if n > n_top + n_bot else []

        def _bucket_stats(bucket):
            if not bucket:
                return {"avg_roi": 0, "win_rate_pct": 0, "count": 0}
            return {
                "avg_roi": round(float(np.mean([r.roi for r in bucket])), 1),
                "win_rate_pct": round(sum(1 for r in bucket if r.win_loss == "Win") / len(bucket) * 100, 1),
                "count": len(bucket),
            }

        sizing_analysis = {
            "top20pct": _bucket_stats(top_bucket),
            "mid60pct": _bucket_stats(mid_bucket),
            "bottom20pct": _bucket_stats(bot_bucket),
        }

        # 加权 ROI 指标
        total_inv = sum(r.total_invested for r in closed)
        rois = np.array([r.roi for r in closed])
        weights = np.array([r.total_invested for r in closed])
        w_norm = weights / weights.sum() if weights.sum() > 0 else weights

        weighted_mean_roi = float(np.average(rois, weights=weights)) if total_inv > 0 else 0
        weighted_std_roi = float(np.sqrt(np.average((rois - weighted_mean_roi) ** 2, weights=weights))) if total_inv > 0 else 0
        weighted_mad_roi = float(np.average(np.abs(rois - weighted_mean_roi), weights=weights)) if total_inv > 0 else 0

        # 入场价格分布分桶 (0-10%, 10-20%, ..., 90-100%)
        price_buckets: dict[str, dict] = {}
        for r in closed:
            bucket_idx = min(int(r.avg_entry_price * 10), 9)
            key = f"{bucket_idx * 10}-{(bucket_idx + 1) * 10}%"
            if key not in price_buckets:
                price_buckets[key] = {"count": 0, "wins": 0, "total_pnl": 0.0, "total_invested": 0.0}
            price_buckets[key]["count"] += 1
            if r.win_loss == "Win":
                price_buckets[key]["wins"] += 1
            price_buckets[key]["total_pnl"] += r.realized_pnl
            price_buckets[key]["total_invested"] += r.total_invested

        entry_price_dist = []
        for key in sorted(price_buckets.keys(), key=lambda k: int(k.split("-")[0])):
            b = price_buckets[key]
            entry_price_dist.append({
                "range": key,
                "count": b["count"],
                "win_rate_pct": round(b["wins"] / b["count"] * 100, 1) if b["count"] > 0 else 0,
                "avg_roi_pct": round(b["total_pnl"] / b["total_invested"] * 100, 1) if b["total_invested"] > 0 else 0,
                "total_pnl": round(b["total_pnl"], 2),
            })

        # ── 持仓时间风险分析 ──
        # 检测做市商 / 高频 / 快进快出 地址
        holding_risk = self._analyze_holding_risk(closed, hours)

        return {
            "strategy_type": strategy,
            "total_trades": total_trades,
            "total_buys": total_buys,
            "total_sells": total_sells,
            "holding_time_stats": holding_stats,
            "holding_risk": holding_risk,
            "position_distribution": position_dist,
            "win_loss_comparison": win_loss_comp,
            "capital_concentration": capital_concentration,
            "position_sizing_analysis": sizing_analysis,
            "weighted_roi_stats": {
                "weighted_mean_roi": round(weighted_mean_roi, 2),
                "weighted_std_roi": round(weighted_std_roi, 2),
                "weighted_mad_roi": round(weighted_mad_roi, 2),
                "simple_mean_roi": round(float(np.mean(rois)), 2),
                "simple_std_roi": round(float(np.std(rois)), 2),
            },
            "entry_price_distribution": entry_price_dist,
        }

    # ── 4.5 持仓时间风险分析 ─────────────────────────────

    def _analyze_holding_risk(self, closed: list[MarketReport], valid_hours: list[float]) -> dict:
        """
        检测做市商 / 高频交易 / 快进快出 地址。

        判定逻辑（多维度交叉验证）：
        ─────────────────────────────────────────────────
        1. 中位持仓时间 < 1h → 极高频（疑似做市商/机器人）
        2. 中位持仓时间 < 6h → 高频短线
        3. 中位持仓时间 < 24h → 短线交易者
        4. 超过 50% 头寸持仓 < 1h → 做市商特征
        5. 超过 70% 头寸持仓 < 6h → 快进快出特征
        6. 平均每头寸交易笔数 > 10 → 频繁调仓（做市商行为）
        7. SELL 占比 > 40% + 中位持仓 < 6h → 主动做市特征
        """
        n_closed = len(closed)
        if not valid_hours or n_closed == 0:
            return {
                "label": "unknown",
                "severity": "info",
                "median_hours": 0,
                "mean_hours": 0,
                "pct_under_1h": 0,
                "pct_under_6h": 0,
                "pct_under_24h": 0,
                "avg_trades_per_position": 0,
                "sell_ratio_pct": 0,
                "signals": [],
                "verdict": "持仓时间数据不足，无法判定",
            }

        median_h = float(np.median(valid_hours))
        mean_h = float(np.mean(valid_hours))
        pct_under_1h = sum(1 for h in valid_hours if h < 1) / len(valid_hours) * 100
        pct_under_6h = sum(1 for h in valid_hours if h < 6) / len(valid_hours) * 100
        pct_under_24h = sum(1 for h in valid_hours if h < 24) / len(valid_hours) * 100

        total_trades = sum(r.buy_count + r.sell_count for r in closed)
        avg_trades_per_pos = total_trades / n_closed
        total_sells = sum(r.sell_count for r in closed)
        sell_ratio = total_sells / max(total_trades, 1) * 100

        # ── 信号检测 ──
        signals: list[dict] = []

        # S1: 极高频
        if median_h < 1:
            signals.append({
                "id": "S1", "name": "极高频交易",
                "detail": f"中位持仓 {median_h:.1f}h < 1h",
                "severity": "critical",
            })

        # S2: 高频短线
        elif median_h < 6:
            signals.append({
                "id": "S2", "name": "高频短线",
                "detail": f"中位持仓 {median_h:.1f}h < 6h",
                "severity": "high",
            })

        # S3: 短线交易者
        elif median_h < 24:
            signals.append({
                "id": "S3", "name": "短线交易者",
                "detail": f"中位持仓 {median_h:.1f}h < 24h",
                "severity": "medium",
            })

        # S4: 做市商特征 — 超半数头寸 < 1h
        if pct_under_1h > 50:
            signals.append({
                "id": "S4", "name": "做市商特征",
                "detail": f"{pct_under_1h:.0f}% 头寸持仓 < 1h",
                "severity": "critical",
            })

        # S5: 快进快出 — 超 70% 头寸 < 6h
        if pct_under_6h > 70:
            signals.append({
                "id": "S5", "name": "快进快出",
                "detail": f"{pct_under_6h:.0f}% 头寸持仓 < 6h",
                "severity": "high",
            })

        # S6: 频繁调仓
        if avg_trades_per_pos > 10:
            signals.append({
                "id": "S6", "name": "频繁调仓",
                "detail": f"平均每头寸 {avg_trades_per_pos:.1f} 笔交易",
                "severity": "high",
            })

        # S7: 主动做市特征
        if sell_ratio > 40 and median_h < 6:
            signals.append({
                "id": "S7", "name": "主动做市特征",
                "detail": f"SELL 占比 {sell_ratio:.0f}% + 中位持仓 {median_h:.1f}h",
                "severity": "critical",
            })

        # ── 综合判定 ──
        severities = [s["severity"] for s in signals]
        has_critical = "critical" in severities
        has_high = "high" in severities
        n_signals = len(signals)

        if has_critical or n_signals >= 3:
            label = "market_maker_suspect"
            severity = "critical"
            verdict = (
                "🚨 严重警告：该地址高度疑似做市商/高频机器人，"
                "不适合跟单。做市商的盈利来自价差和流动性提供，"
                "普通用户无法复制其策略，跟单将面临严重滑点和反向选择风险。"
            )
        elif has_high or n_signals >= 2:
            label = "scalper"
            severity = "high"
            verdict = (
                "⚠️ 高风险警告：该地址为快进快出型短线交易者，"
                "持仓时间极短，跟单延迟将导致入场价格严重偏离，"
                "不建议跟单。"
            )
        elif n_signals >= 1:
            label = "short_term_trader"
            severity = "medium"
            verdict = (
                "⚠️ 注意：该地址偏短线操作，跟单需要极快的执行速度，"
                "建议仅在自动化跟单系统下谨慎使用。"
            )
        else:
            label = "normal"
            severity = "low"
            verdict = "持仓时间正常，适合跟单。"

        logger.info(f"持仓风险分析 | label={label} severity={severity} signals={n_signals}")

        return {
            "label": label,
            "severity": severity,
            "median_hours": round(median_h, 1),
            "mean_hours": round(mean_h, 1),
            "pct_under_1h": round(pct_under_1h, 1),
            "pct_under_6h": round(pct_under_6h, 1),
            "pct_under_24h": round(pct_under_24h, 1),
            "avg_trades_per_position": round(avg_trades_per_pos, 1),
            "sell_ratio_pct": round(sell_ratio, 1),
            "signals": signals,
            "verdict": verdict,
        }

    # ── 5. 数据校验 ───────────────────────────────────────

    def validate(self, raw_activity: pd.DataFrame | None = None) -> list[dict]:
        """
        7 项程序化校验 + 1 项 assumption audit。
        每项输出: {id, name, status, detail}
        status: pass / warn / fail / unknown
        """
        act = raw_activity if raw_activity is not None else self._raw_activity
        checks: list[dict] = []

        # ── V1: activity BUY usdcSize vs closed totalBought ──
        if act is not None and not act.empty:
            act_copy = act.copy()
            act_copy["usdcSize"] = pd.to_numeric(act_copy.get("usdcSize"), errors="coerce").fillna(0)
            buy_trades = act_copy[(act_copy.get("type") == "TRADE")]
            if "side" in buy_trades.columns:
                buy_trades = buy_trades[buy_trades["side"] == "BUY"]

            coverage_details = []
            for r in self._closed:
                mask = buy_trades["conditionId"] == r.condition_id
                if "outcome" in buy_trades.columns:
                    mask = mask & (buy_trades["outcome"] == r.outcome)
                act_sum = float(buy_trades.loc[mask, "usdcSize"].sum())
                pct = round(act_sum / r.total_invested * 100, 1) if r.total_invested > 0 else 0
                coverage_details.append({"title": r.title[:35], "outcome": r.outcome,
                                         "activity_sum": round(act_sum, 2),
                                         "closed_total": r.total_invested, "coverage_pct": pct})

            avg_cov = np.mean([d["coverage_pct"] for d in coverage_details]) if coverage_details else 0
            status = "pass" if avg_cov > 90 else ("warn" if avg_cov > 50 else "fail")
            checks.append({"id": "V1", "name": "activity BUY vs closed totalBought",
                           "status": status,
                           "detail": f"平均覆盖率 {avg_cov:.1f}%", "items": coverage_details})
        else:
            checks.append({"id": "V1", "name": "activity BUY vs closed totalBought",
                           "status": "unknown", "detail": "无 raw activity 数据"})

        # ── V2: 时间范围核对（48h 安全余量） ──
        if act is not None and not act.empty:
            act_copy = act.copy()
            act_copy["timestamp"] = pd.to_numeric(act_copy.get("timestamp"), errors="coerce")
            time_issues = 0
            issue_details: list[dict] = []
            total_checked = len(self._closed)
            margin_seconds = 48 * 3600  # 48h 安全余量

            for r in self._closed:
                mask = act_copy["conditionId"] == r.condition_id
                ts = act_copy.loc[mask, "timestamp"].dropna()
                if ts.empty:
                    continue  # 无 activity 不算时间异常，V1 已覆盖
                if r.end_date:
                    try:
                        end_ts = pd.Timestamp(r.end_date).timestamp()
                        earliest = float(ts.min())
                        if earliest > end_ts + margin_seconds:
                            time_issues += 1
                            gap_hours = round((earliest - end_ts) / 3600, 1)
                            issue_details.append({
                                "title": r.title[:50],
                                "gap_hours": gap_hours,
                                "end_date": r.end_date,
                            })
                    except Exception:
                        pass

            issue_details.sort(key=lambda x: x["gap_hours"], reverse=True)
            ratio = time_issues / total_checked if total_checked > 0 else 0
            status = "pass" if ratio < 0.05 else ("warn" if ratio < 0.10 else "fail")
            checks.append({
                "id": "V2", "name": "时间范围核对",
                "status": status,
                "detail": f"{time_issues}/{total_checked} 个头寸时间异常 ({ratio:.1%})",
                "top_issues": issue_details[:5],
            })
        else:
            checks.append({"id": "V2", "name": "时间范围核对",
                           "status": "unknown", "detail": "无 raw activity 数据"})

        # ── V3: 原始 activity side 分布 ──
        if act is not None and not act.empty:
            type_side = {}
            trades = act[act.get("type") == "TRADE"] if "type" in act.columns else pd.DataFrame()
            if "side" in trades.columns and not trades.empty:
                type_side = trades["side"].value_counts().to_dict()
            sell_count = type_side.get("SELL", 0)
            buy_count = type_side.get("BUY", 0)
            status = "pass" if sell_count == 0 else "warn"
            checks.append({"id": "V3", "name": "原始 activity side 分布",
                           "status": status,
                           "detail": f"BUY={buy_count}, SELL={sell_count}",
                           "note": "在已解析 activity 中未发现主动卖出" if sell_count == 0
                                   else f"发现 {sell_count} 笔 SELL 交易"})
        else:
            checks.append({"id": "V3", "name": "原始 activity side 分布",
                           "status": "unknown", "detail": "无 raw activity 数据"})

        # ── V4: event 聚合 vs outcome 级 summary 对比 ──
        events = self.events
        outcome_wins = sum(1 for r in self._closed if r.win_loss == "Win")
        outcome_total = len(self._closed)
        event_wins = sum(1 for e in events if e["event_win_flag"])
        event_total = len(events)
        checks.append({"id": "V4", "name": "event vs outcome 口径对比",
                       "status": "warn" if outcome_total != event_total else "pass",
                       "detail": (f"outcome: {outcome_wins}/{outcome_total} "
                                  f"({outcome_wins/outcome_total*100:.1f}%) | "
                                  f"event: {event_wins}/{event_total} "
                                  f"({event_wins/event_total*100:.1f}%)")})

        # ── V5: 大仓 vs 小仓分桶 ──
        behavior = self.analyze_behavior()
        sizing = behavior.get("position_sizing_analysis", {})
        top = sizing.get("top20pct", {})
        bot = sizing.get("bottom20pct", {})
        if top and bot:
            checks.append({"id": "V5", "name": "大仓 vs 小仓分桶",
                           "status": "pass",
                           "detail": (f"top20%: ROI={top['avg_roi']}%, WR={top['win_rate_pct']}% | "
                                      f"bottom20%: ROI={bot['avg_roi']}%, WR={bot['win_rate_pct']}%")})
        else:
            checks.append({"id": "V5", "name": "大仓 vs 小仓分桶",
                           "status": "unknown", "detail": "数据不足"})

        # ── V6: 加权 vs 简单均值对比 ──
        w_stats = behavior.get("weighted_roi_stats", {})
        w_roi = w_stats.get("weighted_mean_roi", 0)
        s_roi = w_stats.get("simple_mean_roi", 0)
        diff = abs(w_roi - s_roi)
        status = "pass" if diff < 10 else ("warn" if diff < 30 else "fail")
        checks.append({"id": "V6", "name": "加权 vs 简单均值 ROI",
                       "status": status,
                       "detail": f"加权={w_roi}%, 简单={s_roi}%, 差异={diff:.1f}pp"})

        # ── V7: BUY-only 结论复核 ──
        total_sell_in_reports = sum(r.sell_count for r in self._closed)
        status = "pass" if total_sell_in_reports == 0 else "warn"
        checks.append({"id": "V7", "name": "BUY-only 结论复核",
                       "status": status,
                       "detail": f"MarketReport 中 sell_count 总计: {total_sell_in_reports}",
                       "note": ("退出主要依赖结算/赎回，未发现主动二级市场卖出"
                                if total_sell_in_reports == 0
                                else f"发现 {total_sell_in_reports} 笔卖出记录")})

        # ── V8: 字段语义假设审计 (assumption audit) ──
        checks.append({"id": "V8", "name": "字段语义假设审计",
                       "status": "info",
                       "field_assumptions": [
                           {"field": "totalBought", "assumption": "gross cost basis, fees not deducted",
                            "status": "unverified", "risk": "medium"},
                           {"field": "realizedPnl", "assumption": "net realized PnL after settlement",
                            "status": "partially_verified", "risk": "low"},
                           {"field": "curPrice", "assumption": "settlement price (0 or 1)",
                            "status": "verified_by_data", "risk": "low"},
                           {"field": "avgPrice", "assumption": "volume-weighted average entry price",
                            "status": "unverified", "risk": "medium"},
                       ]})

        return checks

    # ── 6. 跟单推荐指数（event 级六维评分） ────────────────

    def calculate_score(self) -> dict:
        """
        基于 event 级数据的八维评分 (0-100)。
        维度：胜率(20) + ROI稳定性(15) + Entry Edge(20) + 样本量(15) + 分散度(10) + 盈亏比(10) + 滑点惩罚 + 持仓时间惩罚
        """
        if not self._closed:
            return {"total": 0, "grade": "D", "breakdown": {},
                    "risk_warnings": ["无已结算市场数据"]}

        events = self.events
        closed = self._closed
        categories = set(r.category for r in closed)

        # ── 胜率 (20 分): event 级 Bayesian 胜率 ──
        event_wins = sum(1 for e in events if e["event_win_flag"])
        event_total = len(events)
        bayesian_wr = (event_wins + 1) / (event_total + 2)
        score_wr = min(bayesian_wr / 0.8, 1.0) * 20

        # ── ROI 稳定性 (15 分): 归一化 MAD ──
        event_rois = np.array([e["event_roi"] for e in events])
        event_invs = np.array([e["event_total_bought"] for e in events])
        if event_invs.sum() > 0:
            w_mean = float(np.average(event_rois, weights=event_invs))
            w_mad = float(np.average(np.abs(event_rois - w_mean), weights=event_invs))
            median_roi = float(np.median(event_rois))
            # MAD 越小越稳定。MAD < 10% 满分，MAD > 50% 零分
            score_stability = max(0, min(1, (50 - w_mad) / 40)) * 15
        else:
            w_mad = 0
            median_roi = 0
            score_stability = 0

        # ── Entry Edge (20 分): event 级加权 entry_edge ──
        w_edges = np.array([e["weighted_entry_edge"] for e in events])
        if event_invs.sum() > 0:
            avg_edge = float(np.average(w_edges, weights=event_invs))
            # edge 范围 [-1, 1], 0.5 以上很强
            score_edge = max(0, min(avg_edge / 0.5, 1.0)) * 20
        else:
            score_edge = 0

        # ── 样本量 (15 分): 三因子 ──
        all_first = [r.first_trade for r in closed if r.first_trade is not None]
        all_last = [r.last_trade for r in closed if r.last_trade is not None]
        active_days = (max(all_last) - min(all_first)).days if all_first and all_last else 0
        cat_count = len(categories)

        f_event = min(event_total / 15, 1.0) * 0.5
        f_days = min(active_days / 90, 1.0) * 0.3
        f_cats = min(cat_count / 3, 1.0) * 0.2
        score_sample = (f_event + f_days + f_cats) * 15

        # ── 分散度 (10 分) ──
        score_div = min(cat_count / 5, 1.0) * 10

        # ── 盈亏比 (10 分): profit_factor ──
        win_pnl = sum(r.realized_pnl for r in closed if r.realized_pnl > 0)
        loss_pnl = abs(sum(r.realized_pnl for r in closed if r.realized_pnl < 0))
        profit_factor = win_pnl / loss_pnl if loss_pnl > 0 else (10.0 if win_pnl > 0 else 0)
        # PF >= 3.0 满分，PF <= 1.0 零分
        score_pf = max(0, min(1, (profit_factor - 1.0) / 2.0)) * 10

        # ── 滑点惩罚 ──
        total_invested = sum(r.total_invested for r in closed)
        slippage = -10 if total_invested > 1_000_000 else (-5 if total_invested > 100_000 else 0)

        # ── 持仓时间惩罚 ──
        # 做市商/高频地址不适合跟单，直接大幅扣分
        behavior = self.analyze_behavior()
        holding_risk = behavior.get("holding_risk", {})
        hr_severity = holding_risk.get("severity", "low")
        if hr_severity == "critical":
            holding_penalty = -30  # 做市商嫌疑，直接扣 30 分
        elif hr_severity == "high":
            holding_penalty = -20  # 快进快出，扣 20 分
        elif hr_severity == "medium":
            holding_penalty = -10  # 短线交易者，扣 10 分
        else:
            holding_penalty = 0

        total = round(score_wr + score_stability + score_edge + score_sample + score_div + score_pf + slippage + holding_penalty, 1)
        total = max(0, min(100, total))

        grade = "S" if total >= 85 else "A" if total >= 70 else "B" if total >= 55 else "C" if total >= 40 else "D"

        # 风险提示
        warnings = self._generate_warnings(events, closed, categories, active_days, total_invested)

        return {
            "total": total,
            "grade": grade,
            "breakdown": {
                "win_rate": round(score_wr, 1),
                "roi_stability": round(score_stability, 1),
                "entry_edge": round(score_edge, 1),
                "sample_size": round(score_sample, 1),
                "diversification": round(score_div, 1),
                "profit_factor": round(score_pf, 1),
                "slippage_penalty": slippage,
                "holding_time_penalty": holding_penalty,
            },
            "scoring_inputs": {
                "bayesian_event_win_rate": round(bayesian_wr, 4),
                "raw_event_win_rate": round(event_wins / event_total, 4) if event_total > 0 else 0,
                "event_count": event_total,
                "active_days": active_days,
                "category_count": cat_count,
                "weighted_avg_entry_edge": round(avg_edge, 4) if event_invs.sum() > 0 else 0,
                "weighted_mad_roi": round(w_mad, 2) if event_invs.sum() > 0 else 0,
                "profit_factor": round(profit_factor, 2),
                "holding_risk_label": holding_risk.get("label", "unknown"),
                "holding_risk_severity": hr_severity,
                "median_holding_hours": holding_risk.get("median_hours", 0),
            },
            "risk_warnings": warnings,
        }

    def _generate_warnings(self, events, closed, categories, active_days, total_invested) -> list[str]:
        warnings = []

        # ── 高频预检警告（最最高优先级） ──
        fc = self._freq_check
        if fc and fc.get("is_high_freq"):
            tph = fc.get("trades_per_hour", 0)
            span = fc.get("sample_time_span_hours", 0)
            warnings.append(
                f"🚨 高频地址预检命中：{tph} 笔/小时 "
                f"(100 笔 TRADE 仅覆盖 {span:.1f}h)，"
                f"疑似做市商/机器人，不适合跟单"
            )

        # ── 持仓时间风险（最高优先级） ──
        behavior = self.analyze_behavior()
        holding_risk = behavior.get("holding_risk", {})
        hr_severity = holding_risk.get("severity", "low")
        if hr_severity in ("critical", "high"):
            warnings.insert(0, f"🚨 {holding_risk['verdict']}")
            for sig in holding_risk.get("signals", []):
                warnings.append(f"  ↳ [{sig['id']}] {sig['name']}: {sig['detail']}")

        # 分类集中度
        cats_pnl = defaultdict(float)
        for r in closed:
            cats_pnl[r.category] += r.realized_pnl
        total_pnl = sum(cats_pnl.values())
        if total_pnl > 0:
            top_cat = max(cats_pnl, key=cats_pnl.get)
            top_share = cats_pnl[top_cat] / total_pnl * 100
            if top_share > 80:
                warnings.append(f"高度集中于 {top_cat}（贡献 {top_share:.0f}% PnL），分散度不足")

        if total_invested > 1_000_000:
            warnings.append(f"跟单需大额资金 (${total_invested/1e6:.1f}M)，滑点风险高")

        if active_days < 60:
            warnings.append(f"活跃周期仅 {active_days} 天，可能是事件驱动型而非持续盈利")

        if len(events) < 10:
            warnings.append(f"仅 {len(events)} 个独立事件，样本量不足以判断系统性能力")

        # 大仓判断力弱于小仓（复用上面已获取的 behavior）
        sizing = behavior.get("position_sizing_analysis", {})
        top = sizing.get("top20pct", {})
        bot = sizing.get("bottom20pct", {})
        if top and bot:
            top_wr = top.get("win_rate_pct", 0)
            bot_wr = bot.get("win_rate_pct", 0)
            if bot_wr > top_wr + 5:
                warnings.append(
                    f"大仓胜率 ({top_wr}%) 低于小仓 ({bot_wr}%)，跟单大额交易风险更高"
                )

        # 信心加权分析警告
        conv = self.analyze_conviction()
        if conv.get("status") == "ok":
            grade = conv.get("conviction_grade", "unknown")
            if grade == "weak":
                spread = conv.get("conviction_spread_pp", 0)
                warnings.append(
                    f"重仓胜率低于轻仓 ({spread:+.1f}pp)，仓位管理能力差，跟单大额交易风险极高"
                )
            hlr = conv.get("heavy_loss_rate_pct")
            if hlr is not None and hlr > 30:
                warnings.append(
                    f"重仓亏损率 {hlr:.0f}%，该地址在高信心时判断力不可靠"
                )

        return warnings

    # ── 7. 报告生成 ───────────────────────────────────────

    def generate_report(self) -> dict:
        """生成完整 JSON 报告（双口径：outcome 级 + event 级）。"""
        closed = self._closed
        events = self.events

        # outcome 级 summary
        total_pnl = sum(r.realized_pnl for r in closed)
        total_invested = sum(r.total_invested for r in closed)
        wins = sum(1 for r in closed if r.win_loss == "Win")
        losses = sum(1 for r in closed if r.win_loss == "Loss")

        all_first = [r.first_trade for r in closed if r.first_trade is not None]
        all_last = [r.last_trade for r in closed if r.last_trade is not None]
        active_start = min(all_first).strftime("%Y-%m-%d") if all_first else ""
        active_end = max(all_last).strftime("%Y-%m-%d") if all_last else ""
        active_days = (max(all_last) - min(all_first)).days if all_first and all_last else 0

        # event 级 summary
        event_wins = sum(1 for e in events if e["event_win_flag"])
        event_losses = len(events) - event_wins
        raw_event_wr = event_wins / len(events) if events else 0
        bayesian_event_wr = (event_wins + 1) / (len(events) + 2) if events else 0

        report = {
            "address": self._address,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "outcome_level": {
                    "total_pnl": round(total_pnl, 2),
                    "total_invested": round(total_invested, 2),
                    "roi_pct": round(total_pnl / total_invested * 100, 1) if total_invested > 0 else 0,
                    "roi_note": "已结算头寸的累计成本回报率，非账户净值回报",
                    "win_rate_pct": round(wins / len(closed) * 100, 1) if closed else 0,
                    "markets_closed": len(closed),
                    "markets_open": len(self._open),
                    "wins": wins,
                    "losses": losses,
                },
                "event_level": {
                    "event_count": len(events),
                    "event_wins": event_wins,
                    "event_losses": event_losses,
                    "raw_event_win_rate": round(raw_event_wr, 4),
                    "bayesian_event_win_rate": round(bayesian_event_wr, 4),
                    "event_total_pnl": round(sum(e["event_pnl"] for e in events), 2),
                    "event_total_invested": round(sum(e["event_total_bought"] for e in events), 2),
                    "event_roi_pct": round(
                        sum(e["event_pnl"] for e in events) /
                        max(sum(e["event_total_bought"] for e in events), 1) * 100, 1),
                },
                "active_period": f"{active_start} ~ {active_end}",
                "active_days": active_days,
            },
            "entry_timing": self.analyze_entry_timing(),
            "category_breakdown": self.analyze_categories(),
            "pressure_test": self.analyze_pressure(),
            "behavior": self.analyze_behavior(),
            "conviction_analysis": self.analyze_conviction(),
            "events": [{k: v for k, v in e.items() if k != "outcomes"} for e in events],
            "copy_trading_score": self.calculate_score(),
            "validation": self.validate(),
        }

        # 高频预检信息
        if self._freq_check and self._freq_check.get("is_high_freq"):
            report["high_frequency_prescreen"] = {
                "is_high_freq": True,
                "trades_per_hour": self._freq_check.get("trades_per_hour", 0),
                "sample_time_span_hours": self._freq_check.get("sample_time_span_hours", 0),
                "sample_newest": self._freq_check.get("sample_newest", ""),
                "sample_oldest": self._freq_check.get("sample_oldest", ""),
                "trade_count_in_sample": self._freq_check.get("trade_count_in_sample", 0),
                "total_activity_in_page": self._freq_check.get("total_activity_in_page", 0),
                "verdict": (
                    "该地址为高频交易地址（做市商/机器人），"
                    "已跳过全量 activity 拉取，仅基于 closed-positions 分析。"
                    "不适合跟单。"
                ),
            }

        logger.info(
            f"报告生成 | PnL=${total_pnl:+,.2f} | "
            f"评分={report['copy_trading_score']['total']} ({report['copy_trading_score']['grade']}) | "
            f"event={len(events)}, outcome={len(closed)}"
        )
        return report

    def save_report(self, output_dir: str = "data") -> Path:
        report = self.generate_report()
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        short = self._address[:10] if self._address else "unknown"
        path = out / f"{short}_report.json"

        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)

        logger.info(f"报告已保存 | {path}")
        return path
