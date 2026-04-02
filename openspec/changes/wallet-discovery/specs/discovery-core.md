# Specs: Wallet Discovery Module Core Logic

## 1. Goal
Implement the core logic for merging, filtering, and orchestrating the analysis of wallet addresses discovered from various sources.

## 2. Main Module: `polycopilot/discovery.py`

### Class: `WalletDiscoveryModule`

#### Constructor (`__init__`)
-   **Parameters**:
    -   `cache_manager`: An instance of `CacheManager` to manage local wallet data.
    -   `polymarket_fetcher`: An instance of `PolymarketFetcher` for initial data fetching and pre-screening.
    -   `max_wallets_to_analyze`: Integer, limits the total number of unique wallets to analyze after filtering (e.g., Top 50).
    -   `min_profit_threshold`: Float, minimum profit for a wallet to be considered (e.g., $10,000).
    -   `min_volume_threshold`: Float, minimum volume for a wallet to be considered (e.g., $50,000).
    -   `min_active_days`: Integer, minimum active days for a wallet to be considered.
    -   `copy_delay_seconds`: Float, TradeFox-adapted copy delay for scoring.
    -   `min_market_liquidity`: Float, TradeFox market liquidity param for scoring.
    -   `max_slippage_pct`: Float, TradeFox max slippage param for scoring.

#### Method: `discover_wallets(sources: list[str]) -> list[dict]`
-   **Purpose**: Orchestrates the entire discovery process from multiple sources to ranked output.
-   **Parameters**:
    -   `sources`: A list of strings indicating which discovery sources to use (e.g., `["polymarket_leaderboard", "tradefox", "on_chain"]`).
-   **Workflow**:
    1.  **Source Aggregation**:
        -   Initialize an empty list `raw_discovered_wallets`.
        -   For each `source` in `sources`:
            -   Call the appropriate scraper/extractor function (e.g., `_scrape_polymarket_leaderboard()`, `_scrape_tradefox()`, `_get_on_chain_wallets()`).
            -   Append results (list of dictionaries with `address`, `name`, `profit_str`, `volume_str` etc.) to `raw_discovered_wallets`.
    2.  **Deduplication and Normalization**:
        -   Create a unique list of wallet addresses.
        -   Normalize profit and volume strings to numerical values (e.g., "$12,394,130" -> 12394130.0).
        -   Combine information for duplicate addresses (e.g., take max profit if from multiple sources).
    3.  **Initial Filtering**:
        -   Filter out wallets based on `min_profit_threshold`, `min_volume_threshold`.
        -   Filter out addresses detected as high-frequency (using `PolymarketFetcher`'s pre-screening logic).
    4.  **Batch Analysis Orchestration**:
        -   Initialize an empty list `analyzed_wallets_reports`.
        -   For each `unique_address` in the filtered list:
            -   Asynchronously call `run_analysis()` from `analyze.py` (or a dedicated internal analysis function).
            -   Pass `copy_delay_seconds`, `min_market_liquidity`, `max_slippage_pct` to `WalletAnalyzer`.
            -   Collect the resulting analysis report (JSON structure).
    5.  **Ranking**:
        -   Sort `analyzed_wallets_reports` in descending order based on `copy_trading_score.total`.
        -   Apply `max_wallets_to_analyze` limit.
    6.  **Return**: A list of ranked wallet reports.

#### Helper Method: `_scrape_polymarket_leaderboard(limit: int, timeframe: str) -> list[dict]`
-   Encapsulates the scraping logic described in `specs/data-sources.md`.
-   Uses `OpenClaw browser tool`.

#### Helper Method: `_scrape_tradefox() -> list[dict]`
-   Encapsulates the scraping logic described in `specs/data-sources.md`.
-   Uses `OpenClaw browser tool`.

#### Helper Method: `_get_on_chain_wallets() -> list[dict]`
-   Encapsulates the on-chain discovery logic described in `specs/on-chain-discovery.md`.
-   Uses `web3.py`.

## 3. CLI Integration: `analyze.py`

### New Subcommand: `discover`

#### Usage
```bash
python analyze.py discover [options]
```

#### Options
-   `--sources`: Comma-separated list of sources (e.g., `polymarket,tradefox,on_chain`). Default: `polymarket,tradefox`.
-   `--top-n`: Integer, limit the number of top wallets to output. Default: 20.
-   `--min-profit`: Float, filter wallets below this profit. Default: $10,000.
-   `--min-volume`: Float, filter wallets below this volume. Default: $50,000.
-   `--min-active-days`: Integer, filter wallets with fewer active days. Default: 30.
-   `--output-json`: Boolean flag, output results as JSON to stdout.
-   `--output-file`: String, path to save the discovery report.

#### Implementation
-   Add a new `discover_parser` to `analyze.py`'s `main` function.
-   Call `WalletDiscoveryModule().discover_wallets()` with parsed arguments.
-   Format and print the results based on `--output-json` or `--output-file`.

## 4. Testing

### Unit Tests (`tests/test_discovery.py`)
-   Test each scraper function (`_scrape_polymarket_leaderboard`, `_scrape_tradefox`).
-   Test `_get_on_chain_wallets` (mocking `web3.py` interactions).
-   Test deduplication and normalization logic.
-   Test filtering logic (`min_profit`, `min_volume`, high-frequency).
-   Test ranking logic.

### Integration Tests
-   Run `analyze.py discover` with various parameters and verify output.
-   Verify cache interaction during batch analysis.

---
