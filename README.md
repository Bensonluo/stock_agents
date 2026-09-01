<div align="center">

# Stock Analysis Multi-Agent System

**A production-grade multi-agent system for stock analysis — dual execution paths, one source of truth (LangGraph pipeline + ReAct agent), evidence-constrained research synthesis, costed backtesting, supporting both US/international and Chinese A-share markets.**

[![Live Demo](https://img.shields.io/badge/LIVE-DEMO-brightgreen?style=for-the-badge&logo=vercel)](http://101.43.97.91/stock)
[![GitHub stars](https://img.shields.io/github/stars/Bensonluo/stock_agents?style=for-the-badge)](https://github.com/Bensonluo/stock_agents/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-FF6B6B)](https://github.com/langchain-ai/langgraph)
[![Next.js](https://img.shields.io/badge/Next.js-15.5-black?logo=next.js&logoColor=white)](https://nextjs.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

<!-- 🎬 录制说明:录一次完整分析 AAPL 的流程,展示前端 dashboard 实时更新 -->
<img src="docs/assets/demo.gif" alt="Stock Analysis Demo" width="80%">

*🎬 Replace this with a 30s GIF of the analysis flow — see [Recording Guide](#-demo-recording-guide) below*

</div>

---

## 📌 Table of Contents

- [Why This Project](#-why-this-project)
- [Key Highlights](#-key-highlights)
- [Dual Execution Paths](#-dual-execution-paths)
- [Quick Start](#-quick-start)
- [API Examples](#-api-examples)
- [System Architecture](#-system-architecture)
- [中文说明](#-中文说明)

---

## 💡 Why This Project

There are plenty of "LLM stock analysis" demos, but most have the same problems:

- ❌ US-only — they ignore the billion-user Chinese A-share market
- ❌ One agent does everything — slow, unreliable, no specialization
- ❌ No resilience — one API timeout kills the whole pipeline
- ❌ No real-time feedback — you wait 2 minutes staring at a spinner

This project solves all of them:

> 🚀 **Two complementary architectures sharing one set of deterministic engines**: a 8-stage LangGraph pipeline for structured reports, plus an autonomous ReAct agent for ad-hoc queries. Every number is engine-computed and traceable (unit, as-of, source, formula); the LLM only narrates and orchestrates. A Bull/Bear cross-examination, evidence auditor and risk committee gate every report before it ships.

It's a **reference implementation** for production-grade multi-agent systems — the kind of architecture you'd build for a real fintech product.

---

## ✨ Key Highlights

<div align="center">

| 🤖 Agents | 🌍 Markets | 🛡️ Resilience |
|:---:|:---:|:---:|
| **8**-stage pipeline + ReAct | US & international | Circuit breaker |
| Shared deterministic engines | Chinese A-shares | Retry with backoff |
| Each with monitoring | Auto-detect by code | Timeout enforcement |

| 📡 Real-time | 🔬 Evidence-constrained | 🧪 Backtesting |
|:---:|:---:|:---:|
| WebSocket streaming | Bull/Bear cross-exam | Next-bar fills + costs |
| Live agent metrics | Evidence auditor gate | Walk-forward + calibration |
| Circuit breaker status | Risk committee verdicts | Manifest reproducibility |

| 📈 Stats | | |
|:---:|:---:|:---:|
| **5** data providers | **282** tests green | **2** architectures |
| **4** backtest strategies | **1** shared engine per domain | **WebSocket** real-time |

</div>

### 🧠 What makes it different

1. **Evidence-constrained research, not LLM guessing** — deterministic engines compute every number as `MetricEvidence` (unit, as-of, source, formula); the LLM only narrates, and citations outside the evidence set are dropped
2. **Bull/Bear cross-examination + audit + committee** — the strongest bull and bear arguments face off with evidence refs; an auditor blocks stale/conflicting data; a risk committee issues approve/limit/veto/watch — low risk alone never justifies a buy
3. **Dual execution paths, one source of truth** — the pipeline and ReAct delegate to the same engines; parity tests pin bit-identical outputs so paths can't drift
4. **Native A-share support** — 6-digit codes auto-trigger AkShare; a 5-provider fallback chain (yfinance → Alpha Vantage → Finnhub → AkShare → Yahoo API → Stooq) keeps CN-hosted servers alive
5. **Backtesting you can trust** — signals fill at the next bar's open, commissions/slippage/stamp tax included, force-liquidation at the end, walk-forward with Wilson-bounded hit rates, and a reproducibility manifest (data hash + params + commit)

---

## 🔄 Dual Execution Paths

### Architecture 1: Sequential Pipeline (LangGraph)

For structured, deterministic reports — every agent runs in order:

```
data_collection      ← 3y history, multi-provider fallback chain
    ↓
technical_analysis   ← Daily + weekly SMA(5/10/20/40/60w) engines
    ↓
fundamental_analysis ← Scoring + quality red flags + Bear/Base/Bull valuation
    ↓
sentiment_analysis   ← Canonical lexicon scoring (+ optional LLM enrichment)
    ↓
risk_assessment      ← Beta/alpha/R², CVaR, Sortino, stress scenarios
    ↓
research_synthesis   ← Bull/Bear debate → evidence audit → risk committee
    ↓
decision_making      ← Single formula (fund 45% + tech 30% + sent 15% + risk 10%)
    ↓
report_generation    ← Versioned report + evidence index + quality gates
```

### Architecture 2: ReAct Autonomous Agent

For ad-hoc queries — the agent decides what to do:

```
Reason:   "User wants AAPL analysis. Need price + fundamentals + news."
Act:      [selects tools: get_price, get_fundamentals, get_news]
Observe:  [tool results]
Reflect:  "Have enough data. Generate report."
```

Built-in safety: max iterations, repetition detection, cost tracking, context truncation.

### When to use which?

| Use case | Architecture |
|----------|-------------|
| Daily market report (deterministic) | Sequential Pipeline |
| "Compare AAPL and MSFT" (ad-hoc) | ReAct Agent |
| Real-time alerting | Sequential + WebSocket |
| Interactive exploration | ReAct Agent |

---

## 🚀 Quick Start

### Option 1: Docker (recommended)

```bash
git clone https://github.com/Bensonluo/stock_agents.git
cd stock_agents

cp .env.example .env
# Edit .env: set ZHIPUAI_API_KEY (or OPENAI_API_KEY)

docker-compose up -d
```

- 📊 Frontend: http://localhost:3000
- 🔌 API: http://localhost:8000/docs

### Option 2: Try the Live Demo

**[Try it online →](http://101.43.97.91/stock)** — analyze real stocks in your browser.

### Option 3: Local development

```bash
# Backend
poetry install
cp .env.example .env
poetry run uvicorn app.main:app --reload

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

---

## 📡 API Examples

### Analyze stocks

```bash
# Async analysis (returns workflow ID immediately)
curl -X POST "http://localhost:8000/api/analysis/analyze" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Analyze these stocks",
    "symbols": ["AAPL", "MSFT"]
  }'

# 🇨🇳 Chinese A-shares (use 6-digit codes — AkShare auto-triggers)
curl -X POST "http://localhost:8000/api/analysis/analyze" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "分析这些股票",
    "symbols": ["600000", "000001"]
  }'

# Sync analysis (waits for completion)
curl -X POST "http://localhost:8000/api/analysis/analyze/sync" \
  -H "Content-Type: application/json" \
  -d '{"query": "Analyze AAPL", "symbols": ["AAPL"]}'
```

### Backtest a strategy

```bash
# V2 engine: next-bar fills, full costs (CN/US presets), benchmark excess,
# complete metric suite, reproducibility manifest
curl -X POST "http://localhost:8000/api/backtest/v2/run" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "AAPL",
    "strategy": "sma_crossover",
    "start_date": "2026-05-01",
    "end_date": "2026-08-27",
    "market": "us",
    "benchmark_symbol": "^GSPC",
    "strategy_params": {"sma_short": 10, "sma_long": 40}
  }'

# Rolling walk-forward: params picked on train, scored on unseen test windows,
# failures and parameter stability reported
curl -X POST "http://localhost:8000/api/backtest/v2/walkforward" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "AAPL", "strategy": "sma_crossover",
    "start_date": "2025-01-01", "end_date": "2026-08-27",
    "param_grid": {"sma_short": [5, 10], "sma_long": [30, 60]},
    "train_bars": 150, "test_bars": 60
  }'

# Signal hit-rate calibration with Wilson lower bounds
curl -X POST "http://localhost:8000/api/backtest/v2/calibrate" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "AAPL", "strategy": "sma_crossover",
    "start_date": "2025-01-01", "end_date": "2026-08-27",
    "horizons": [20, 60]
  }'

# Legacy endpoint (same engine, legacy response shape)
curl -X POST "http://localhost:8000/api/backtest/run" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "AAPL",
    "strategy": "sma_crossover",
    "start_date": "2026-05-01",
    "end_date": "2026-08-27"
  }'
```

### Real-time monitoring

| Endpoint | Purpose |
|----------|---------|
| `GET /api/monitoring/health` | System health overview |
| `GET /api/monitoring/metrics` | Agent execution metrics |
| `GET /api/monitoring/alerts` | Alert history |
| `GET /api/monitoring/circuit-breakers` | Circuit breaker status |
| `WS  /api/ws/monitoring` | Real-time event stream |

---

## 🏗️ System Architecture

```
┌──────────────────────────────────────────────────────────┐
│                  Next.js Frontend (:3000)                │
└─────────────────────────┬────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────┐
│                    Nginx Reverse Proxy                    │
└─────────────────────────┬────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────┐
│                   FastAPI API (:8000)                     │
│  ┌────────────┐  ┌────────────┐  ┌────────────────────┐  │
│  │ Analysis   │  │ Backtest   │  │  History (SQLite)  │  │
│  └────────────┘  └────────────┘  └────────────────────┘  │
└─────────────────────────┬────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────┐
│               LangGraph Orchestrator                      │
│  ┌────────────────────────────────────────────────────┐  │
│  │              State Management                       │  │
│  │   (In-memory checkpoints; durable history in SQLite)│  │
│  └────────────────────────────────────────────────────┘  │
└───────┬──────────┬──────────┬──────────┬────────────────┘
        │          │          │          │
   ┌────▼───┐ ┌───▼────┐ ┌──▼───┐ ┌───▼──────┐
   │  Data  │ │Analysis│ │ Risk │ │ Decision │
   │ Agent  │ │ Agents │ │Agent │ │  + Report│
   └────┬───┘ └───┬────┘ └──┬───┘ └────┬─────┘
        └──────────┴─────────┴──────────┘
                       │
    ┌──────────────────▼──────────────────┐
    │      Monitoring & Resilience        │
    │  • Metrics   • Circuit Breaker      │
    │  • Alerts    • Retry / Timeout      │
    │  • WebSocket Broadcast              │
    └─────────────────────────────────────┘
```

### Data Sources

| Source | Scope | Notes |
|--------|-------|-------|
| **yfinance** | US & international | Primary |
| **Alpha Vantage** | Global | Free tier 25 req/day, 100-day history; snapshot + historical |
| **Finnhub** | US snapshots | Needs `FINNHUB_API_KEY` |
| **AkShare** | Chinese A-shares | Auto-triggered for 6-digit codes |
| **Yahoo chart API / Stooq** | Global | Last-resort fallbacks |

Providers chain automatically on failure; statements become visible only
after a reporting lag (point-in-time), and `as_of` gates every metric.

### Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ZHIPUAI_API_KEY` | Zhipu AI API key (primary LLM) | — |
| `OPENAI_API_KEY` | OpenAI API key (fallback) | — |
| `PRIMARY_LLM_MODEL` | LLM model for analysis | `glm-5.3-flash` |
| `DATABASE_URL` | Optional PostgreSQL checkpoint-manager connection | `postgresql://...` |
| `MAX_RETRIES` | Max retry attempts per agent | `3` |
| `TIMEOUT_PER_AGENT` | Timeout per agent (seconds) | `300` |

See `.env.example` for the full list.

---

## 📁 Project Structure

```
stock_agents/
├── app/
│   ├── domain/schemas/      # 📐 MetricEvidence, DataQuality, ReportV2 contracts
│   ├── analysis/            # ⚙️ Deterministic engines (single source of truth)
│   │   ├── technical/       #   Daily + weekly SMA engines
│   │   ├── fundamental/     #   Scoring + quality/red flags
│   │   ├── valuation/       #   Bear/Base/Bull scenarios + sensitivity
│   │   ├── risk/            #   Beta/CVaR/Sortino/stress/correlation
│   │   └── sentiment.py     #   Canonical lexicon scoring
│   ├── research/            # 🔬 Bull/Bear debate, auditor, committee,
│   │                        #   narrator + analyst panel (evidence-bound)
│   ├── backtest/            # 🧪 V2 engine: costs, walk-forward,
│   │                        #   calibration, point-in-time, manifest
│   ├── agents/              # 🎯 Pipeline agents (thin delegates)
│   ├── react_agent/         # ReAct autonomous agent
│   ├── services/            # ReportService, BacktestService
│   ├── orchestration/       # LangGraph workflow (+ synthesis node)
│   ├── api/routes/          # analysis, backtest v2, history, monitoring, ws
│   ├── monitoring/          # Metrics, WebSocket broadcast
│   ├── resilience/          # Circuit breaker, retry, timeout
│   ├── storage/             # SQLite analysis-history layer
│   └── tools/               # Agent tool registry (wrappers over engines)
├── frontend/                # Next.js dashboard
├── deploy/                  # Production deployment scripts
├── tests/                   # 292 tests: unit + integration + path parity
└── docker-compose.yml
```

---

## 🗺️ Roadmap

- [x] 7-agent sequential pipeline (LangGraph) + research synthesis stage
- [x] ReAct autonomous agent (evidence-constrained tools)
- [x] Chinese A-share support (AkShare + 5-provider fallback chain)
- [x] WebSocket real-time monitoring
- [x] Circuit breaker + retry + timeout
- [x] Strategy backtesting (4 strategies, V2 costed engine)
- [x] Deterministic engines with MetricEvidence traceability
- [x] Bull/Bear debate + evidence auditor + risk committee
- [x] Walk-forward evaluation + signal calibration
- [x] Pipeline/ReAct parity tests (bit-identical outputs)
- [ ] Phase 4: filings RAG, expectations data, options-implied signals
- [ ] Portfolio optimization agent
- [ ] Multi-language reports (EN/ZH auto-switch)

---

## 🧪 Testing

```bash
poetry run pytest tests/ -q          # 292 passed (5 network tests deselected)
```

Coverage highlights: every engine has golden-value tests; pipeline/ReAct
**parity tests** assert bit-identical outputs for fundamental, risk,
sentiment and the decision formula; functional tests run the full
seven-agent sequence and the backtest API through the real engine;
point-in-time and no-look-ahead rules are pinned by dedicated suites.

---

## ⚠️ Disclaimer

This project is for **educational and research purposes only**. Not financial advice. Always do your own research before making investment decisions.

---

## 🤝 Contributing

PRs welcome — especially:
- 🌍 New data sources (European markets, crypto, etc.)
- 🤖 New agent types (portfolio optimizer, options analyst)
- 📊 New technical indicators
- 🐛 Bug fixes with a failing test

---

## 📜 License

[MIT](LICENSE) — free for personal and commercial use.

If this project helped you learn multi-agent systems, please ⭐ star the repo.

---

## 📬 Contact

- 💼 **Portfolio**: [benluo.art](https://benluo.art)
- 🐙 **GitHub**: [@Bensonluo](https://github.com/Bensonluo)
- 💬 **Issues**: [GitHub Issues](https://github.com/Bensonluo/stock_agents/issues)

---

## 🇨🇳 中文说明

**股票分析多智能体系统** — 双执行路径(顺序流水线 + ReAct 自主 Agent)共享单一事实源,支持美股和中国 A 股。

### 核心亮点

- **双执行路径·单一事实源**:LangGraph 顺序流水线 + ReAct 自主 Agent,共享同一组确定性引擎
- **7 个专业 Agent**:数据采集、技术分析、基本面分析、舆情分析、风险评估、决策制定、报告生成
- **A 股支持**:6 位股票代码自动触发 AkShare 数据源
- **企业级容错**:每个 Agent 都有熔断器、超时、重试
- **WebSocket 实时监控**:Agent 执行事件实时推送到前端
- **策略回测**:SMA 交叉、RSI、MACD、Buy & Hold 四种策略
- **多因子决策**:技术面 30% + 基本面 40% + 舆情 15% + 风控 15%

### 快速开始

```bash
git clone https://github.com/Bensonluo/stock_agents.git
cd stock_agents
cp .env.example .env  # 填入 ZHIPUAI_API_KEY
docker-compose up -d
# 前端:http://localhost:3000  API:http://localhost:8000/docs
```

> ⚠️ **免责声明**:本项目仅供学习和研究,不构成任何投资建议。

---

<details>
<summary>🎬 Demo Recording Guide (for maintainers)</summary>

### How to record the hero GIF

1. **Tool**: [Kap](https://getkap.co/) (Mac) or [licecap](https://www.cockos.com/licecap/)
2. **Content** (~30s):
   - 0-5s: Open dashboard, enter "AAPL" in the search box
   - 5-15s: Click Analyze, show WebSocket events streaming in real-time
   - 15-25s: Show the final report with technical/fundamental/sentiment sections
   - 25-30s: Switch to A-share example (e.g., "600000") to showcase dual-market support
3. **Save to**: `docs/assets/demo.gif` (keep under 5MB)

</details>

<!--
RECORDING_TODO:
1. Record demo.gif → docs/assets/demo.gif
2. Replace placeholder img tag in hero section
3. Consider moving Live Demo to benluo.art subdomain for HTTPS
-->
