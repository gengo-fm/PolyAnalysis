## Why

当前系统每次分析钱包时都全量拉取所有数据（activity、closed_positions、positions），对于已分析过的钱包，这造成大量重复 API 调用和不必要的等待时间。

一个活跃钱包可能有数千条 activity 记录，全量拉取需要 15-20 秒。如果只拉取上次之后的新数据，可以将时间缩短到 5-7 秒（节省 65%+）。随着关注钱包数量增加和定时监控需求，增量获取变得必要。

## What Changes

- **新增本地缓存层**: 按钱包地址存储已获取的数据（Parquet 格式）和元数据（JSON）
- **新增增量获取逻辑**: activity 基于时间戳增量拉取，closed_positions 全量拉取后 diff，positions 每次覆盖
- **新增 CLI 入口**: 支持 `python analyze.py <address>` 一行命令分析，自动判断全量/增量
- **新增缓存管理**: 查看缓存状态、清除缓存、强制全量刷新
- **兼容现有代码**: 不破坏现有 fetcher/processor/analyzer 接口

## Capabilities

### New Capabilities
- `data-cache`: 本地数据缓存管理，包括存储、读取、过期、清除
- `incremental-fetch`: 增量数据获取逻辑，基于时间戳锚点只拉取新数据
- `cli-entry`: 命令行入口，支持地址参数、强制刷新、缓存管理等子命令

### Modified Capabilities
- `data-fetch`: 现有 PolymarketFetcher 需要新增 `fetch_incremental()` 和 `get_activity_since()` 方法

## Impact

- **代码**: `polycopilot/fetcher.py` 新增方法，新增 `polycopilot/cache.py` 模块，新增 `analyze.py` CLI 入口
- **数据**: 新增 `data/cache/<address>/` 目录结构
- **依赖**: 无新依赖（使用现有 pandas/parquet）
- **API**: 不影响 Polymarket API 调用方式，只减少调用量
