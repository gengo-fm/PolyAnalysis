# Tasks: Wallet Discovery Module Implementation

## Phase 1: Core Discovery (Priority: P0)

### Task 1.1: Create `polycopilot/discovery.py` skeleton
- [ ] Create `WalletDiscoveryModule` class with constructor
- [ ] Implement `discover_wallets()` orchestration method (stub)
- [ ] Implement `_deduplicate_and_normalize()` method
- [ ] Implement `_filter_wallets()` method
- [ ] Implement `_batch_analyze_wallets()` method (async)
- **Depends on**: None
- **Estimated effort**: 2h

### Task 1.2: Implement Polymarket Leaderboard Scraper
- [ ] Implement `_scrape_polymarket_leaderboard()` using browser tool
- [ ] Handle pagination (click next page, extract data from each page)
- [ ] Handle timeframe selection (Today/Weekly/Monthly/All)
- [ ] Extract: address, name, profit, volume, rank
- [ ] Add error handling and retries
- [ ] Test with `limit=20` (1 page) and `limit=50` (3 pages)
- **Depends on**: Task 1.1
- **Estimated effort**: 3h

### Task 1.3: Implement TradeFox Smart Money Scraper
- [ ] Inspect TradeFox smart money page structure
- [ ] Implement `_scrape_tradefox()` using browser tool
- [ ] Extract wallet addresses and any available metrics
- [ ] Add error handling
- [ ] Test extraction
- **Depends on**: Task 1.1
- **Estimated effort**: 2h

### Task 1.4: Add `discover` CLI subcommand to `analyze.py`
- [ ] Add `discover` subparser with options (--sources, --top-n, --min-profit, --min-volume, --output-json, --output-file)
- [ ] Wire up to `WalletDiscoveryModule.discover_wallets()`
- [ ] Implement terminal table output for ranked wallets
- [ ] Implement JSON output option
- [ ] Test CLI: `python analyze.py discover --sources polymarket --top-n 10`
- **Depends on**: Task 1.1, 1.2
- **Estimated effort**: 2h

### Task 1.5: End-to-end test Phase 1
- [ ] Run `python analyze.py discover --sources polymarket,tradefox --top-n 10`
- [ ] Verify: scraping → dedup → filter → analyze → rank → output
- [ ] Check cache usage (second run should be faster)
- [ ] Fix any integration issues
- **Depends on**: Task 1.2, 1.3, 1.4
- **Estimated effort**: 1h

---

## Phase 2: Extended Sources (Priority: P1)

### Task 2.1: Implement HashDive Scraper
- [ ] Inspect HashDive page structure (https://www.hashdive.com/)
- [ ] Implement `_scrape_hashdive()` using browser tool
- [ ] Extract wallet addresses and Smart Score (if available)
- [ ] Add error handling
- [ ] Test extraction
- **Depends on**: Task 1.1
- **Estimated effort**: 2h

### Task 2.2: Implement Polymarket Analytics Scraper
- [ ] Inspect Polymarket Analytics page structure (https://polymarketanalytics.com/)
- [ ] Implement `_scrape_polymarket_analytics()` using browser tool
- [ ] Extract wallet addresses and metrics
- [ ] Add error handling
- [ ] Test extraction
- **Depends on**: Task 1.1
- **Estimated effort**: 2h

### Task 2.3: Parse Awesome-Prediction-Market-Tools
- [ ] Fetch GitHub README via web_fetch
- [ ] Parse Markdown to extract tool names and URLs
- [ ] Identify tools with "smart money", "whale tracking", "top traders" keywords
- [ ] Store as a reference list for future source expansion
- **Depends on**: None
- **Estimated effort**: 1h

---

## Phase 3: On-Chain Discovery (Priority: P2)

### Task 3.1: Install and configure `web3.py`
- [ ] `pip install web3` in project venv
- [ ] Test connection to Polygon RPC endpoint
- [ ] Document RPC endpoint configuration
- **Depends on**: None
- **Estimated effort**: 0.5h

### Task 3.2: Identify Polymarket contract addresses
- [ ] Research Polymarket's core contracts on Polygon PoS
- [ ] Find contract addresses via PolygonScan or official docs
- [ ] Download contract ABIs
- [ ] Store in `polycopilot/contracts/` directory
- **Depends on**: Task 3.1
- **Estimated effort**: 2h

### Task 3.3: Implement basic on-chain wallet discovery
- [ ] Implement `_get_on_chain_wallets()` method
- [ ] Query contract events (e.g., PositionBought, CollateralDeposit)
- [ ] Filter by volume threshold
- [ ] Extract unique wallet addresses
- [ ] Test with recent block range
- **Depends on**: Task 3.1, 3.2
- **Estimated effort**: 4h

### Task 3.4: Integrate on-chain source into discovery pipeline
- [ ] Add "on_chain" as a valid source in `discover_wallets()`
- [ ] Test: `python analyze.py discover --sources on_chain --top-n 10`
- [ ] Verify on-chain discovered wallets are analyzed correctly
- **Depends on**: Task 3.3, 1.4
- **Estimated effort**: 1h

---

## Phase 4: Polish & Testing (Priority: P1)

### Task 4.1: Comprehensive error handling
- [ ] Add graceful degradation for each source (if one fails, others continue)
- [ ] Add timeout handling for browser scraping
- [ ] Add rate limiting for batch analysis
- [ ] Log all errors with context
- **Depends on**: Phase 1, 2
- **Estimated effort**: 2h

### Task 4.2: Unit tests
- [ ] Test `_deduplicate_and_normalize()` with various inputs
- [ ] Test `_filter_wallets()` with edge cases
- [ ] Test CLI argument parsing for `discover`
- [ ] Mock browser/web3 calls for scraper tests
- **Depends on**: Phase 1
- **Estimated effort**: 3h

### Task 4.3: Documentation
- [ ] Update README.md with `discover` command usage
- [ ] Document data source configuration
- [ ] Document on-chain setup (RPC, API keys)
- [ ] Add examples to `docs/`
- **Depends on**: Phase 1, 2, 3
- **Estimated effort**: 1h

### Task 4.4: Performance optimization
- [ ] Profile batch analysis for bottlenecks
- [ ] Implement concurrency limits (e.g., max 5 parallel analyses)
- [ ] Optimize cache hit rate
- [ ] Add progress bar for long-running discovery
- **Depends on**: Phase 1
- **Estimated effort**: 2h

---

## Summary

| Phase | Tasks | Estimated Effort | Priority |
|-------|-------|-----------------|----------|
| Phase 1: Core Discovery | 5 tasks | ~10h | P0 |
| Phase 2: Extended Sources | 3 tasks | ~5h | P1 |
| Phase 3: On-Chain Discovery | 4 tasks | ~7.5h | P2 |
| Phase 4: Polish & Testing | 4 tasks | ~8h | P1 |
| **Total** | **16 tasks** | **~30.5h** | |

---
