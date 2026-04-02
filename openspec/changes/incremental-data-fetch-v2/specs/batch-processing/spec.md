# Batch Processing Specification

## Overview

批量并发处理，提升整体效率。

## ADDED Requirements

### Requirement: Concurrent processing

The system MUST process multiple wallets concurrently.

#### Scenario: Process 20 wallets concurrently
- **GIVEN** a queue of 100 wallets to analyze
- **WHEN** batch processing starts
- **THEN** the system SHALL process up to 20 wallets in parallel

### Requirement: Smart rate limiting

The system MUST respect API rate limits across concurrent requests.

#### Scenario: Rate limit approach
- **GIVEN** 20 concurrent requests are running
- **WHEN** rate limit is approached (50 requests/minute)
- **THEN** the system SHALL pause before sending more requests

### Requirement: Failure handling

The system MUST handle individual failures without stopping the batch.

#### Scenario: One wallet fails
- **GIVEN** 20 wallets are processing concurrently, one fails with API error
- **WHEN** failure occurs
- **THEN** the system SHALL log the error, skip this wallet, and continue processing the remaining 19

#### Scenario: All retries exhausted
- **GIVEN** a wallet has failed 3 times
- **WHEN** all retries are exhausted
- **THEN** the system SHALL mark it as permanently failed and move to next

### Requirement: Batch statistics

The system MUST provide batch processing statistics.

#### Scenario: Report batch statistics
- **GIVEN** a batch of 100 wallets was processed
- **WHEN** batch completes
- **THEN** the system SHALL report:
  - Total processed: 100
  - Successful: 85
  - Failed: 10
  - Skipped: 5
  - Total time: 45 minutes

## Configuration

```python
class BatchConfig:
    max_concurrent: int = 20          # Maximum concurrent requests
    rate_limit_per_minute: int = 50   # API rate limit
    retry_attempts: int = 3           # Retry failed requests
    retry_delay_seconds: int = 10     # Delay between retries
    progress_interval: int = 10        # Save progress every N wallets
```

## Parallel Processing Flow

```
[Wallet Queue]
      │
      ▼
[Semaphore: 20 concurrent]
      │
      ├──────▶ [Wallet 1] ──▶ Save ──▶ Done
      ├──────▶ [Wallet 2] ──▶ Save ──▶ Done
      ├──────▶ [Wallet 3] ──▶ Retry ──▶ Done/Fail
      ...
      │
      ▼
[Progress Update]
      │
      ▼
[Save to disk]
```
