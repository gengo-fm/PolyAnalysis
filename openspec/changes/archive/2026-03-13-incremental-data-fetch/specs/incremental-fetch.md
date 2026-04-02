# Incremental Fetch Specification

## Overview
The system SHALL fetch only new data since the last fetch, reducing API calls and improving performance.

## Requirements

### REQ-INCR-001: Fetch Strategy Selection
The system SHALL automatically determine fetch strategy:
- If no cache exists → full fetch
- If cache exists and valid → incremental fetch
- If cache expired or corrupted → full fetch

#### Scenario: First-time fetch
- GIVEN no cached data exists for address
- WHEN fetch is requested
- THEN system SHALL perform full fetch and create cache

#### Scenario: Incremental fetch
- GIVEN valid cached data exists
- WHEN fetch is requested
- THEN system SHALL fetch only new records since last_fetch

### REQ-INCR-002: Activity Incremental Fetch
The system SHALL fetch activity records incrementally:
- Use `activity_latest_timestamp` from metadata as anchor
- Fetch only records with timestamp > anchor
- Merge new records with cached data
- Remove duplicates based on unique identifiers

#### Scenario: New activity records
- GIVEN cached activity with latest timestamp T1
- WHEN incremental fetch is performed
- THEN only activity records with timestamp > T1 SHALL be fetched

### REQ-INCR-003: Closed Positions Strategy
The system SHALL handle closed positions as follows:
- Always fetch full list (relatively small dataset)
- Compare with cached data to identify new closures
- Update cache with new closed positions
- Preserve historical closed positions

#### Scenario: New position closed
- GIVEN cached closed_positions
- WHEN incremental fetch is performed
- THEN new closed positions SHALL be identified and added to cache

### REQ-INCR-004: Current Positions Strategy
The system SHALL always fetch current positions fresh:
- Positions represent current state, not historical
- Always overwrite cached positions.parquet
- No incremental logic needed

#### Scenario: Position update
- GIVEN any cached data
- WHEN fetch is performed
- THEN current positions SHALL be fetched and cached positions SHALL be replaced

### REQ-INCR-005: Performance Metrics
The system SHALL track and report:
- Fetch duration (seconds)
- Records fetched (new vs cached)
- API calls made
- Cache hit rate

#### Scenario: Performance reporting
- GIVEN an incremental fetch completes
- WHEN user requests analysis
- THEN performance metrics SHALL be displayed

### REQ-INCR-006: Fallback to Full Fetch
The system SHALL fall back to full fetch when:
- Incremental fetch fails (API error)
- Data inconsistency detected
- User explicitly requests full refresh

#### Scenario: Incremental fetch failure
- GIVEN incremental fetch encounters API error
- WHEN error is detected
- THEN system SHALL fall back to full fetch
