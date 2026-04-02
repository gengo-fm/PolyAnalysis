# Incremental Data Fetch - Design Document

## Architecture Overview

```
┌─────────────┐
│  analyze.py │  ← CLI Entry Point
└──────┬──────┘
       │
       ▼
┌──────────────────┐
│  CacheManager    │  ← New Module
│  - load_cache()  │
│  - save_cache()  │
│  - clear_cache() │
└────────┬─────────┘
         │
         ▼
┌──────────────────────────┐
│  PolymarketFetcher       │  ← Modified
│  + fetch_incremental()   │  ← New Method
│  + get_activity_since()  │  ← New Method
│  - fetch_all()           │  ← Existing
└────────┬─────────────────┘
         │
         ▼
┌──────────────────┐
│  TradeProcessor  │  ← Unchanged
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  WalletAnalyzer  │  ← Unchanged
└──────────────────┘
```

## Module Design

### 1. CacheManager (`polycopilot/cache.py`)

**Purpose**: Manage local data cache

**Key Classes**:
```python
@dataclass
class CacheMetadata:
    address: str
    first_fetch: str  # ISO 8601
    last_fetch: str
    activity_count: int
    activity_latest_timestamp: str
    closed_count: int
    fetch_history: list[dict]

class CacheManager:
    def __init__(self, cache_dir: Path = Path("data/cache")):
        ...
    
    def load_metadata(self, address: str) -> CacheMetadata | None:
        """Load metadata.json for address"""
    
    def save_metadata(self, address: str, meta: CacheMetadata):
        """Save metadata.json"""
    
    def load_data(self, address: str) -> dict[str, pd.DataFrame]:
        """Load all parquet files"""
    
    def save_data(self, address: str, data: dict[str, pd.DataFrame]):
        """Save all parquet files"""
    
    def clear_cache(self, address: str):
        """Delete cache directory for address"""
    
    def list_cached(self) -> list[str]:
        """List all cached addresses"""
    
    def get_stats(self, address: str) -> dict:
        """Get cache statistics"""
```

### 2. Modified PolymarketFetcher (`polycopilot/fetcher.py`)

**New Methods**:
```python
async def fetch_incremental(
    self, 
    address: str, 
    cache_manager: CacheManager
) -> dict:
    """
    Fetch data incrementally if cache exists, otherwise full fetch.
    
    Returns:
        {
            "activity": DataFrame,
            "closed_positions": DataFrame,
            "positions": DataFrame,
            "fetch_type": "full" | "incremental",
            "stats": {
                "duration_seconds": float,
                "activity_new": int,
                "activity_cached": int,
                "api_calls": int
            }
        }
    """
    meta = cache_manager.load_metadata(address)
    
    if meta is None:
        # First time: full fetch
        return await self._fetch_full_and_cache(address, cache_manager)
    
    # Incremental fetch
    return await self._fetch_incremental_and_merge(address, meta, cache_manager)

async def get_activity_since(
    self, 
    address: str, 
    since_timestamp: str
) -> list[dict]:
    """
    Fetch activity records with timestamp > since_timestamp.
    Uses existing time-based pagination logic.
    """
    # Convert since_timestamp to Unix timestamp
    since_ts = int(datetime.fromisoformat(since_timestamp).timestamp())
    
    # Use existing get_all_activity but with start filter
    # (May need to modify get_all_activity to accept start_time parameter)
    ...
```

**Implementation Strategy**:
- Reuse existing `get_all_activity()` pagination logic
- Add `start_time` parameter to filter records
- Merge new records with cached data using pandas
- Deduplicate based on unique identifiers

### 3. CLI Entry (`analyze.py`)

