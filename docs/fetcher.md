# fetcher.py — 数据采集模块文档

## 模块定位

`polycopilot/fetcher.py` 是整个 PolyCopilot 系统的数据入口层，负责与 Polymarket Data API 通信，获取指定钱包地址的全量链上活动数据。后续的 processor（数据处理）、analyzer（量化分析）、scorer（跟单评分）全部依赖本模块的输出。

## 核心类

### `PolymarketFetcher`

异步上下文管理器，通过 `async with` 使用：

```python
async with PolymarketFetcher(timeout=30.0) as fetcher:
    data = await fetcher.fetch_all("0x...")
```

## API 端点与数据源

本模块对接两个 Polymarket 服务：

| 服务 | 基础 URL | 用途 |
|------|---------|------|
| Data API | `https://data-api.polymarket.com` | 交易活动、持仓、已平仓数据 |
| Gamma API | `https://gamma-api.polymarket.com` | 市场元数据（标题、分类、到期时间） |

### 端点详情

#### 1. `/activity` — 链上活动记录

**用途**：获取地址的全部链上操作，是行为分析的主数据源。

**返回的记录类型**：

| type | 含义 | side 字段 |
|------|------|----------|
| `TRADE` | 买卖交易 | `BUY` / `SELL` |
| `REDEEM` | 市场结算赎回（赢了兑现） | 空 |
| `MERGE` | 合并 Yes+No token 赎回 USDC | 空 |
| `REWARD` | 平台奖励 | 空 |

**关键字段**：

| 字段 | 类型 | 含义 |
|------|------|------|
| `size` | float | token 份数（不是 USDC 金额） |
| `usdcSize` | float | 实际花费/收到的 USDC 金额 |
| `price` | float | 成交价（0~1，即隐含概率） |
| `conditionId` | string | 市场唯一标识 |
| `outcome` | string | 押注方向（Yes/No/Republican 等） |
| `transactionHash` | string | 链上交易哈希 |
| `timestamp` | int | Unix 时间戳 |

**已知限制**：
- offset 硬上限 4000 条（超过返回 400）
- 数据不完整：对比 `closed-positions` 的 `totalBought`，activity 的 `usdcSize` 汇总约缺失 56%。原因是 API 对同一笔链上交易的多个 fill 只返回部分记录。
- **结论：activity 适合行为分析（频率、时间、价格区间），不适合金额汇总。**

#### 2. `/closed-positions` — 已平仓头寸（权威 PnL 来源）

**用途**：获取已结算市场的盈亏数据。这是 PnL 计算的唯一可信来源。

**关键字段**：

| 字段 | 类型 | 含义 |
|------|------|------|
| `totalBought` | float | 该市场总买入 USDC（链上完整数据） |
| `avgPrice` | float | 加权平均买入价 |
| `curPrice` | float | 结算价（1.0=赢, 0.0=输） |
| `realizedPnl` | float | 已实现盈亏（API 基于链上数据计算，权威值） |
| `endDate` | string | 市场到期时间 |

**已知限制**：
- 默认只返回 10 条！必须传 `limit=1000` 才能拿到全部数据。

#### 3. `/positions` — 当前持仓

**用途**：获取当前未平仓头寸。

#### 4. Gamma API `/markets` — 市场元数据

**用途**：获取市场的标题、分类、到期时间等元信息。

**已知限制**：
- 从部分网络环境不可达（IPv4 被拒绝）
- 不接受 conditionId 作为路径参数，需用查询参数 `condition_id`

## 核心方法

### `get_all_activity(address) → DataFrame`

全量拉取地址的链上活动记录。

**时间锚点分页算法**：

```
轮次 1: offset 0→4000, 拿到最老记录 ts=T1
轮次 2: end=T1, offset 0→4000, 拿到最老记录 ts=T2
轮次 3: end=T2, offset 0→4000, ...
...直到某轮返回 < 4000 条（数据拉完）
最后: 按 transactionHash+timestamp+type 三元组去重
```

**实际效果**（以 Theo4 地址为例）：
- 旧方案（纯 offset）：4,000 条
- 新方案（时间锚点）：15,926 条（5 轮，覆盖 2024-10-14 ~ 2024-11-15）

### `get_closed_positions(address) → DataFrame`

获取全部已平仓头寸。传 `limit=1000` 确保不遗漏。

### `get_positions(address) → DataFrame`

获取当前未平仓头寸。

### `get_market_details_bulk(condition_ids, concurrency=5) → DataFrame`

并发获取多个市场的 Gamma API 元数据。使用 `asyncio.Semaphore` 控制并发数。

### `fetch_all(address) → dict[str, DataFrame]`

一键并发获取三个端点的数据：

```python
{
    "activity": DataFrame,        # 全量活动记录
    "closed_positions": DataFrame, # 已平仓头寸（权威 PnL）
    "positions": DataFrame,        # 当前持仓
}
```

三个请求通过 `asyncio.gather` 并发执行。

### `save_parquet(data, address, output_dir) → dict[str, Path]`

将数据导出为 Parquet 文件，命名格式：`{地址前10位}_{数据类型}.parquet`

### `load_parquet(address, output_dir) → dict[str, DataFrame]`

从 Parquet 文件加载数据。

## 健壮性机制

### 限流

每 5 次 HTTP 请求后自动 `await asyncio.sleep(1.0)`，防止被 Cloudflare/API 封禁。

### 重试

使用 `tenacity` 库，对网络传输错误（`httpx.TransportError`）自动重试：
- 最多 5 次
- 指数退避（1s → 2s → 4s → ... → 30s）
- HTTP 4xx 错误不重试（如 400 表示 offset 超限，应优雅停止）

### 日志

使用 `loguru`，每页请求记录时间范围：

```
轮次 1 | offset=0 → 1000 条, 累计 1000 | 时间: 2024-11-15 09:56 → 2024-10-29 08:25
```

## 数据可信度总结

| 数据项 | 来源 | 可信度 | 用途 |
|--------|------|--------|------|
| PnL / 盈亏 | closed-positions.realizedPnl | ✅ 权威 | 跟单评分核心指标 |
| 总买入金额 | closed-positions.totalBought | ✅ 权威 | ROI 计算 |
| 平均买入价 | closed-positions.avgPrice | ✅ 权威 | 共识偏离度计算 |
| 结算结果 | closed-positions.curPrice | ✅ 权威 | 胜负判定 |
| 交易笔数/频率 | activity (TRADE) | ⚠️ 部分 | 行为模式分析 |
| 交易金额汇总 | activity (usdcSize) | ❌ 不完整 | 不应用于金额计算 |
| 交易时间分布 | activity (timestamp) | ✅ 可信 | 时序分析 |
| 价格区间 | activity (price) | ✅ 可信 | 入场策略分析 |

## 依赖

```
httpx        — 异步 HTTP 客户端
pandas       — DataFrame 数据结构
loguru       — 日志
tenacity     — 重试机制
pyarrow      — Parquet 读写
```
