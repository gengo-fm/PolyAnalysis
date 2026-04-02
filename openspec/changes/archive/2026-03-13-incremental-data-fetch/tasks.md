# Implementation Tasks

## Phase 1: Cache Module

- [ ] Create `polycopilot/cache.py` with `CacheManager` class
  - [ ] `CacheMetadata` dataclass
  - [ ] `load_metadata()` / `save_metadata()`
  - [ ] `load_data()` / `save_data()` (Parquet read/write)
  - [ ] `clear_cache()` (single address)
  - [ ] `clear_all_caches()`
  - [ ] `list_cached()` (list all cached addresses)
  - [ ] `get_stats()` (cache statistics)
  - [ ] `validate_cache()` (integrity check)

## Phase 2: Incremental Fetch

- [ ] Add `start_time` parameter to `PolymarketFetcher.get_all_activity()`
  - [ ] Filter activity records by timestamp > start_time
  - [ ] Maintain existing pagination logic
- [ ] Add `get_activity_since()` method to `PolymarketFetcher`
- [ ] Add `fetch_incremental()` method to `PolymarketFetcher`
  - [ ] Auto-detect full vs incremental based on cache state
  - [ ] Merge new activity with cached activity
  - [ ] Deduplicate records
  - [ ] Handle closed_positions diff
  - [ ] Always refresh positions
  - [ ] Track and return performance metrics
- [ ] Add fallback logic: incremental failure → full fetch

## Phase 3: CLI Entry

- [ ] Create `analyze.py` with argparse
  - [ ] `analyze <address>` command
  - [ ] `--force` flag (bypass cache)
  - [ ] `--json` flag (JSON output)
  - [ ] `--quiet` / `--verbose` flags
  - [ ] `cache list` subcommand
  - [ ] `cache show <address>` subcommand
  - [ ] `cache clear <address>` subcommand
  - [ ] `cache clear --all` subcommand
  - [ ] `cache stats` subcommand
- [ ] Progress reporting during fetch
- [ ] Error handling (invalid address, API errors)

## Phase 4: Testing

- [ ] Unit test: CacheManager CRUD operations
- [ ] Unit test: Incremental merge logic
- [ ] Integration test: Full fetch → incremental → verify data consistency
- [ ] Performance test: Compare full vs incremental fetch time

## Phase 5: Documentation

- [ ] Update README.md with CLI usage
- [ ] Add cache management documentation
- [ ] Update TOOLS.md with new commands
