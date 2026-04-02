# CLI Entry Specification

## Overview
The system SHALL provide a command-line interface for wallet analysis with cache management.

## Requirements

### REQ-CLI-001: Basic Analysis Command
The system SHALL provide `analyze.py` with the following usage:
```bash
python analyze.py <address> [options]
```

#### Scenario: Analyze wallet
- GIVEN a valid wallet address
- WHEN user runs `python analyze.py 0x1234...`
- THEN system SHALL analyze the wallet and output report

### REQ-CLI-002: Force Refresh Option
The system SHALL support `--force` flag to bypass cache:
```bash
python analyze.py <address> --force
```

#### Scenario: Force full refresh
- GIVEN cached data exists
- WHEN user runs with `--force` flag
- THEN system SHALL ignore cache and perform full fetch

### REQ-CLI-003: Cache Management Commands
The system SHALL provide cache management subcommands:
```bash
python analyze.py cache list              # List all cached addresses
python analyze.py cache show <address>    # Show cache details
python analyze.py cache clear <address>   # Clear specific cache
python analyze.py cache clear --all       # Clear all caches
python analyze.py cache stats             # Show cache statistics
```

#### Scenario: List cached addresses
- GIVEN multiple cached wallets
- WHEN user runs `cache list`
- THEN all cached addresses SHALL be displayed with metadata

### REQ-CLI-004: Output Options
The system SHALL support output format options:
- `--json`: Output report as JSON
- `--quiet`: Suppress progress messages
- `--verbose`: Show detailed fetch information

#### Scenario: JSON output
- GIVEN analysis completes
- WHEN `--json` flag is used
- THEN report SHALL be output as valid JSON

### REQ-CLI-005: Error Handling
The system SHALL handle errors gracefully:
- Invalid address format → clear error message
- API failures → retry with exponential backoff
- Cache corruption → automatic fallback to full fetch

#### Scenario: Invalid address
- GIVEN an invalid wallet address
- WHEN user runs analyze command
- THEN system SHALL display error and exit with code 1

### REQ-CLI-006: Progress Reporting
The system SHALL display progress during fetch:
- Fetching activity: X/Y records
- Fetching closed positions: X records
- Processing data...
- Generating report...

#### Scenario: Progress display
- GIVEN a fetch is in progress
- WHEN data is being fetched
- THEN progress SHALL be displayed in real-time
