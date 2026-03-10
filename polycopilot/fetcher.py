"""
PolymarketFetcher — 异步数据采集模块 v3

核心能力：
- 时间锚点分页：突破 offset=4000 上限，通过 `end` 参数递归拉取全量数据
- 限流保护：每 5 次请求自动 sleep，防止 API 封禁
- 并发市场元数据获取
- Parquet 导出：按地址命名，支持快速加载
"""

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
from loguru import logger
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

# ── API 端点 ──────────────────────────────────────────────
DATA_API_BASE = "https://data-api.polymarket.com"
GAMMA_API_BASE = "https://gamma-api.polymarket.com"

PAGE_LIMIT = 1000       # 每页上限
OFFSET_CEILING = 4000   # API offset 硬限制
RATE_LIMIT_EVERY = 5    # 每 N 次请求后 sleep
RATE_LIMIT_SLEEP = 1.0  # sleep 秒数


def _ts_to_str(ts: int | float) -> str:
    """Unix 时间戳 → 可读字符串。"""
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


class PolymarketFetcher:
    """异步 Polymarket 数据采集客户端。"""

    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._req_count = 0  # 请求计数器（限流用）

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=self._timeout)
        self._req_count = 0
        return self

    async def __aexit__(self, *exc):
        if self._client:
            await self._client.aclose()

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("请在 async with PolymarketFetcher() 上下文中使用")
        return self._client

    # ── 限流 ──────────────────────────────────────────────

    async def _rate_limit(self):
        """每 N 次请求后暂停，防止被封。"""
        self._req_count += 1
        if self._req_count % RATE_LIMIT_EVERY == 0:
            logger.debug(f"限流暂停 | 已请求 {self._req_count} 次, sleep {RATE_LIMIT_SLEEP}s")
            await asyncio.sleep(RATE_LIMIT_SLEEP)

    # ── 通用请求 ──────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception_type((httpx.TransportError,)),
        before_sleep=lambda rs: logger.warning(
            f"请求重试 (第 {rs.attempt_number} 次): {rs.outcome.exception()}"
        ),
    )
    async def _get(self, url: str, params: dict | None = None) -> Any:
        await self._rate_limit()
        client = self._ensure_client()
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    # ── 核心：时间锚点分页拉取全量活动 ────────────────────

    async def get_all_activity(self, address: str) -> pd.DataFrame:
        """
        通过时间锚点分页获取地址的全部链上活动。

        策略：
        1. 从最新数据开始，用 offset 分页拉取（每轮最多 4000 条）
        2. 当 offset 达到上限时，取当前最老记录的 timestamp
        3. 用 `end=timestamp` 参数锚定时间窗口，offset 重置为 0
        4. 循环直到拉完所有数据
        """
        logger.info(f"开始全量活动拉取 | 地址: {address}")
        t0 = time.time()

        all_records: list[dict] = []
        end_anchor: int | None = None  # 时间锚点
        round_num = 0

        while True:
            round_num += 1
            round_records = await self._fetch_one_round(address, end_anchor, round_num)

            if not round_records:
                break

            all_records.extend(round_records)

            # 检查是否触达 offset 上限（需要时间锚点续拉）
            if len(round_records) >= OFFSET_CEILING:
                # 取本轮最老记录的 timestamp 作为下一轮锚点
                oldest_ts = min(int(r["timestamp"]) for r in round_records)
                # 去重：排除与锚点时间戳相同的记录（下一轮会重新拉到）
                end_anchor = oldest_ts
                logger.info(
                    f"触达 offset 上限 | 轮次 {round_num}, "
                    f"本轮 {len(round_records)} 条, "
                    f"新锚点: {_ts_to_str(oldest_ts)} (ts={oldest_ts})"
                )
            else:
                break

        # 去重（时间锚点边界可能有重复）
        if all_records:
            seen = set()
            unique = []
            for r in all_records:
                key = r.get("transactionHash", "") + str(r.get("timestamp", "")) + r.get("type", "")
                if key not in seen:
                    seen.add(key)
                    unique.append(r)
            dedup_count = len(all_records) - len(unique)
            if dedup_count > 0:
                logger.info(f"去重 | 移除 {dedup_count} 条重复记录")
            all_records = unique

        elapsed = time.time() - t0

        if not all_records:
            logger.warning(f"地址 {address} 无活动记录")
            return pd.DataFrame()

        df = pd.DataFrame(all_records)

        # 统计
        type_counts = df["type"].value_counts().to_dict()
        trade_sides = df.loc[df["type"] == "TRADE", "side"].value_counts().to_dict()
        ts_col = pd.to_numeric(df["timestamp"], errors="coerce")
        time_range = f"{_ts_to_str(ts_col.max())} → {_ts_to_str(ts_col.min())}"

        logger.info(
            f"全量拉取完成 | {len(df)} 条, {round_num} 轮, {elapsed:.1f}s | "
            f"类型: {type_counts} | TRADE: {trade_sides} | "
            f"时间: {time_range}"
        )
        return df

    async def _fetch_one_round(
        self, address: str, end_anchor: int | None, round_num: int
    ) -> list[dict]:
        """单轮 offset 分页拉取（最多 OFFSET_CEILING 条）。"""
        records: list[dict] = []
        offset = 0

        while True:
            params: dict[str, Any] = {
                "user": address, "limit": PAGE_LIMIT, "offset": offset
            }
            if end_anchor is not None:
                params["end"] = end_anchor

            try:
                data = await self._get(f"{DATA_API_BASE}/activity", params=params)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 400:
                    logger.debug(f"轮次 {round_num} offset={offset} 返回 400, 停止")
                    break
                raise

            batch = [d for d in data if isinstance(d, dict)]
            if not batch:
                break

            records.extend(batch)

            # 进度日志
            if batch:
                oldest = _ts_to_str(min(int(b["timestamp"]) for b in batch))
                newest = _ts_to_str(max(int(b["timestamp"]) for b in batch))
                logger.debug(
                    f"轮次 {round_num} | offset={offset} → {len(batch)} 条, "
                    f"累计 {len(records)} | 时间: {newest} → {oldest}"
                )

            if len(batch) < PAGE_LIMIT:
                break

            offset += PAGE_LIMIT
            if offset >= OFFSET_CEILING:
                logger.debug(f"轮次 {round_num} | offset 达到上限 {OFFSET_CEILING}")
                break

        return records

    # ── 已平仓头寸 ───────────────────────────────────────

    async def get_closed_positions(self, address: str) -> pd.DataFrame:
        """
        分页获取全部已平仓头寸（含 API 计算的 PnL）。

        API 限制：limit 最大 50，offset 最大 100,000。
        策略：每次拉 50 条，offset 递增，直到返回空数据。
        """
        logger.info(f"拉取已平仓 | 地址: {address}")
        page_limit = 50  # API 文档规定上限
        offset = 0
        all_records: list[dict] = []

        while True:
            data = await self._get(
                f"{DATA_API_BASE}/closed-positions",
                params={
                    "user": address,
                    "limit": page_limit,
                    "offset": offset,
                    "sortBy": "TIMESTAMP",
                    "sortDirection": "DESC",
                },
            )
            batch = [d for d in data if isinstance(d, dict)] if data else []
            if not batch:
                break

            all_records.extend(batch)
            logger.debug(
                f"closed-positions | offset={offset}, 本页 {len(batch)} 条, "
                f"累计 {len(all_records)}"
            )

            if len(batch) < page_limit:
                break  # 最后一页

            offset += page_limit
            if offset > 100_000:
                logger.warning("closed-positions offset 达到 100,000 上限，停止分页")
                break

        if not all_records:
            logger.warning(f"地址 {address} 无已平仓头寸")
            return pd.DataFrame()

        df = pd.DataFrame(all_records)
        logger.info(
            f"已平仓 {len(df)} 条 | "
            f"API 总 PnL: ${df['realizedPnl'].astype(float).sum():,.2f}"
        )
        return df

    # ── 当前持仓 ──────────────────────────────────────────

    async def get_positions(self, address: str) -> pd.DataFrame:
        """
        分页获取全部当前持仓。

        API 限制：limit 最大 500，offset 最大 10,000。
        """
        logger.info(f"拉取持仓 | 地址: {address}")
        page_limit = 500  # API 文档上限
        offset = 0
        all_records: list[dict] = []

        while True:
            data = await self._get(
                f"{DATA_API_BASE}/positions",
                params={"user": address, "limit": page_limit, "offset": offset},
            )
            batch = [d for d in data if isinstance(d, dict)] if data else []
            if not batch:
                break

            all_records.extend(batch)
            logger.debug(
                f"positions | offset={offset}, 本页 {len(batch)} 条, "
                f"累计 {len(all_records)}"
            )

            if len(batch) < page_limit:
                break
            offset += page_limit
            if offset > 10_000:
                logger.warning("positions offset 达到 10,000 上限，停止分页")
                break

        if not all_records:
            logger.warning(f"地址 {address} 无当前持仓")
            return pd.DataFrame()

        df = pd.DataFrame(all_records)
        logger.info(f"持仓 {len(df)} 条")
        return df

    # ── 批量市场元数据 ───────────────────────────────────

    async def get_market_details_bulk(
        self, condition_ids: list[str], concurrency: int = 5
    ) -> pd.DataFrame:
        """
        并发获取多个市场的元数据（Gamma API）。

        Parameters
        ----------
        condition_ids : list[str]
            conditionId 列表
        concurrency : int
            最大并发数
        """
        logger.info(f"批量拉取市场元数据 | {len(condition_ids)} 个, 并发={concurrency}")
        sem = asyncio.Semaphore(concurrency)
        results: list[dict] = []

        async def _fetch_one(cid: str):
            async with sem:
                try:
                    data = await self._get(
                        f"{GAMMA_API_BASE}/markets",
                        params={"condition_id": cid, "limit": 1},
                    )
                    if isinstance(data, list) and data:
                        results.append(data[0])
                    elif isinstance(data, dict):
                        results.append(data)
                except Exception as e:
                    logger.warning(f"市场 {cid[:16]}... 元数据获取失败: {e}")

        await asyncio.gather(*[_fetch_one(cid) for cid in condition_ids])
        logger.info(f"市场元数据获取完成 | 成功 {len(results)}/{len(condition_ids)}")
        return pd.DataFrame(results) if results else pd.DataFrame()

    # ── 高频地址预检 ──────────────────────────────────────

    HIGH_FREQ_THRESHOLD = 30  # 笔 TRADE / 小时

    async def _prescreen(self, address: str) -> dict:
        """
        快速预检：拉 1 页 activity (1000 条)，取最新 100 笔 TRADE，
        计算交易频率。>= 30 笔/小时判定为高频地址。

        返回 dict 包含判定结果和采样数据。
        """
        logger.info(f"预检开始 | 地址: {address}")

        try:
            data = await self._get(
                f"{DATA_API_BASE}/activity",
                params={"user": address, "limit": PAGE_LIMIT, "offset": 0},
            )
        except Exception as e:
            logger.warning(f"预检请求失败，降级到全量拉取: {e}")
            return {"is_high_freq": False, "error": str(e), "sample_df": pd.DataFrame()}

        records = [d for d in data if isinstance(d, dict)] if data else []
        total_in_page = len(records)

        if total_in_page < 10:
            logger.info(f"预检 | 仅 {total_in_page} 条 activity，非高频")
            sample_df = pd.DataFrame(records) if records else pd.DataFrame()
            return {
                "is_high_freq": False,
                "trade_count_in_sample": 0,
                "trades_per_hour": 0,
                "sample_time_span_hours": 0,
                "total_activity_in_page": total_in_page,
                "sample_df": sample_df,
            }

        sample_df = pd.DataFrame(records)

        # 筛选 TRADE 类型
        trades = [r for r in records if r.get("type") == "TRADE"]
        trade_count = len(trades)

        if trade_count < 100:
            logger.info(f"预检 | TRADE 仅 {trade_count} 笔 (< 100)，非高频")
            return {
                "is_high_freq": False,
                "trade_count_in_sample": trade_count,
                "trades_per_hour": 0,
                "sample_time_span_hours": 0,
                "total_activity_in_page": total_in_page,
                "sample_df": sample_df,
            }

        # 取最新 100 笔 TRADE
        trades_sorted = sorted(trades, key=lambda r: int(r.get("timestamp", 0)), reverse=True)
        top100 = trades_sorted[:100]

        ts_list = [int(r["timestamp"]) for r in top100]
        ts_max = max(ts_list)
        ts_min = min(ts_list)
        span_seconds = ts_max - ts_min

        if span_seconds == 0:
            # 所有交易同一秒，极端高频
            trades_per_hour = float("inf")
            span_hours = 0.0
        else:
            span_hours = span_seconds / 3600
            trades_per_hour = 100 / span_hours

        is_high_freq = trades_per_hour >= self.HIGH_FREQ_THRESHOLD

        newest_str = _ts_to_str(ts_max)
        oldest_str = _ts_to_str(ts_min)

        level = "WARNING" if is_high_freq else "INFO"
        logger.log(
            level,
            f"预检结果 | {'高频' if is_high_freq else '正常'} | "
            f"{trades_per_hour:.1f} 笔/小时 | "
            f"100 笔 TRADE 覆盖 {span_hours:.1f}h ({oldest_str} → {newest_str}) | "
            f"本页 TRADE {trade_count}/{total_in_page} 条"
        )

        return {
            "is_high_freq": is_high_freq,
            "trade_count_in_sample": trade_count,
            "trades_per_hour": round(trades_per_hour, 1) if trades_per_hour != float("inf") else 99999,
            "sample_time_span_hours": round(span_hours, 2),
            "sample_newest": newest_str,
            "sample_oldest": oldest_str,
            "total_activity_in_page": total_in_page,
            "sample_df": sample_df,
        }

    # ── 一键获取全部数据 ──────────────────────────────────

    async def fetch_all(self, address: str) -> dict[str, pd.DataFrame]:
        """
        两阶段数据采集：先预检交易频率，高频地址跳过全量 activity 拉取。

        返回 dict 包含 activity, closed_positions, positions，
        高频地址时额外包含 freq_check 字段。
        """
        logger.info(f"{'='*50}")
        logger.info(f"开始数据采集 | {address}")
        logger.info(f"{'='*50}")

        # 阶段 0：快速预检
        freq_check = await self._prescreen(address)

        if freq_check["is_high_freq"]:
            logger.warning(
                f"高频地址预检命中 | {freq_check['trades_per_hour']} 笔/小时, "
                f"跳过全量 activity 拉取，仅拉取 closed-positions + positions"
            )
            # 高频地址：跳过全量 activity，只拉 closed-positions 和 positions
            closed, positions = await asyncio.gather(
                self.get_closed_positions(address),
                self.get_positions(address),
            )
            return {
                "activity": freq_check["sample_df"],  # 保留预检的 1000 条采样
                "closed_positions": closed,
                "positions": positions,
                "freq_check": freq_check,
            }

        # 阶段 1：正常全量拉取
        # 预检的 1000 条已经是第一轮的数据，传入 get_all_activity 避免重复请求
        activity, closed, positions = await asyncio.gather(
            self.get_all_activity(address),
            self.get_closed_positions(address),
            self.get_positions(address),
        )

        return {
            "activity": activity,
            "closed_positions": closed,
            "positions": positions,
        }

    # ── Parquet 导出 ──────────────────────────────────────

    @staticmethod
    def save_parquet(
        data: dict[str, pd.DataFrame],
        address: str,
        output_dir: str = "data",
    ) -> dict[str, Path]:
        """
        将全量数据保存为 parquet 文件。

        文件命名: data/{address}_activity.parquet 等
        返回 {key: Path} 字典。
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        short_addr = address[:10]
        saved: dict[str, Path] = {}

        for key, df in data.items():
            if df.empty:
                continue
            # 清理时区信息（parquet 不支持混合时区）
            for col in df.select_dtypes(include=["datetimetz"]).columns:
                df[col] = df[col].dt.tz_localize(None)

            path = out / f"{short_addr}_{key}.parquet"
            df.to_parquet(path, index=False)
            saved[key] = path
            logger.info(f"已保存 | {path} ({len(df)} 行, {path.stat().st_size / 1024:.0f} KB)")

        return saved

    @staticmethod
    def load_parquet(address: str, output_dir: str = "data") -> dict[str, pd.DataFrame]:
        """从 parquet 文件加载数据。"""
        out = Path(output_dir)
        short_addr = address[:10]
        result: dict[str, pd.DataFrame] = {}

        for key in ["activity", "closed_positions", "positions"]:
            path = out / f"{short_addr}_{key}.parquet"
            if path.exists():
                result[key] = pd.read_parquet(path)
                logger.info(f"已加载 | {path} ({len(result[key])} 行)")
            else:
                result[key] = pd.DataFrame()

        return result


# ── 模块直接运行时的简单验证 ─────────────────────────────

if __name__ == "__main__":
    async def _quick_test():
        addr = "0x56687bf447db6ffa42ffe2204a05edaa20f55839"
        async with PolymarketFetcher() as f:
            data = await f.fetch_all(addr)
        for k, v in data.items():
            print(f"{k}: {len(v)} 条" if not v.empty else f"{k}: 空")

    asyncio.run(_quick_test())