**Structure**:
```python
import argparse
from polycopilot.fetcher import PolymarketFetcher
from polycopilot.processor import TradeProcessor
from polycopilot.analyzer import WalletAnalyzer
from polycopilot.cache import CacheManager

def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    
    # Main analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze wallet")
    analyze_parser.add_argument("address")
    analyze_parser.add_argument("--force", action="store_true")
    analyze_parser.add_argument("--json", action="store_true")
    analyze_parser.add_argument("--quiet", action="store_true")
    analyze_parser.add_argument("--verbose", action="store_true")
    
    # Cache management
    cache_parser = subparsers.add_parser("cache", help="Manage cache")
    cache_subparsers = cache_parser.add_subparsers(dest="cache_command")
    
    cache_subparsers.add_parser("list")
    cache_subparsers.add_parser("stats")
    
    show_parser = cache_subparsers.add_parser("show")
    show_parser.add_argument("address")
    
    clear_parser = cache_subparsers.add_parser("clear")
    clear_parser.add_argument("address", nargs="?")
    clear_parser.add_argument("--all", action="store_true")
    
    args = parser.parse_args()
    
    if args.command == "analyze":
        run_analysis(args)
    elif args.command == "cache":
        manage_cache(args)

async def run_analysis(args):
    cache_mgr = CacheManager()
    fetcher = PolymarketFetcher()
    
    if args.force:
        cache_mgr.clear_cache(args.address)
    
    data = await fetcher.fetch_incremental(args.address, cache_mgr)
    
    processor = TradeProcessor(data)
    reports = processor.build_reports()
    
    analyzer = WalletAnalyzer(reports)
    analyzer.generate_report()
    analyzer.save_report(f"data/{args.address}_report.json")
    
    if args.json:
        print(json.dumps(analyzer.report, indent=2))
    else:
        print_summary(analyzer.report)
```

## Data Flow

### First-Time Fetch
```
1. User: python analyze.py 0x1234...
2. CacheManager: load_metadata() → None
3. Fetcher: fetch_all() → full data
4. CacheManager: save_data() + save_metadata()
5. Processor: build_reports()
6. Analyzer: generate_report()
```

### Incremental Fetch
```
1. User: python analyze.py 0x1234...
2. CacheManager: load_metadata() → metadata
3. Fetcher: get_activity_since(last_timestamp)
4. Fetcher: merge with cached activity
5. Fetcher: fetch closed_positions (full)
6. Fetcher: diff with cached, add new
7. Fetcher: fetch positions (overwrite)
8. CacheManager: save_data() + update_metadata()
9. Processor: build_reports()
10. Analyzer: generate_report()
```

## Performance Considerations

**Time Complexity**:
- First fetch: O(n) where n = total records
- Incremental: O(m) where m = new records since last fetch
- Typical m << n, so significant speedup

**Space Complexity**:
- Cache size: ~1-5 MB per wallet (depends on activity count)
- Parquet compression: ~10x better than JSON

**API Rate Limits**:
- Current: 5 requests/second with sleep
- Incremental reduces total requests by ~70%

## Error Handling

**Scenarios**:
1. **Cache corruption**: Detect via parquet read error → fallback to full fetch
2. **API failure**: Retry with exponential backoff (existing logic)
3. **Inconsistent data**: Validate record counts → re-fetch if mismatch
4. **Disk full**: Catch IOError → warn user, continue without cache

## Testing Strategy

**Unit Tests**:
- `test_cache_manager.py`: CRUD operations, metadata handling
- `test_incremental_fetch.py`: Merge logic, deduplication
- `test_cli.py`: Argument parsing, command routing

**Integration Tests**:
- End-to-end: First fetch → incremental → verify correctness
- Performance: Measure time savings on real wallet

## Migration Path

**Phase 1**: Add cache module, no breaking changes
**Phase 2**: Add CLI, keep existing test scripts working
**Phase 3**: Update documentation
**Phase 4**: Optional: deprecate old test scripts

## Rollback Plan

If issues arise:
1. Keep existing `fetch_all()` unchanged
2. CLI can bypass cache with `--force`
3. Delete cache directory to reset
4. No database migrations needed (file-based)
