# Design: Wallet Discovery Module Implementation

## 1. Module Structure and Classes

### `polycopilot/discovery.py`

```python
import asyncio
import pandas as pd
from loguru import logger
from web3 import Web3, HTTPProvider
from eth_abi import decode_single, decode_abi
from eth_utils import encode_hex, decode_hex
from collections import defaultdict
import re

from .cache import CacheManager
from .fetcher import PolymarketFetcher
from .analyzer import WalletAnalyzer, BehaviorProfileConfig, MarketReport # For batch analysis
from analyze import run_analysis # Import the async analysis function

class WalletDiscoveryModule:
    def __init__(
        self,
        cache_manager: CacheManager,
        polymarket_fetcher: PolymarketFetcher,
        rpc_url: str = "https://polygon-rpc.com", # Default Polygon RPC
        web3_api_key: str = None, # Optional API key for Web3 provider
        profile_config: BehaviorProfileConfig = None,
        copy_delay_seconds: float = 0.3,
        min_market_liquidity: float = 10000,
        max_slippage_pct: float = 1.0,
    ):
        self._cache_manager = cache_manager
        self._polymarket_fetcher = polymarket_fetcher
        self._profile_config = profile_config or BehaviorProfileConfig()
        self._copy_delay_seconds = copy_delay_seconds
        self._min_market_liquidity = min_market_liquidity
        self._max_slippage_pct = max_slippage_pct
        
        # Web3 setup for on-chain
        self._w3 = Web3(HTTPProvider(rpc_url))
        if not self._w3.is_connected():
            logger.error(f"Failed to connect to Web3 provider at {rpc_url}")
            raise ConnectionError(f"Cannot connect to Polygon RPC at {rpc_url}")
        
        # Polymarket Contract Addresses (replace with actual mainnet addresses)
        self._polymarket_contracts = {
            "ConditionFactory": {
                "address": "0x...", # Placeholder, find actual
                "abi": [...] # Placeholder, find actual
            },
            "FixedProductMarketMaker": {
                "address": "0x...", # Placeholder, find actual
                "abi": [...] # Placeholder, find actual
            },
            # Add other relevant contracts
        }

        # Regex for wallet address extraction from URLs
        self._profile_url_pattern = re.compile(r'/profile/(0x[a-fA-F0-9]{40})')

    async def discover_wallets(
        self,
        sources: list[str],
        max_wallets_to_analyze: int,
        min_profit_threshold: float,
        min_volume_threshold: float,
        min_active_days: int,
    ) -> list[dict]:
        """
        Orchestrates wallet discovery from multiple sources, filters, analyzes, and ranks them.
        """
        logger.info(f"Starting wallet discovery from sources: {sources}")
        
        raw_discovered_wallets = []
        if "polymarket_leaderboard" in sources:
            raw_discovered_wallets.extend(await self._scrape_polymarket_leaderboard())
        if "tradefox" in sources:
            raw_discovered_wallets.extend(await self._scrape_tradefox())
        if "hashdive" in sources: # New source
            raw_discovered_wallets.extend(await self._scrape_hashdive())
        if "on_chain" in sources:
            raw_discovered_wallets.extend(await self._get_on_chain_wallets())
            
        logger.info(f"Discovered {len(raw_discovered_wallets)} raw wallet entries.")

        # Deduplication and Normalization
        unique_wallets_data = self._deduplicate_and_normalize(raw_discovered_wallets)
        logger.info(f"After deduplication, {len(unique_wallets_data)} unique wallets.")

        # Initial Filtering
        filtered_wallets = self._filter_wallets(
            unique_wallets_data,
            min_profit_threshold,
            min_volume_threshold,
            min_active_days,
        )
        logger.info(f"After initial filtering, {len(filtered_wallets)} wallets remain.")

        # Batch Analysis
        analyzed_reports = await self._batch_analyze_wallets(filtered_wallets)
        logger.info(f"Analyzed {len(analyzed_reports)} wallets.")

        # Ranking
        ranked_wallets = sorted(
            analyzed_reports,
            key=lambda r: r.get("copy_trading_score", {}).get("total", 0),
            reverse=True,
        )[:max_wallets_to_analyze]
        
        return ranked_wallets

    async def _scrape_polymarket_leaderboard(self, limit: int = 50) -> list[dict]:
        """Scrapes Polymarket leaderboard for top N wallets."""
        # Implementation using OpenClaw browser tool as described in data-sources.md
        # This will involve multiple browser.act calls, page navigation, and data extraction
        # Example structure:
        # browser.open(url="https://polymarket.com/leaderboard")
        # await browser.act(kind="click", ref="e89") # Click "All" timeframe
        # ... extract data and paginate ...
        # return [{address, name, profit, volume, rank}, ...]
        logger.warning("Polymarket Leaderboard scraper not yet implemented.")
        return []

    async def _scrape_tradefox(self) -> list[dict]:
        """Scrapes TradeFox smart money page."""
        # Implementation using OpenClaw browser tool
        logger.warning("TradeFox scraper not yet implemented.")
        return []

    async def _scrape_hashdive(self) -> list[dict]:
        """Scrapes HashDive for smart money."""
        # Implementation using OpenClaw browser tool
        logger.warning("HashDive scraper not yet implemented.")
        return []

    async def _get_on_chain_wallets(self) -> list[dict]:
        """Discovers wallets via on-chain data analysis using web3.py."""
        # Implementation as described in on-chain-discovery.md
        # This will involve:
        # 1. Getting contract ABIs and addresses
        # 2. Querying contract events (e.g., MarketCreated, PositionBought)
        # 3. Filtering by volume/activity
        logger.warning("On-chain discovery not yet implemented.")
        return []

    def _deduplicate_and_normalize(self, raw_wallets: list[dict]) -> dict[str, dict]:
        """Deduplicates wallets and normalizes their metrics."""
        unique_wallets = defaultdict(lambda: {"profit": 0.0, "volume": 0.0, "sources": set()})
        for entry in raw_wallets:
            address = entry["address"].lower()
            profit_str = entry.get("profit", "$0").replace("$", "").replace(",", "")
            volume_str = entry.get("volume", "$0").replace("$", "").replace(",", "")

            try:
                profit = float(profit_str)
                volume = float(volume_str)
            except ValueError:
                profit = 0.0
                volume = 0.0
            
            unique_wallets[address]["profit"] = max(unique_wallets[address]["profit"], profit)
            unique_wallets[address]["volume"] = max(unique_wallets[address]["volume"], volume)
            unique_wallets[address]["name"] = entry.get("name", unique_wallets[address].get("name", address))
            unique_wallets[address]["sources"].add(entry.get("source", "unknown"))

        return {addr: {**data, "sources": list(data["sources"])} for addr, data in unique_wallets.items()}

    def _filter_wallets(
        self,
        wallets_data: dict[str, dict],
        min_profit: float,
        min_volume: float,
        min_active_days: int, # This needs actual analysis, so initial filter is basic
    ) -> list[str]:
        """Applies initial filters to the unique wallet list."""
        filtered_addresses = []
        for address, data in wallets_data.items():
            if data["profit"] >= min_profit and data["volume"] >= min_volume:
                # High-frequency check will happen in run_analysis or be part of BehaviorProfileConfig
                # min_active_days filtering will require a full analysis first
                filtered_addresses.append(address)
        return filtered_addresses

    async def _batch_analyze_wallets(self, addresses: list[str]) -> list[dict]:
        """Analyzes a batch of wallets using run_analysis."""
        tasks = []
        for address in addresses:
            # run_analysis accepts TradeFox params, so we pass them here
            task = asyncio.create_task(run_analysis(
                address=address,
                force=False, # Use incremental fetch
                json_output=True, # Get full JSON report
                copy_delay=self._copy_delay_seconds,
                min_liquidity=self._min_market_liquidity,
                max_slippage=self._max_slippage_pct,
            ))
            tasks.append(task)
        
        # Wait for all analyses to complete and collect reports
        reports = []
        for f in asyncio.as_completed(tasks):
            try:
                # run_analysis returns the WalletAnalyzer object, we need its report
                analyzer = await f
                if analyzer and analyzer.report:
                    reports.append(analyzer.report)
            except Exception as e:
                logger.error(f"Error analyzing wallet: {e}")
        return reports

# --- CLI Integration ---
# (To be added to analyze.py)
# def add_discovery_subparser(subparsers):
#     discover_parser = subparsers.add_parser("discover", help="Discover smart money wallets")
#     discover_parser.add_argument("--sources", type=str, default="polymarket,tradefox",
#                                  help="Comma-separated sources for discovery")
#     discover_parser.add_argument("--top-n", type=int, default=20,
#                                  help="Number of top wallets to output")
#     discover_parser.add_argument("--min-profit", type=float, default=10000.0,
#                                  help="Minimum profit for filtering")
#     discover_parser.add_argument("--min-volume", type=float, default=50000.0,
#                                  help="Minimum volume for filtering")
#     discover_parser.add_argument("--min-active-days", type=int, default=30,
#                                  help="Minimum active days for filtering")
#     discover_parser.add_argument("--output-json", action="store_true",
#                                  help="Output results as JSON to stdout")
#     discover_parser.add_argument("--output-file", type=str,
#                                  help="Path to save the discovery report")
#     discover_parser.set_defaults(func=run_discovery_command)
#
# async def run_discovery_command(args):
#     # Instantiate discovery module and call discover_wallets
#     # Print/save results
#     pass
```

