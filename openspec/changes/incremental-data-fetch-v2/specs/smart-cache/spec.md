# Smart Cache Specification

## Overview

三层缓存架构：内存 → 文件 → API，智能选择数据来源。

## ADDED Requirements

### Requirement: Three-tier cache hierarchy

The system MUST implement a three-tier cache hierarchy.

#### Scenario: L1 memory cache hit
- **GIVEN** data was loaded in current session
- **WHEN** requesting same address
- **THEN** data SHALL be returned from memory (fastest)

#### Scenario: L2 disk cache hit
- **GIVEN** no memory cache, but disk cache exists
- **WHEN** requesting same address
- **THEN** data SHALL be loaded from disk file

#### Scenario: L3 API fetch required
- **GIVEN** no memory or disk cache exists
- **WHEN** requesting address
- **THEN** data SHALL be fetched from API and saved to disk

### Requirement: Cache validation

The system MUST validate cache integrity before use.

#### Scenario: Corrupted cache file
- **GIVEN** cache file is corrupted (invalid JSON)
- **WHEN** loading cache
- **THEN** the system SHALL treat it as cache miss and fetch from API

### Requirement: Cache expiration

The system MUST handle cache expiration appropriately.

#### Scenario: Cache older than 24 hours
- **GIVEN** cached data is older than 24 hours
- **WHEN** loading cache
- **THEN** the system SHALL trigger background refresh

## Cache File Structure

```
data/
├── 0x1234..._metadata.json
├── 0x1234..._positions.json
├── 0x1234..._closed.json
├── 0x1234..._activity.json
└── _progress.json
```

## Memory Cache Interface

```python
class MemoryCache:
    def get(self, key: str) -> Optional[Data]:
        """Get from memory cache, return None if not found"""
        
    def set(self, key: str, data: Data, ttl: int = 3600):
        """Set memory cache with TTL in seconds"""
        
    def clear(self):
        """Clear all memory cache"""
```

## Disk Cache Interface

```python
class DiskCache:
    def load(self, address: str) -> Optional[CacheData]:
        """Load from disk, return None if not found or corrupted"""
        
    def save(self, address: str, data: CacheData):
        """Save to disk with atomic write"""
        
    def exists(self, address: str) -> bool:
        """Check if cache file exists"""
```
