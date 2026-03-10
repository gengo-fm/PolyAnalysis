"""
TradeProcessor — 数据处理引擎 v4

核心逻辑：
- 以 closed-positions 为主表（权威 PnL 来源）
- 以 (conditionId, outcome) 为联合主键对齐 activity 行为数据
- activity 仅用于行为分析（时间、频率、价格区间），不用于金额计算

输入：fetcher.fetch_all() 返回的 DataFrame 或 Parquet 文件
输出：MarketReport 列表 + 汇总 DataFrame
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import numpy as np
from loguru import logger
from dataclasses import dataclass, field


# ── 分类映射 ──────────────────────────────────────────────
# 注意：_classify() 是 first-match，更具体的分类必须放在前面
CATEGORY_KEYWORDS = {
    "Weather": [
        "temperature", "weather", "rain", "snow", "wind", "hurricane",
        "storm", "celsius", "fahrenheit",
    ],
    "Social_Media": [
        "tweet", "tweets", "post", "retweet", "x-post",
        "subscriber", "follower", "tiktok", "youtube",
    ],
    "Politics": [
        "president", "election", "trump", "biden", "republican",
        "democrat", "senate", "congress", "governor", "political",
        "vote", "gop", "primary", "inaugur",
    ],
    "Crypto": [
        "bitcoin", "btc", "ethereum", "eth", "crypto", "token",
        "defi", "nft", "solana", "sol", "blockchain",
    ],
    "Sports": [
        "nba", "nfl", "mlb", "nhl", "soccer", "football",
        "basketball", "baseball", "tennis", "ufc", "boxing",
        "championship", "super-bowl", "world-cup",
    ],
    "Entertainment": [
        "oscar", "grammy", "emmy", "movie", "film", "music",
        "celebrity", "james-bond", "tv-show", "netflix",
    ],
    "Finance": [
        "fed", "interest-rate", "inflation", "gdp", "stock",
        "sp500", "nasdaq", "recession", "unemployment",
    ],
}


@dataclass
class MarketReport:
    """单个 (conditionId, outcome) 头寸的完整报告。"""

    # ── 标识 ──────────────────────────────────────────────
    condition_id: str
    outcome: str
    title: str
    category: str
    event_slug: str

    # ── 权威金额（来自 closed-positions） ─────────────────
    total_invested: float = 0.0      # totalBought
    realized_pnl: float = 0.0       # realizedPnl
    avg_entry_price: float = 0.0    # avgPrice
    settlement_price: float = 0.0   # curPrice (1=赢, 0=输)
    roi: float = 0.0                # realizedPnl / totalBought * 100

    # ── 状态 ──────────────────────────────────────────────
    status: str = "Open"            # Closed / Open
    win_loss: str = "Open"          # Win / Loss / Breakeven / Open

    # ── 行为数据（来自 activity） ─────────────────────────
    trade_count: int = 0            # TRADE 笔数
    buy_count: int = 0
    sell_count: int = 0
    first_trade: pd.Timestamp | None = None
    last_trade: pd.Timestamp | None = None
    price_min: float = 0.0          # 入场最低价
    price_max: float = 0.0          # 入场最高价
    redeem_time: pd.Timestamp | None = None   # REDEEM 时间（资金释放点）
    redeem_usdc: float = 0.0
    merge_usdc: float = 0.0

    # ── 衍生指标 ──────────────────────────────────────────
    holding_hours: float = 0.0
    entry_edge: float = 0.0         # settlement_price - avg_entry_price, 范围 [-1, 1]
    alpha_timing_legacy: float = 0.0  # deprecated: 旧版 alpha_timing，保留兼容
    consensus_deviation: float = 0.0
    wallet_entry_timing_pct: float = 0.5  # 钱包在该事件上的入场时间位置 [0,1]

    # ── 市场到期时间（来自 closed-positions） ─────────────
    end_date: str = ""


def _classify(slug: str) -> str:
    """基于 eventSlug 关键词匹配分类。"""
    if not isinstance(slug, str):
        return "Other"
    s = slug.lower()
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(k in s for k in kws):
            return cat
    return "Other"


class TradeProcessor:
    """交易数据处理引擎。"""

    def __init__(
        self,
        activity_df: pd.DataFrame,
        closed_positions_df: pd.DataFrame,
    ):
        self._activity_raw = activity_df.copy()
        self._closed_raw = closed_positions_df.copy() if not closed_positions_df.empty else pd.DataFrame()
        self._activity: pd.DataFrame | None = None
        self._reports: list[MarketReport] | None = None
        self._pnl_df: pd.DataFrame | None = None

    # ── 从 Parquet 加载 ──────────────────────────────────

    @classmethod
    def from_parquet(cls, address: str, data_dir: str = "data") -> TradeProcessor:
        """从 Parquet 文件构造 TradeProcessor。"""
        out = Path(data_dir)
        short = address[:10]

        activity_path = out / f"{short}_activity.parquet"
        closed_path = out / f"{short}_closed_positions.parquet"

        activity = pd.read_parquet(activity_path) if activity_path.exists() else pd.DataFrame()
        closed = pd.read_parquet(closed_path) if closed_path.exists() else pd.DataFrame()

        logger.info(f"Parquet 加载 | activity={len(activity)}, closed={len(closed)}")
        return cls(activity, closed)

    # ── 1. 清洗 activity ─────────────────────────────────

    def clean(self) -> pd.DataFrame:
        """清洗 activity 数据：类型转换、时间戳、分类。"""
        df = self._activity_raw.copy()
        if df.empty:
            self._activity = df
            return df

        logger.info(f"清洗 activity | 原始 {len(df)} 行")

        for col in ["size", "usdcSize", "price", "timestamp"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

        if "timestamp" in df.columns:
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)

        if "eventSlug" in df.columns:
            df["category"] = df["eventSlug"].apply(_classify)

        df = df.sort_values("timestamp").reset_index(drop=True)

        type_counts = df["type"].value_counts().to_dict() if "type" in df.columns else {}
        logger.info(f"清洗完成 | {len(df)} 行, 类型 {type_counts}")
        self._activity = df
        return df

    # ── 2. 构建报告（以 closed-positions 为主表） ────────

    def build_reports(self) -> list[MarketReport]:
        """
        以 closed-positions 为主表，关联 activity 行为数据。

        步骤：
        1. 遍历 closed_positions，以 (conditionId, outcome) 建立基础账本
        2. 关联 activity 中的行为数据
        3. 处理 activity 中有但 closed 中没有的头寸（标记为 Open）
        """
        if self._activity is None:
            self.clean()
        act = self._activity

        # 按 (conditionId, outcome) 索引 activity
        act_index: dict[tuple[str, str], pd.DataFrame] = {}
        if not act.empty and "conditionId" in act.columns and "outcome" in act.columns:
            for (cid, outcome), grp in act.groupby(["conditionId", "outcome"]):
                act_index[(cid, outcome)] = grp

        # 按 conditionId 索引 activity（用于 REDEEM，它的 outcome 为空）
        act_by_cid: dict[str, pd.DataFrame] = {}
        if not act.empty and "conditionId" in act.columns:
            for cid, grp in act.groupby("conditionId"):
                act_by_cid[cid] = grp

        reports: list[MarketReport] = []
        seen_keys: set[tuple[str, str]] = set()

        # ── 阶段 1：从 closed-positions 建立基础账本 ─────
        if not self._closed_raw.empty:
            for _, row in self._closed_raw.iterrows():
                cid = row["conditionId"]
                outcome = row["outcome"]
                key = (cid, outcome)
                seen_keys.add(key)

                rpt = self._build_from_closed(row, act_index.get(key), act_by_cid.get(cid))
                reports.append(rpt)

        # ── 阶段 2：activity 中有但 closed 中没有的头寸 ──
        for key, grp in act_index.items():
            if key in seen_keys:
                continue
            # 只处理有 TRADE 记录的
            trades = grp[grp["type"] == "TRADE"] if "type" in grp.columns else grp
            if trades.empty:
                continue
            rpt = self._build_open(key[0], key[1], grp)
            reports.append(rpt)

        reports.sort(key=lambda r: r.total_invested, reverse=True)
        self._reports = reports

        # ── 阶段 3：计算 wallet_entry_timing_pct（需要 event 级上下文）──
        self._compute_wallet_entry_timing(reports)

        closed_count = sum(1 for r in reports if r.status == "Closed")
        open_count = sum(1 for r in reports if r.status == "Open")
        total_pnl = sum(r.realized_pnl for r in reports)
        wins = sum(1 for r in reports if r.win_loss == "Win")
        losses = sum(1 for r in reports if r.win_loss == "Loss")

        logger.info(
            f"报告生成 | {len(reports)} 个头寸 "
            f"(已结算 {closed_count}, 未结算 {open_count}) | "
            f"PnL=${total_pnl:+,.2f} | 胜{wins}/负{losses}"
        )
        return reports

    @staticmethod
    def _compute_wallet_entry_timing(reports: list[MarketReport]):
        """
        计算 wallet_entry_timing_pct：钱包在该事件上的入场时间位置。

        wallet_event_start = 该事件下所有 outcome 的最早 first_trade
        wallet_event_end = 该事件下最晚的 redeem_time 或 endDate
        pct = (first_trade - wallet_event_start) / (wallet_event_end - wallet_event_start)
        """
        from collections import defaultdict

        event_groups: dict[str, list[MarketReport]] = defaultdict(list)
        for r in reports:
            slug = r.event_slug or f"_orphan_{r.condition_id}"
            event_groups[slug].append(r)

        for slug, group in event_groups.items():
            # wallet_event_start
            first_trades = [r.first_trade for r in group if r.first_trade is not None]
            if not first_trades:
                continue
            event_start = min(first_trades)

            # wallet_event_end: 优先 redeem_time, 兜底 endDate
            end_candidates = []
            for r in group:
                if r.redeem_time is not None:
                    end_candidates.append(r.redeem_time)
                elif r.end_date:
                    try:
                        end_candidates.append(pd.Timestamp(r.end_date))
                    except Exception:
                        pass
            if not end_candidates:
                continue
            event_end = max(end_candidates)

            span = (event_end - event_start).total_seconds()
            if span <= 0:
                for r in group:
                    r.wallet_entry_timing_pct = 0.5
                continue

            for r in group:
                if r.first_trade is not None:
                    offset = (r.first_trade - event_start).total_seconds()
                    r.wallet_entry_timing_pct = round(min(max(offset / span, 0), 1), 4)
                else:
                    r.wallet_entry_timing_pct = 0.5

    def _build_from_closed(
        self,
        closed_row: pd.Series,
        act_group: pd.DataFrame | None,
        act_cid_group: pd.DataFrame | None,
    ) -> MarketReport:
        """从 closed-positions 行 + activity 行为数据构建报告。"""
        cid = closed_row["conditionId"]
        outcome = closed_row["outcome"]
        title = closed_row.get("title", "")
        event_slug = closed_row.get("eventSlug", "")
        category = _classify(event_slug)

        # 权威金额
        total_invested = float(closed_row.get("totalBought", 0))
        realized_pnl = float(closed_row.get("realizedPnl", 0))
        avg_entry = float(closed_row.get("avgPrice", 0))
        settle = float(closed_row.get("curPrice", 0))
        end_date = str(closed_row.get("endDate", ""))
        roi = (realized_pnl / total_invested * 100) if total_invested > 0 else 0.0

        # 状态
        if realized_pnl > 0:
            win_loss = "Win"
        elif realized_pnl < 0:
            win_loss = "Loss"
        else:
            win_loss = "Breakeven"

        # 行为数据
        trade_count = buy_count = sell_count = 0
        first_trade = last_trade = None
        price_min = price_max = 0.0
        redeem_time = None
        redeem_usdc = 0.0
        merge_usdc = 0.0

        if act_group is not None and not act_group.empty:
            trades = act_group[act_group["type"] == "TRADE"] if "type" in act_group.columns else act_group
            if not trades.empty:
                trade_count = len(trades)
                buy_count = (trades["side"] == "BUY").sum() if "side" in trades.columns else 0
                sell_count = (trades["side"] == "SELL").sum() if "side" in trades.columns else 0
                first_trade = trades["datetime"].min() if "datetime" in trades.columns else None
                last_trade = trades["datetime"].max() if "datetime" in trades.columns else None
                price_min = float(trades["price"].min())
                price_max = float(trades["price"].max())

        # REDEEM 时间（从 conditionId 级别的 activity 中找）
        if act_cid_group is not None and not act_cid_group.empty:
            redeems = act_cid_group[act_cid_group["type"] == "REDEEM"] if "type" in act_cid_group.columns else pd.DataFrame()
            if not redeems.empty:
                redeem_time = redeems["datetime"].max() if "datetime" in redeems.columns else None
                redeem_usdc = float(redeems["usdcSize"].sum()) if "usdcSize" in redeems.columns else 0.0

            merges = act_cid_group[act_cid_group["type"] == "MERGE"] if "type" in act_cid_group.columns else pd.DataFrame()
            if not merges.empty:
                merge_usdc = float(merges["usdcSize"].sum()) if "usdcSize" in merges.columns else 0.0

        # 持仓时长
        holding_hours = 0.0
        if first_trade is not None and redeem_time is not None:
            holding_hours = (redeem_time - first_trade).total_seconds() / 3600
        elif first_trade is not None and last_trade is not None:
            holding_hours = (last_trade - first_trade).total_seconds() / 3600

        # Entry Edge: settlement_price - avg_entry_price (统一定义, [-1, 1])
        entry_edge = settle - avg_entry

        # Alpha Timing Legacy (deprecated, 保留兼容)
        alpha_timing_legacy = 0.0
        if settle >= 0.95 and avg_entry > 0:
            alpha_timing_legacy = avg_entry
        elif settle <= 0.05 and avg_entry > 0:
            alpha_timing_legacy = avg_entry

        # 共识偏离度
        if win_loss == "Win":
            consensus_deviation = 1.0 - avg_entry
        elif win_loss == "Loss":
            consensus_deviation = -(1.0 - avg_entry) * 0.5
        else:
            consensus_deviation = 0.0

        return MarketReport(
            condition_id=cid,
            outcome=outcome,
            title=title,
            category=category,
            event_slug=event_slug,
            total_invested=round(total_invested, 2),
            realized_pnl=round(realized_pnl, 2),
            avg_entry_price=round(avg_entry, 6),
            settlement_price=settle,
            roi=round(roi, 2),
            status="Closed",
            win_loss=win_loss,
            trade_count=trade_count,
            buy_count=buy_count,
            sell_count=sell_count,
            first_trade=first_trade,
            last_trade=last_trade,
            price_min=round(price_min, 6),
            price_max=round(price_max, 6),
            redeem_time=redeem_time,
            redeem_usdc=round(redeem_usdc, 2),
            merge_usdc=round(merge_usdc, 2),
            holding_hours=round(holding_hours, 2),
            entry_edge=round(entry_edge, 6),
            alpha_timing_legacy=round(alpha_timing_legacy, 6),
            consensus_deviation=round(consensus_deviation, 4),
            end_date=end_date,
        )

    def _build_open(
        self, cid: str, outcome: str, act_group: pd.DataFrame
    ) -> MarketReport:
        """从 activity 构建未结算头寸报告（无权威金额）。"""
        title = act_group["title"].iloc[0] if "title" in act_group.columns else ""
        event_slug = act_group["eventSlug"].iloc[0] if "eventSlug" in act_group.columns else ""
        category = _classify(event_slug)

        trades = act_group[act_group["type"] == "TRADE"] if "type" in act_group.columns else act_group
        trade_count = len(trades)
        buy_count = (trades["side"] == "BUY").sum() if "side" in trades.columns else 0
        sell_count = (trades["side"] == "SELL").sum() if "side" in trades.columns else 0

        first_trade = trades["datetime"].min() if "datetime" in trades.columns and not trades.empty else None
        last_trade = trades["datetime"].max() if "datetime" in trades.columns and not trades.empty else None
        price_min = float(trades["price"].min()) if not trades.empty else 0.0
        price_max = float(trades["price"].max()) if not trades.empty else 0.0

        holding_hours = 0.0
        if first_trade is not None and last_trade is not None:
            holding_hours = (last_trade - first_trade).total_seconds() / 3600

        return MarketReport(
            condition_id=cid,
            outcome=outcome,
            title=title,
            category=category,
            event_slug=event_slug,
            status="Open",
            win_loss="Open",
            trade_count=trade_count,
            buy_count=buy_count,
            sell_count=sell_count,
            first_trade=first_trade,
            last_trade=last_trade,
            price_min=round(price_min, 6),
            price_max=round(price_max, 6),
            holding_hours=round(holding_hours, 2),
        )

    # ── 3. 转为 DataFrame ────────────────────────────────

    def to_dataframe(self) -> pd.DataFrame:
        """将报告列表转为 DataFrame。"""
        if self._reports is None:
            self.build_reports()
        rows = [r.__dict__ for r in self._reports]
        df = pd.DataFrame(rows)
        self._pnl_df = df
        return df

    # ── 属性 ──────────────────────────────────────────────

    @property
    def reports(self) -> list[MarketReport]:
        if self._reports is None:
            self.build_reports()
        return self._reports

    @property
    def pnl_df(self) -> pd.DataFrame:
        if self._pnl_df is None:
            self.to_dataframe()
        return self._pnl_df
