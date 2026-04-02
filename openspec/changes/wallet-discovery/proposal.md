# Proposal: Wallet Discovery Module

## Why

**Problem:**
Currently, the PolyAnalysis system requires users to manually provide wallet addresses for analysis. This creates a significant bottleneck:
- Users must already know which wallets are worth analyzing
- No systematic way to discover high-performing traders ("smart money")
- Manual discovery through social media, forums, or leaderboards is time-consuming and incomplete
- Missing opportunities to identify emerging profitable traders before they become widely known

**Opportunity:**
By building an automated wallet discovery module, we can:
- Continuously scan multiple data sources to identify profitable traders
- Provide users with a curated list of "smart money" wallets ranked by our TradeFox-adapted scoring system
- Enable proactive discovery rather than reactive analysis
- Create a competitive advantage by finding profitable traders faster than manual methods

**Why Now:**
- The core analysis engine (PolyAnalysis) is mature and proven
- TradeFox scoring adaptation is complete, providing accurate copy-trading evaluation
- Multiple data sources are available (Polymarket leaderboard, TradeFox, analytics platforms, on-chain data)
- User feedback indicates strong demand for automated smart money discovery

## What Changes

### High-Level Changes

1. **New Discovery Module** (`polycopilot/discovery.py`)
   - Multi-source wallet address scraping
   - Deduplication and filtering logic
   - Batch analysis orchestration
   - Smart money ranking and reporting

2. **CLI Extension** (`analyze.py`)
   - New `discover` subcommand
   - Configurable discovery parameters (sources, filters, top-N)
   - Output formats (JSON, CSV, terminal table)

3. **Data Source Integrations**
   - Polymarket official leaderboard scraper
   - TradeFox smart money page scraper
   - Third-party analytics platforms (HashDive, Polymarket Analytics)
   - On-chain data analysis (Polygon blockchain via web3.py)

4. **Discovery Pipeline**
   - Source → Scrape → Merge → Filter → Analyze → Rank → Report

### User-Facing Changes

**Before:**
```bash
# User must manually find addresses
python analyze.py 0x123...
```

**After:**
```bash
# Automated discovery and ranking
python analyze.py discover --sources polymarket,tradefox --top-n 50 --min-profit 100000

# Output: Ranked list of top 50 wallets with scores, grades, and key metrics
```

### Technical Changes

- Add `browser` automation for web scraping
- Add `web3.py` for on-chain data queries
- Implement async batch processing for parallel analysis
- Add caching layer to avoid re-analyzing recently discovered wallets
- Create discovery report format with wallet metadata + analysis summary

## Impact

### Positive Impact

**For Users:**
- **Time Savings**: Automated discovery vs. hours of manual research
- **Better Coverage**: Access to multiple data sources simultaneously
- **Data-Driven Decisions**: Ranked by proven scoring algorithm, not gut feeling
- **Early Discovery**: Find profitable traders before they're widely known
- **Continuous Monitoring**: Can be run periodically to track new entrants

**For the System:**
- **Increased Value**: Transforms from analysis tool → discovery + analysis platform
- **Competitive Moat**: Unique multi-source aggregation with TradeFox-adapted scoring
- **Scalability**: Batch processing enables analyzing hundreds of wallets efficiently
- **Extensibility**: Easy to add new data sources as they emerge

### Potential Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| **Rate Limiting**: Web scraping may hit rate limits | Implement exponential backoff, respect robots.txt, add delays between requests |
| **Data Quality**: Scraped data may be incomplete/incorrect | Validate all addresses, cross-reference multiple sources, log data quality issues |
| **Performance**: Analyzing 100+ wallets may be slow | Use async/parallel processing, implement smart caching, allow incremental discovery |
| **Maintenance**: Website structure changes break scrapers | Modular design per source, comprehensive error handling, monitoring/alerts |
| **API Costs**: On-chain queries may require paid API keys | Start with free tiers, make on-chain analysis optional, document API key setup |

### Success Metrics

- **Discovery Coverage**: Number of unique wallets discovered per run
- **Analysis Throughput**: Wallets analyzed per minute
- **Quality Score**: Percentage of discovered wallets scoring B+ or higher
- **User Adoption**: Usage frequency of `discover` command
- **Time to Discovery**: How quickly new profitable traders are identified

## Dependencies

### External Dependencies
- `httpx` (already installed) - for HTTP requests
- `beautifulsoup4` or `playwright` - for HTML parsing (if needed beyond browser tool)
- `web3.py` - for on-chain data analysis
- `asyncio` (stdlib) - for parallel processing

### Internal Dependencies
- Existing `PolymarketFetcher` - for wallet data retrieval
- Existing `WalletAnalyzer` - for scoring discovered wallets
- Existing `CacheManager` - for avoiding redundant analysis
- OpenClaw `browser` tool - for web scraping

### API Keys (Optional)
- Etherscan/PolygonScan API key - for on-chain data (free tier available)
- Brave Search API key - for web search (if needed)

## Timeline Estimate

- **Phase 1 - Core Discovery** (2-3 days)
  - Implement Polymarket leaderboard scraper
  - Implement TradeFox scraper
  - Build discovery pipeline (scrape → merge → filter)
  - Add `discover` CLI command

- **Phase 2 - Batch Analysis** (1-2 days)
  - Implement parallel wallet analysis
  - Add progress reporting
  - Create discovery report format

- **Phase 3 - Extended Sources** (2-3 days)
  - Add HashDive/Polymarket Analytics scrapers
  - Implement basic on-chain analysis
  - Add source selection flags

- **Phase 4 - Polish & Testing** (1-2 days)
  - Error handling and retry logic
  - Documentation
  - Integration testing
  - Performance optimization

**Total: 6-10 days**

## Open Questions

1. **Caching Strategy**: How long should we cache discovery results before re-scraping?
   - Proposal: 24 hours for leaderboards, 7 days for analyzed wallets

2. **Filtering Thresholds**: What minimum criteria should wallets meet to be analyzed?
   - Proposal: Min profit $10k, min volume $50k, active in last 30 days

3. **On-Chain Priority**: Should on-chain analysis be Phase 1 or Phase 3?
   - Proposal: Phase 3 (start with easier web scraping, add on-chain later)

4. **Output Format**: JSON, CSV, or both?
   - Proposal: Both, with `--format` flag

5. **Scheduling**: Should discovery run on a schedule (cron) or on-demand only?
   - Proposal: Start with on-demand, add scheduling in future iteration

## Alternatives Considered

### Alternative 1: Manual Curation
- **Pros**: Simple, no scraping complexity
- **Cons**: Not scalable, requires constant manual effort, misses new traders
- **Decision**: Rejected - defeats the purpose of automation

### Alternative 2: API-Only Approach
- **Pros**: More reliable than scraping, structured data
- **Cons**: Most platforms don't offer public APIs for trader lists
- **Decision**: Use APIs where available, scraping where necessary

### Alternative 3: On-Chain Only
- **Pros**: Most authoritative data source, no scraping
- **Cons**: Complex to implement, requires deep Polymarket contract knowledge, slower
- **Decision**: Include as one source, not the only source

## Conclusion

The Wallet Discovery Module is a natural evolution of PolyAnalysis from a reactive analysis tool to a proactive discovery platform. By automating the identification of profitable traders across multiple data sources, we significantly increase the value proposition for users while maintaining our technical advantage through TradeFox-adapted scoring.

The modular design allows incremental implementation, starting with high-value, low-complexity sources (leaderboards) and expanding to more sophisticated sources (on-chain) over time.

**Recommendation: Proceed with implementation, starting with Phase 1.**
