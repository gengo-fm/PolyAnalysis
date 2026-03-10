# PolyCopilot — 项目总结文档

## 一句话概述

基于 Polymarket 链上交易数据的钱包量化分析与跟单评分系统，输入钱包地址 → 输出跟单指数 (0-100) 及等级 (S/A/B/C/D)。

## 核心价值

帮助用户判断某个 Polymarket 玩家**是否值得跟单**，通过量化其历史胜率、盈亏比、入场时机、风险偏好等维度给出综合评分。

## 技术架构

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌─────────────┐
│  Streamlit   │────▶│  Fetcher     │────▶│  Processor   │────▶│  Analyzer   │
│  (前端输入)   │     │  (数据采集)   │     │  (数据清洗)   │     │  (量化分析)  │
└─────────────┘     └──────────────┘     └──────────────┘     └──────┬──────┘
                                                                      │
                                                                      ▼
                                                               ┌─────────────┐
                                                               │   Scorer    │
                                                               │  (跟单评分)  │
                                                               └─────────────┘
```

## 四大模块

| 模块 | 文件 | 职责 |
|------|------|------|
| 数据采集 | `fetcher.py` | httpx 异步分页拉取交易记录、持仓、市场元数据 |
| 数据处理 | `processor.py` | USDC 精度处理、时间戳转换、PnL 计算、元数据关联 |
| 量化分析 | `analyzer.py` | 胜率、盈亏比、最大回撤、入场时机 Alpha、投注风格 |
| 跟单评分 | `scorer.py` | 加权算法输出 0-100 分，映射为 S/A/B/C/D 等级 |

## 技术栈

- **语言**: Python 3.10+
- **并发**: httpx + asyncio
- **数据**: Pandas + NumPy
- **API**: Polymarket Data API + Gamma API
- **前端**: Streamlit
- **可视化**: Plotly

## 工作流程

1. 用户输入 Polygon 钱包地址
2. Fetcher 异步拉取过去 6 个月（或全部）交易
3. Processor 关联 Gamma 元数据，还原每笔赌注含义
4. Analyzer 生成资产曲线 (Equity Curve) 和分类盈亏矩阵
5. Scorer 输出跟单等级 + 推荐原因 + 风险提示

## PnL 计算逻辑

```
PnL = Size × (ExitPrice - EntryPrice)
```

- 买入时 ExitPrice 为空，需关联后续 Sell 或 Redeem
- 结算 Win: 结算价 = 1.0
- 结算 Loss: 结算价 = 0.0

## 开发顺序

1. ✅ `fetcher.py` — 数据采集（当前阶段）
2. ⬜ `processor.py` — 数据清洗与 PnL 计算
3. ⬜ `analyzer.py` — 量化指标计算
4. ⬜ `scorer.py` — 跟单评分
5. ⬜ `app.py` — Streamlit 仪表盘
