<div align="center">

# Stock Analysis Multi-Agent System

**A production-grade multi-agent system for stock analysis — dual architecture (LangGraph pipeline + ReAct agent), supporting both US/international and Chinese A-share markets.**

[![Live Demo](https://img.shields.io/badge/LIVE-DEMO-brightgreen?style=for-the-badge&logo=vercel)](http://101.43.97.91/stock)
[![GitHub stars](https://img.shields.io/github/stars/Bensonluo/stock_agents?style=for-the-badge)](https://github.com/Bensonluo/stock_agents/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-FF6B6B)](https://github.com/langchain-ai/langgraph)
[![Next.js](https://img.shields.io/badge/Next.js-14-black?logo=next.js&logoColor=white)](https://nextjs.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

<!-- 🎬 录制说明:录一次完整分析 AAPL 的流程,展示前端 dashboard 实时更新 -->
<img src="docs/assets/demo.gif" alt="Stock Analysis Demo" width="80%">

*🎬 Replace this with a 30s GIF of the analysis flow — see [Recording Guide](#-demo-recording-guide) below*

</div>

---

## 📌 Table of Contents

- [Why This Project](#-why-this-project)
- [Key Highlights](#-key-highlights)
- [Dual Architecture](#-dual-architecture)
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

> 🚀 **Two complementary architectures**: a deterministic 7-agent LangGraph pipeline for structured reports, plus an autonomous ReAct agent for ad-hoc queries. Built-in circuit breakers, retries, WebSocket streaming, and Chinese A-share support via AkShare.

It's a **reference implementation** for production-grade multi-agent systems — the kind of architecture you'd build for a real fintech product.

---

## ✨ Key Highlights

<div align="center">

| 🤖 Agents | 🌍 Markets | 🛡️ Resilience |
|:---:|:---:|:---:|
| **7** specialized agents | US & international | Circuit breaker |
| Sequential + ReAct dual arch | Chinese A-shares | Retry with backoff |
| Each with monitoring | Auto-detect by code | Timeout enforcement |

| 📡 Real-time | 📊 Analysis | 🧪 Backtesting |
|:---:|:---:|:---:|
| WebSocket streaming | Technical (RSI/MACD/BB) | SMA crossover |
| Live agent metrics | Fundamental (ROE/P/E/P/B) | RSI / MACD strategy |
| Circuit breaker status | Sentiment scoring | Buy & Hold baseline |

| 📈 Stats | | |
|:---:|:---:|:---:|
| **7** specialized agents | **2** architectures | **2** markets |
| **4** backtest strategies | **2** LLM providers | **WebSocket** real-time |

</div>

### 🧠 What makes it different

1. **Dual architecture, not one** — sequential pipeline for reliable reports + ReAct for autonomous exploration
2. **Native A-share support** — 6-digit codes auto-trigger AkShare data source
3. **Enterprise-grade resilience** — every agent wrapped with circuit breaker, timeout, retry
4. **Real-time observability** — WebSocket streams agent execution events live to the dashboard
5. **Multi-factor decision** — technical 30% + fundamental 40% + sentiment 15% + risk 15%

---

## 🔄 Dual Architecture

### Architecture 1: Sequential Pipeline (LangGraph)

For structured, deterministic reports — every agent runs in order:

```
data_collection
    ↓
technical_analysis   ← RSI, MACD, Bollinger Bands, K-line patterns
    ↓
fundamental_analysis ← ROE, P/E, P/B, debt ratio, profitability
    ↓
sentiment_analysis   ← News keyword scoring
    ↓
risk_assessment      ← VaR, max drawdown, position sizing
    ↓
decision_making      ← Multi-factor weighted score
    ↓
report_generation    ← Structured investment report
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
curl -X POST "http://localhost:8000/api/backtest/run" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "AAPL",
    "strategy": "sma_crossover",
    "start_date": "2023-01-01",
    "end_date": "2024-01-01"
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
│  │ Analysis   │  │ Backtest   │  │ History (PostgreSQL)│ │
│  └────────────┘  └────────────┘  └────────────────────┘  │
└─────────────────────────┬────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────┐
│               LangGraph Orchestrator                      │
│  ┌────────────────────────────────────────────────────┐  │
│  │              State Management                       │  │
│  │      (PostgreSQL Checkpoint Persistence)            │  │
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

| Source | Scope | Trigger |
|--------|-------|---------|
| **yfinance** | US & international stocks | Always active |
| **AkShare** | Chinese A-shares | Auto-triggered for 6-digit codes |

### Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ZHIPUAI_API_KEY` | Zhipu AI API key (primary LLM) | — |
| `OPENAI_API_KEY` | OpenAI API key (fallback) | — |
| `PRIMARY_LLM_MODEL` | LLM model for analysis | `glm-5.2` |
| `DATABASE_URL` | PostgreSQL connection | `postgresql://...` |
| `MAX_RETRIES` | Max retry attempts per agent | `3` |
| `TIMEOUT_PER_AGENT` | Timeout per agent (seconds) | `300` |

See `.env.example` for the full list.

---

## 📁 Project Structure

```
stock_agents/
├── app/
│   ├── agents/              # 🎯 7 specialized agents
│   │   ├── base.py          #   BaseAgent with circuit breaker
│   │   ├── data_agent.py    #   yfinance + AkShare collection
│   │   ├── analysis_agent.py#   Technical + fundamental
│   │   ├── sentiment_agent.py
│   │   ├── risk_agent.py
│   │   ├── decision_agent.py
│   │   └── report_agent.py
│   ├── react_agent/         # ReAct autonomous agent
│   ├── orchestration/       # LangGraph workflow
│   ├── api/routes/          # analysis, backtest, history, monitoring, ws
│   ├── monitoring/          # Metrics, WebSocket broadcast
│   ├── resilience/          # Circuit breaker, retry, timeout
│   ├── storage/             # PostgreSQL layer
│   └── tools/               # Agent tool registry
├── frontend/                # Next.js dashboard
├── deploy/                  # Production deployment scripts
├── tests/                   # Unit + integration + e2e
└── docker-compose.yml
```

---

## 🗺️ Roadmap

- [x] 7-agent sequential pipeline (LangGraph)
- [x] ReAct autonomous agent
- [x] Chinese A-share support (AkShare)
- [x] WebSocket real-time monitoring
- [x] Circuit breaker + retry + timeout
- [x] Strategy backtesting (4 strategies)
- [ ] Portfolio optimization agent
- [ ] Options analysis
- [ ] Multi-language reports (EN/ZH auto-switch)

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

**股票分析多智能体系统** — 双架构(顺序流水线 + ReAct 自主 Agent),支持美股和中国 A 股。

### 核心亮点

- **双架构**:LangGraph 顺序流水线(7 个专业 Agent)+ ReAct 自主 Agent
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
