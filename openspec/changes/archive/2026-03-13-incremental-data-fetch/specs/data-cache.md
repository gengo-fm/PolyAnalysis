# Data Cache Specification

## Overview
The system SHALL provide local caching of fetched Polymarket data to enable incremental updates and reduce API calls.

## Requirements

### REQ-CACHE-001: Cache Structure
The system SHALL store cached data in the following structure:
```
data/cache/
  <address>/
    metadata.json
    activity.parquet
    closed_positions.parquet
    positions.parquet
    reports/
      YYYY-MM-DD_HH-MM-SS_report.json
```

#### Scenario: First-time cache creation
- GIVEN a wallet address that has never been analyzed
- WHEN data is fetched for the first time
- THEN a cache directory SHALL be created with all data files

### REQ-CACHE-002: Metadata Storage
The system SHALL store metadata in `metadata.json` with the following fields:
- `address`: wallet address
- `first_fetch`: ISO 8601 timestamp of first fetch
- `last_fetch`: ISO 8601 timestamp of last fetch
- `activity_count`: total number of activity records
- `activity_latest_timestamp`: timestamp of most recent activity record
- `closed_count`: number of closed positions
- `fetch_history`: array of fetch events with type (full/incremental) and counts

#### Scenario: Metadata update after incremental fetch
- GIVEN existing cached data
- WHEN new data is fetched incrementally
- THEN metadata SHALL be updated with new counts and timestamps

### REQ-CACHE-003: Cache Expiry
The system MAY implement cache expiry policies:
- `closed_positions` older than 24 hours SHOULD trigger full refresh
- `positions` (current holdings) SHALL always be refreshed

#### Scenario: Expired cache detection
- GIVEN cached data older than expiry threshold
- WHEN cache is accessed
- THEN system SHALL mark it as expired and trigger refresh

### REQ-CACHE-004: Cache Management
The system SHALL provide operations to:
- List all cached addresses
- Show cache statistics (size, age, record counts)
- Clear cache for specific address
- Clear all caches
- Force full refresh (bypass cache)

#### Scenario: Clear specific cache
- GIVEN a cached wallet address
- WHEN user requests cache clear for that address
- THEN all cache files for that address SHALL be deleted

### REQ-CACHE-005: Data Integrity
The system SHALL validate cached data before use:
- Parquet files SHALL be readable
- Metadata SHALL match actual data counts
- Timestamps SHALL be valid ISO 8601 format

#### Scenario: Corrupted cache detection
- GIVEN corrupted cache files
- WHEN cache is loaded
- THEN system SHALL detect corruption and fall back to full fetch
