# PolyCopilot — 项目总结

## 一句话概述

基于 Polymarket 链上交易数据的钱包量化分析与跟单评分系统，输入钱包地址 → 输出跟单指数 (0-100) 及等级 (S/A/B/C/D)。

## 核心价值

帮助用户判断某个 Polymarket 玩家**是否值得跟单**，通过量化其历史胜率、盈亏比、入场时机、风险偏好等维度给出综合评分。

## 技术架构

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌─────────────┐
│  测试脚本    │────▶│   Fetcher    │────▶│   Processor  │────▶│   Analyzer  │
│ (用户输入)   │     │  (数据采集)   │     │  (数据清洗)   │     │ (量化分析)  │
└─────────────┘     └──────────────┘     └──────────────┘     └─────────────┘
```

## 四大模块

| 模块 | 文件 | 职责 |
|------|------|------|
| 数据采集 | `fetcher.py` | httpx 异步分页拉取交易记录、持仓、市场元数据；高频地址预检 |
| 数据处理 | `processor.py` | USDC 精度处理、时间戳转换、PnL 计算（以 conditionId+outcome 对齐）、元数据关联 |
| 量化分析 | `analyzer.py` | Event 聚合、胜率/盈亏比/入场优势、压力测试、行为分析、跟单评分、JSON 报告 |
| 入口脚本 | `tests/test_full_analysis.py` | 串联全流程，终端输出 + 保存报告至 `data/` |

## 技术栈

- **语言**: Python 3.10+
- **并发**: httpx + asyncio
- **数据**: Pandas + NumPy + PyArrow
- **API**: Polymarket Data API + Gamma API

## 运行方式

```bash
pip install loguru tenacity httpx pandas pyarrow numpy
python tests/test_full_analysis.py
```

修改脚本顶部 `ADDR` 可切换分析地址。报告输出至 `data/{地址前10位}_report.json`。

## PnL 计算逻辑

- 权威数据来自 Polymarket `/closed-positions`（realizedPnl、totalBought、avgPrice）
- 结算 Win: 结算价 = 1.0；Loss: 结算价 = 0.0
- Entry Edge = 结算价 - 均价（衡量入场优势）

## 文档

- `docs/项目说明与报告解读.md` — 报告字段速查与项目说明
- `docs/fetcher.md` — Fetcher 模块详细说明