### 2. Polymarket Contract ABIs and Addresses (Placeholders)

I will need to manually find the actual Polymarket contract addresses and their ABIs on PolygonScan or from official documentation. For the design, placeholders are used.

### 3. `analyze.py` Modifications

The `analyze.py` script will be modified to include the new `discover` subcommand. This will involve:
- Adding a new subparser for `discover`.
- Parsing `discover`-specific arguments.
- Instantiating `WalletDiscoveryModule` and calling its `discover_wallets` method.
- Handling output formats (JSON, terminal table).

### 4. Web Scraping Details (High-Level)

The `_scrape_polymarket_leaderboard`, `_scrape_tradefox`, and `_scrape_hashdive` methods will utilize OpenClaw's `browser` tool. This tool allows executing JavaScript in a browser context, which is ideal for extracting data from dynamically loaded web pages.

-   **Polymarket Leaderboard**: Will involve `browser.act()` with `kind='click'` for pagination and `kind='evaluate'` with JavaScript to query the DOM for wallet details.
-   **TradeFox**: Similar approach, targeting the specific structure of TradeFox's "Smart Money" page.
-   **HashDive**: Will require inspection to identify the correct selectors.

### 5. On-Chain Data Query Details (High-Level)

The `_get_on_chain_wallets` method will use `web3.py`.
-   **Contract Initialization**:
    ```python
    # Example for ConditionFactory
    condition_factory_contract = self._w3.eth.contract(
        address=self._polymarket_contracts["ConditionFactory"]["address"],
        abi=self._polymarket_contracts["ConditionFactory"]["abi"]
    )
    ```
