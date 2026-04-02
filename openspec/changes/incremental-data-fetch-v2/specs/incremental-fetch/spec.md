# Incremental Fetch Specification

## Overview

基于时间戳的增量数据获取，避免重复拉取已有数据。

## ADDED Requirements

### Requirement: Check local cache before API request

The system MUST check local file cache before making any API request to Polymarket.

#### Scenario: Cache exists and is recent
- **GIVEN** local cache file exists for address `0x123...`
- **WHEN** `fetch_with_cache("0x123...")` is called
- **THEN** the system SHALL read the cached data and use its timestamp for incremental fetch

#### Scenario: Cache does not exist
- **GIVEN** no local cache file exists for address `0x456...`
- **WHEN** `fetch_with_cache("0x456...")` is called
- **THEN** the system SHALL perform a full API fetch

### Requirement: Incremental fetch using timestamp

The system MUST support incremental fetch by passing `since` parameter to API.

#### Scenario: Incremental fetch with timestamp
- **GIVEN** cached data has last_updated = "2026-03-14T10:00:00Z"
- **WHEN** incremental fetch is triggered
- **THEN** API request SHALL include `since=2026-03-14T10:00:00Z` parameter

#### Scenario: No new data available
- **GIVEN** API returns empty result set for incremental request
- **THEN** the system SHALL use cached data directly without saving

### Requirement: Merge incremental data with cache

The system MUST merge new data with existing cache.

#### Scenario: Merge new activity records
- **GIVEN** cached has 1000 activity records, new fetch returns 50 additional records
- **WHEN** merge operation is performed
- **THEN** the resulting data SHALL contain 1050 records, sorted by timestamp

## MODIFIED Requirements

### Requirement: API rate limiting compliance

The system MUST respect API rate limits (60 requests/minute).

#### Scenario: Rate limit reached
- **GIVEN** 60 API requests have been made in the current minute
- **WHEN** another API request is attempted
- **THEN** the system SHALL wait until the next minute before proceeding

## Data Structures

### Cache Metadata
```json
{
  "address": "0x123...",
  "last_updated": "2026-03-14T10:00:00Z",
  "record_counts": {
    "positions": 10,
    "closed": 100,
    "activity": 5000
  },
  "api_version": "1.0"
}
```

### Incremental Response
```json
{
  "new_records": 50,
  "latest_timestamp": "2026-03-14T11:00:00Z",
  "data": [...]
}
```
