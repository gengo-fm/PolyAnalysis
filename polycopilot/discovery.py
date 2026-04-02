"""
Wallet Discovery Module for PolyAnalysis

Automatically discovers profitable Polymarket traders from multiple sources:
- Polymarket v1 Leaderboard API (multi-dimension: category × timePeriod × orderBy)
- TradeFox smart money page
- On-chain data analysis (Phase 2)

Usage:
    from polycopilot.discovery import WalletDiscoveryModule
    
    discovery = WalletDiscoveryModule(cache_manager)
    wallets = await discovery.discover_wallets(sources=["polymarket"])
"""

import asyncio
from collections import defaultdict

import httpx
from loguru import logger

from .cache import CacheManager

DATA_API_V1 = "https://data-api.polymarket.com/v1"


class WalletDiscoveryModule:
    """Discovers and analyzes profitable Polymarket wallets."""
    
    def __init__(
        self,
        cache_manager: CacheManager,
        copy_delay_seconds: float = 0.3,
        min_market_liquidity: float = 10000,
        max_slippage_pct: float = 1.0,
        exclude_market_makers: bool = True, # 新增参数
        market_maker_pnl_vol_ratio_threshold: float = 0.01, # 新增参数
    ):
        self._cache = cache_manager
        self._copy_delay = copy_delay_seconds
        self._min_liquidity = min_market_liquidity
        self._max_slippage = max_slippage_pct
        self._exclude_market_makers = exclude_market_makers
        self._market_maker_pnl_vol_ratio_threshold = market_maker_pnl_vol_ratio_threshold
    
    async def discover_wallets(
        self,
        sources: list[str],
        max_wallets_to_analyze: int = 20,
        min_profit_threshold: float = 10000.0,
        min_volume_threshold: float = 50000.0,
        min_active_days: int = 30,
    ) -> list[dict]:
        """Orchestrates: discover → dedup → filter → analyze → rank."""
        logger.info(f"开始钱包发现 | sources={sources}")
        
        raw = []
        if "polymarket_leaderboard" in sources or "polymarket" in sources:
            raw.extend(await self._fetch_leaderboard_multi())
        if "tradefox" in sources:
            raw.extend(await self._scrape_tradefox())
        if "on_chain" in sources:
            raw.extend(await self._get_on_chain_wallets())
        
        logger.info(f"原始发现: {len(raw)} 条记录")
        
        unique = self._deduplicate(raw)
        logger.info(f"去重后: {len(unique)} 个唯一地址")
        self._deduplicate_cache = unique # Store for later use in filtering
        
        filtered_by_threshold = self._filter_wallets_by_min_thresholds(
            unique, min_profit_threshold, min_volume_threshold
        )
        logger.info(f"利润/交易量过滤后: {len(filtered_by_threshold)} 个地址")
        
        if self._exclude_market_makers:
            filtered_addresses = self._filter_market_makers(filtered_by_threshold)
            logger.info(f"排除做市商后: {len(filtered_addresses)} 个地址")
        else:
            filtered_addresses = filtered_by_threshold
        
        analyzed = await self._batch_analyze(filtered_addresses)

        logger.info(f"分析完成: {len(analyzed)} 个报告")
        
        # Post-analysis filtering: 移除不可跟单的地址
        reliable_wallets = []
        excluded_by_reliability = 0
        for report in analyzed:
            reliability = report.get("copy_reliability", {}).get("copy_reliability", "")
            if "❌ 不可跟单" in reliability:
                excluded_by_reliability += 1
                logger.debug(f"排除 (不可跟单): {report.get('address', '')[:10]}... | {reliability}")
            else:
                reliable_wallets.append(report)
        
        if excluded_by_reliability:
            logger.info(f"排除不可跟单: {excluded_by_reliability} 个地址")
        
        ranked = sorted(
            reliable_wallets,
            key=lambda r: r.get("copy_trading_score", {}).get("total", 0),
            reverse=True,
        )[:max_wallets_to_analyze]
        
        logger.info(f"返回 Top {len(ranked)} 钱包 (已过滤不可跟单)")
        return ranked
    
    # ── Polymarket v1 Leaderboard API ──
    
    async def _fetch_leaderboard_multi(self) -> list[dict]:
        """
        Multi-dimension leaderboard discovery.
        Maximizes coverage by exploring all categories, time periods, and sorting methods.
        
        Coverage:
        - Old: ~7 strategies, ~280 unique addresses
        - New: ~20 strategies, ~2000+ unique addresses
        """
        # 完整策略矩阵（优化版）
        # 目标：保留老的 + 增加新的 = 最大化覆盖
        strategies = [
            # === 新崛起 (重点) ===
            ("OVERALL", "DAY",   "PNL", 500, "今日崛起"),
            ("OVERALL", "WEEK",  "PNL", 500, "本周新星"),
            ("OVERALL", "MONTH", "PNL", 500, "本月黑马"),
            
            # === 历史累计 (扩大) ===
            ("OVERALL",  "ALL",   "PNL", 1000, "历史盈利TOP"),
            ("OVERALL",  "ALL",   "VOL", 1000, "历史交易量TOP"),
            
            # === 分类扩展 ===
            ("CRYPTO",   "ALL",   "PNL", 500, "Crypto盈利"),
            ("CRYPTO",   "WEEK",  "PNL", 300, "Crypto新星"),
            ("POLITICS", "ALL",   "PNL", 500, "政治盈利"),
            ("POLITICS", "WEEK",  "PNL", 300, "政治新星"),
            ("SPORTS",   "ALL",   "PNL", 500, "体育盈利"),
            ("SPORTS",   "WEEK",  "PNL", 300, "体育新星"),
            ("TECH",     "ALL",   "PNL", 200, "科技盈利"),
            ("FINANCE",  "ALL",   "PNL", 200, "金融盈利"),
            ("ECONOMICS","ALL",   "PNL", 200, "经济盈利"),
            ("CULTURE",  "ALL",   "PNL", 200, "文化盈利"),
            ("WEATHER",  "ALL",   "PNL", 200, "天气盈利"),
            
            # === 分类交易量 ===
            ("CRYPTO",   "ALL",   "VOL", 200, "Crypto交易量"),
            ("POLITICS", "ALL",   "VOL", 200, "政治交易量"),
            ("SPORTS",   "ALL",   "VOL", 200, "体育交易量"),
        ]
        
        all_wallets = []
        async with httpx.AsyncClient(timeout=20) as client:
            for cat, period, order, max_limit, label in strategies:
                try:
                    wallets = await self._fetch_leaderboard(client, cat, period, order, max_limit)
                    for w in wallets:
                        w["source"] = f"leaderboard_{label}"
                    all_wallets.extend(wallets)
                    logger.info(f"  {label}: {len(wallets)} 个地址")
                except Exception as e:
                    logger.error(f"  {label} 失败: {e}")
                await asyncio.sleep(0.15)  # 快速获取
        
        return all_wallets
    
    async def _fetch_leaderboard(
        self, client: httpx.AsyncClient,
        category: str, time_period: str, order_by: str, limit: int,
    ) -> list[dict]:
        """Fetch leaderboard with pagination (max 50/page, offset up to 1000)."""
        results = []
        offset = 0
        page_size = min(limit, 50)
        
        while offset < limit:
            resp = await client.get(f"{DATA_API_V1}/leaderboard", params={
                "category": category,
                "timePeriod": time_period,
                "orderBy": order_by,
                "limit": page_size,
                "offset": offset,
            })
            resp.raise_for_status()
            data = resp.json()
            
            if not data:
                break
            
            for item in data:
                results.append({
                    "address": item.get("proxyWallet", ""),
                    "name": item.get("userName", ""),
                    "profit": f"${item.get('pnl', 0):,.0f}",
                    "volume": f"${item.get('vol', 0):,.0f}",
                    "rank": int(item.get("rank", 0)),
                    "pnl_raw": item.get("pnl", 0),
                    "vol_raw": item.get("vol", 0),
                    "x_username": item.get("xUsername", ""),
                    "verified": item.get("verifiedBadge", False),
                })
            
            offset += page_size
            if len(data) < page_size:
                break
            await asyncio.sleep(0.2)
        
        return results
    
    def _filter_wallets_by_min_thresholds(
        self,
        wallets_data: dict[str, dict],
        min_profit: float,
        min_volume: float,
    ) -> list[str]:
        """Filter by minimum profit and volume thresholds."""
        return [
            addr for addr, data in wallets_data.items()
            if data["profit"] >= min_profit and data["volume"] >= min_volume
        ]
    
    def _filter_market_makers(self, addresses: list[str]) -> list[str]:
        """
        排除做市商。
        
        做市商特征：超高交易量，但 PnL/Vol 比率极低（< 1%）。
        做市商通过提供流动性赚取微薄利润，不适合跟单。
        """
        filtered = []
        excluded_count = 0
        for addr in addresses:
            data = self._deduplicate_cache.get(addr, {})
            volume = data.get("volume", 0)
            profit = data.get("profit", 0)
            
            if volume > 0:
                pnl_vol_ratio = abs(profit) / volume
            else:
                pnl_vol_ratio = float('inf')  # No volume = not a market maker
            
            if pnl_vol_ratio < self._market_maker_pnl_vol_ratio_threshold:
                excluded_count += 1
                logger.debug(
                    f"排除做市商: {data.get('name', addr[:10])} | "
                    f"PnL: ${profit:,.0f} | Vol: ${volume:,.0f} | "
                    f"PnL/Vol: {pnl_vol_ratio:.2%}"
                )
            else:
                filtered.append(addr)
        
        if excluded_count:
            logger.info(f"排除了 {excluded_count} 个疑似做市商 (PnL/Vol < {self._market_maker_pnl_vol_ratio_threshold:.0%})")
        return filtered
    
    # ── Dedup ──
    
    def _deduplicate(self, raw: list[dict]) -> dict[str, dict]:
        """Merge duplicates, keep max profit/volume, collect all sources."""
        unique = defaultdict(lambda: {
            "profit": 0.0, "volume": 0.0, "name": "",
            "sources": set(), "rank_best": 9999,
            "x_username": "", "verified": False,
        })
        
        for entry in raw:
            addr = entry.get("address", "").lower()
            if not addr or not addr.startswith("0x"):
                continue
            
            profit = entry.get("pnl_raw") or 0
            volume = entry.get("vol_raw") or 0
            
            if not profit:
                try:
                    profit = float(entry.get("profit", "0").replace("+", "").replace("$", "").replace(",", ""))
                except (ValueError, TypeError):
                    profit = 0.0
            if not volume:
                try:
                    volume = float(entry.get("volume", "0").replace("$", "").replace(",", ""))
                except (ValueError, TypeError):
                    volume = 0.0
            
            d = unique[addr]
            d["profit"] = max(d["profit"], profit)
            d["volume"] = max(d["volume"], volume)
            d["name"] = entry.get("name") or d["name"] or addr
            d["sources"].add(entry.get("source", "unknown"))
            d["rank_best"] = min(d["rank_best"], entry.get("rank", 9999))
            d["x_username"] = entry.get("x_username") or d["x_username"]
            d["verified"] = d["verified"] or entry.get("verified", False)
        
        return {a: {**d, "sources": list(d["sources"])} for a, d in unique.items()}
    
    # ── Batch Analysis ──
    
    async def _batch_analyze(self, addresses: list[str]) -> list[dict]:
        """Analyze wallets with concurrency limit."""
        from polycopilot.cache import CacheManager
        from polycopilot.fetcher import PolymarketFetcher
        from polycopilot.processor import TradeProcessor
        from polycopilot.analyzer import WalletAnalyzer
        
        sem = asyncio.Semaphore(5)
        
        async def one(addr: str) -> dict | None:
            async with sem:
                try:
                    cache_mgr = CacheManager()
                    async with PolymarketFetcher() as fetcher:
                        data = await fetcher.fetch_incremental(addr, cache_mgr)
                    
                    processor = TradeProcessor(
                        activity_df=data["activity"],
                        closed_positions_df=data["closed_positions"],
                    )
                    processor.build_reports()
                    
                    if not processor.reports:
                        return None
                    
                    analyzer = WalletAnalyzer(
                        processor.reports,
                        address=addr,
                        copy_delay_seconds=self._copy_delay,
                        min_market_liquidity=self._min_liquidity,
                        max_slippage_pct=self._max_slippage,
                    )
                    return analyzer.generate_report()
                except Exception as e:
                    logger.error(f"分析失败 {addr[:10]}...: {e}")
                return None
        
        results = await asyncio.gather(*(one(a) for a in addresses))
        return [r for r in results if r]
    
    # ── Placeholder sources ──
    
    async def _scrape_tradefox(self) -> list[dict]:
        logger.warning("TradeFox scraper not yet implemented")
        return []
    
    async def _get_on_chain_wallets(self) -> list[dict]:
        logger.warning("On-chain discovery not yet implemented")
        return []
