# Progress Tracking Specification

## Overview

分析进度持久化，支持断点续传和失败重试。

## ADDED Requirements

### Requirement: Save progress to disk

The system MUST save analysis progress to disk after each wallet.

#### Scenario: Save progress after successful analysis
- **GIVEN** wallet `0x123...` was successfully analyzed
- **WHEN** analysis completes
- **THEN** progress.json SHALL be updated with completed count +1

#### Scenario: Save progress after failure
- **GIVEN** wallet `0x456...` analysis failed
- **WHEN** failure is detected
- **THEN** progress.json SHALL record the failure and continue to next wallet

### Requirement: Resume from last checkpoint

The system MUST resume from where it left off.

#### Scenario: Resume interrupted analysis
- **GIVEN** previous run processed 42 wallets, then was interrupted
- **WHEN** analysis is run again
- **THEN** the system SHALL start from wallet #43, skipping already completed

#### Scenario: Skip permanently failed wallets
- **GIVEN** wallet `0x789...` has failed 3 times
- **WHEN** analysis runs again
- **THEN** the system SHALL skip this wallet after 3 failures

### Requirement: Progress metadata

The system MUST track comprehensive progress information.

#### Progress.json Structure
```json
{
  "total": 1361,
  "completed": 42,
  "failed": 3,
  "skipped": 5,
  "remaining": ["0xabc...", "0xdef..."],
  "failed_wallets": {
    "0x123...": {"attempts": 3, "last_error": "API rate limit"}
  },
  "start_time": "2026-03-14T10:00:00Z",
  "last_updated": "2026-03-14T11:00:00Z"
}
```

### Requirement: Status reporting

The system MUST provide clear status updates.

#### Scenario: Report current progress
- **GIVEN** 100 wallets have been processed out of 1000
- **WHEN** status is requested
- **THEN** response SHALL show "10% complete (100/1000), ETA: 2 hours"
