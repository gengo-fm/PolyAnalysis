# PolyAnalysis 上传方案（staged commit plan）

更新时间：2026-04-02 19:12（北京时间）

## 目标
把 PolyAnalysis 整理成一个可公开上传、结构清晰、不会夹带本地缓存/日志/隐私数据的仓库。

---

## 已处理
- 已更新 `.gitignore`
- 已忽略以下本地运行产物：
  - `data/*.json`
  - `data/*.parquet`
  - `data/cache/`
  - `polycopilot/data/`
  - `discovery.log`
  - `.claude/`
  - `.venv/`
  - `__pycache__/`
  - `.env`

---

## 上传原则

### 应上传
- 核心代码
- 测试
- README / docs
- 规格文档（如果是长期有价值的）

### 不应上传
- 真实地址报告
- parquet 数据缓存
- discovery 日志
- 本地 agent/tool 状态
- 本地环境
- 密钥与环境变量

---

## 建议仓库结构

```text
PolyAnalysis/
├── README.md
├── pyproject.toml
├── analyze.py
├── polycopilot/
│   ├── __init__.py
│   ├── fetcher.py
│   ├── processor.py
│   ├── analyzer.py
│   ├── discovery.py
│   ├── cache.py
│   └── batch.py
├── docs/
├── tests/
├── openspec/
└── .gitignore
```

---

## 提交前先检查

在仓库目录执行：

```bash
cd /Users/tkzz/.openclaw/workspace/agents/polymarket-bot/PolyAnalysis

git status --short
```

如果仍看到这些文件被跟踪，需要取消追踪：

```bash
git rm --cached -r data 2>/dev/null || true
git rm --cached discovery.log 2>/dev/null || true
git rm --cached -r .claude 2>/dev/null || true
git rm --cached -r polycopilot/data 2>/dev/null || true
```

然后再次检查：

```bash
git status --short
```

目标是：只剩代码、文档、测试、规格文件。

---

## Commit 1：核心代码

### 建议包含
```text
analyze.py
polycopilot/__init__.py
polycopilot/fetcher.py
polycopilot/processor.py
polycopilot/analyzer.py
polycopilot/discovery.py
polycopilot/cache.py
polycopilot/batch.py
pyproject.toml
```

### 命令
```bash
git add analyze.py pyproject.toml \
  polycopilot/__init__.py \
  polycopilot/fetcher.py \
  polycopilot/processor.py \
  polycopilot/analyzer.py \
  polycopilot/discovery.py \
  polycopilot/cache.py \
  polycopilot/batch.py

git commit -m "feat: add wallet analysis pipeline with cache and discovery modules"
```

---

## Commit 2：文档与说明

### 建议包含
```text
README.md
docs/
openspec/
```

### 命令
```bash
git add README.md docs openspec

git commit -m "docs: add project documentation and usage guide"
```

### 注意
如果 `docs/` 里有乱码文件名、临时稿、重复说明，建议先整理后再 add。

---

## Commit 3：测试与仓库清理

### 建议包含
```text
tests/
.gitignore
删除旧文件的变更
```

### 命令
```bash
git add tests .gitignore

git add -u

git commit -m "chore: clean repository and add test/support files"
```

`git add -u` 会把：
- 已删除的旧文件
- 已修改但未单独 add 的已跟踪文件
一起纳入这个清理 commit。

如果你想更保守，也可以先用：

```bash
git status --short
```

确认没有把不想提交的内容带进去。

---

## 最后 push

```bash
git push origin main
```

---

## 推荐最终检查

### 1. 看最近提交
```bash
git log --oneline -n 5
```

### 2. 看即将上传的文件是否干净
```bash
git ls-files | grep -E '(^data/|discovery.log|\.env|\.venv|\.claude|__pycache__)'
```

如果这条命令没有输出，说明脏文件基本没进仓库。

---

## 可选增强

如果后面你想把仓库做得更专业，可以进一步补：
- `LICENSE`
- `CONTRIBUTING.md`
- `sample_output/`（只放匿名样例，不放真实地址缓存）
- `Makefile` 或 `justfile`
- 更明确的 `docs/architecture.md`

---

## 一句话建议
先把 **代码 / 文档 / 测试** 上传，
不要把 **真实数据 / 缓存 / 日志 / 本地环境** 一起带上去。