-   **Event Filtering**:
    ```python
    # Example: filter for MarketCreated events
    event_filter = condition_factory_contract.events.MarketCreated.create_filter(
        fromBlock="latest", # Or a specific block number
        toBlock="latest",
        argument_filters={} # Filter by specific arguments if needed
    )
    new_events = event_filter.get_new_entries()
    # Process events to extract creator addresses and market IDs
    ```
-   **Transaction Tracing**: For more advanced analysis, one might use `web3.py` to trace transactions to Polymarket contracts, but initially, event-based discovery is sufficient.

## 6. Error Handling and Robustness

-   **Browser Scrapers**: Implement `try-except` blocks for `browser.act()` calls. Use `loguru` to log errors, and return empty lists on failure gracefully.
-   **Web3.py**: Handle `ConnectionError` for RPC, `ContractLogicError` for contract calls, and `HTTPError` for API rate limits.
-   **Data Parsing**: Robust `try-except` blocks when converting scraped strings (profit, volume) to numbers.
-   **Retries**: Implement simple retry logic for network-dependent operations (e.g., in `PolymarketFetcher`, can extend to scrapers).

## 7. Performance Considerations

-   **Asynchronous Operations**: All network I/O (fetching, scraping, on-chain queries) will be `asyncio` based.
-   **Batch Analysis**: `asyncio.gather()` or `asyncio.as_completed()` will be used to run `run_analysis` for multiple wallets concurrently.
-   **Caching**: `CacheManager` will prevent re-fetching and re-analyzing already processed wallet data, significantly speeding up subsequent runs.
-   **Rate Limiting**: For web scrapers, implement `asyncio.sleep()` between requests. For `web3.py`, manage RPC rate limits (potentially via API key).

---
