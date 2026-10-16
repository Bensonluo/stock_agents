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

> 🚀 **Two complementary architectures sharing one set of deterministic engines**: an 8-stage LangGraph pipeline for structured reports, plus an autonomous ReAct agent for ad-hoc queries. Every number is engine-computed and traceable (unit, as-of, source, formula); the LLM only narrates and orchestrates. A Bull/Bear cross-examination, evidence auditor and risk committee gate every report before it ships.

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
| **10** data sources | **1456** tests green | **2** architectures |
| **5** backtest strategies | **1** shared engine per domain | **WebSocket** real-time |

</div>

### 🧠 What makes it different

1. **Evidence-constrained research, not LLM guessing** — deterministic engines compute every number as `MetricEvidence` (unit, as-of, source, formula); the LLM only narrates, and citations outside the evidence set are dropped
2. **Bull/Bear cross-examination + audit + committee** — the strongest bull and bear arguments face off with evidence refs; an auditor blocks stale/conflicting data; a risk committee issues approve/limit/veto/watch — low risk alone never justifies a buy
3. **Dual execution paths, one source of truth** — the pipeline and ReAct delegate to the same engines; parity tests pin bit-identical outputs so paths can't drift
4. **Native A-share support with CN-host fallbacks** — 6-digit codes auto-trigger AkShare; a multi-provider fallback chain (yfinance → Finnhub → Alpha Vantage → AkShare/Sina → Yahoo API → Stooq) keeps CN-hosted servers alive, Tencent kline/quote endpoints backstop the A-share daily bars, the spot table and both market benchmarks when East Money is domain-blocked or Yahoo is rate-limited, US sector-ETF benchmarks keep a Sina SPDR-history third leg for sector-relative regressions when Yahoo is dark, capped responses (AV free tier's 100-day slice) fall through instead of shadowing multi-year sources, and when core market data is missing entirely the decision layer withholds the directional call (hold at zero conviction instead of a guess)
5. **Measured self-assessment, not self-congratulation** — historical recommendations are replayed against realized forward returns: rank IC / ICIR with Newey-West t-statistics (overlapping forward windows) and decay curves, regime-conditional IC buckets, top-k portfolio replay against the equal-weight cross-section, confidence calibration (Brier score + reliability curve), walk-forward results priced with the Deflated Sharpe Ratio and a Monte Carlo random-entry null benchmark; measured IC feeds back into the decision blend (vintage-stamped so evidence never crosses formula versions); an opt-in daily watchlist run (`DAILY_RUN_*`, exactly-once per day) feeds this evidence base without hand-triggering
6. **Backtesting you can trust** — signals fill at the next bar's open, commissions/slippage/stamp tax included, force-liquidation at the end, walk-forward with Wilson-bounded hit rates, and a reproducibility manifest (data hash + params + commit); the `technical_score` strategy replays the live decision formula's technical dimension bar-by-bar, so the engine prices what the agent actually recommends
7. **Market-level option-implied annotation, fenced from scoring** — every CN run attaches one SSE options snapshot (official per-contract IV surface → ATM IV per expiry, term structure, 25-delta skew, plus the official put/call ratio) and the QVIX one-year percentile maps to a 恐慌/中性/自满 market-regime label; both the pipeline and ReAct reports render the block, and it is annotation-only by construction — risk scores, weights, position sizing and decisions never read it (`OPTION_SIGNALS_ENABLED` toggles the whole layer)
8. **Per-symbol analyst-consensus annotation for A-shares** — THS annual EPS forecasts (nearest + next year, implied growth over a positive base) and Sina institute ratings (target-price mean/median gated at ≥3 observations inside a 180-day window, rating counts with a bullish tie-break, implied upside against the live price) attach under `financial_data[symbol]["consensus"]` on every 6-digit run, both pipeline and ReAct; raw frames cache price-independent so upside recomputes per call, and the block is annotation-only — the fundamental score never reads it (`CONSENSUS_ENABLED` toggles the whole layer)
9. **Multi-period fundamental trend annotation** — CN runs carry the full Sina indicator history and US/HK runs the three quarterly statements from the same ticker session; the analysis seam emits a per-symbol trend block (CN: the latest report period vs the same period a year earlier — the only honest comparison for YTD-cumulative rows; US/HK: a 4-quarter revenue/net-income QoQ series), both pipeline and ReAct render it, and it is annotation-only — no score, weight or decision reads it (`TREND_DEPTH_ENABLED` toggles the layer)

---

## 🔄 Dual Execution Paths

### Architecture 1: Sequential Pipeline (LangGraph)

For structured, deterministic reports — two map-reduce fan-outs: the three
analysis agents run as a parallel superstep behind an explicit join barrier,
and after risk the research-synthesis and decision branches run concurrently
(report generation is the fan-in); pipeline-critical nodes stay sequential:

```
data_collection      ← 3y history, multi-provider fallback chain
    ↓
[ technical_analysis | fundamental_analysis | sentiment_analysis ]
      technical: Daily + weekly SMA(5/10/20/40/60w) engines
      fundamental: Scoring + quality red flags + Bear/Base/Bull valuation
      sentiment: Canonical lexicon scoring (+ optional LLM enrichment)
      ↑ first fan-out — one parallel superstep behind an explicit join barrier
    ↓
risk_assessment      ← Beta/alpha/R², CVaR, Sortino, stress scenarios
                       (+ option-implied annotation block on CN runs)
    ↓
[ research_synthesis | decision_making ]
      synthesis: Bull/Bear debate → evidence audit → risk committee
      decision: Composite formula (fund 45% + tech 30% + sent 15% + risk 10%;
                weights adapt toward measured IC when evidence gates pass)
      ↑ second fan-out — both run concurrently; report_generation fans in
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

- 📊 Frontend: http://localhost:3002/stock (compose maps the container to host port 3002; the app is served under the `/stock` base path)
- 🔌 API: http://localhost:8001/docs

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

# Signal quality of PAST recommendations — rank IC / ICIR against realized
# forward returns (also: /ic/decay for half-life, /ic/calibration for Brier,
# /ic/regime for market-regime buckets, /portfolio for top-k portfolio replay)
curl "http://localhost:8000/api/history/ic?horizon_bars=20"
```

### Real-time monitoring

| Endpoint | Purpose |
|----------|---------|
| `GET /api/monitoring/health` | System health overview |
| `GET /api/monitoring/metrics` | Agent execution metrics |
| `GET /api/monitoring/alerts` | Alert history |
| `GET /api/monitoring/circuit-breakers` | Circuit breaker status |
| `GET /api/monitoring/data-sources` | Per-provider ok/fail/fallback counters for the data chain's fallback seams (in-process state, resets on restart) |
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
| **yfinance** | US & international | Primary (rate-limited from CN hosts) |
| **Finnhub** | US snapshots + news | Needs `FINNHUB_API_KEY`; free tier 60 req/min |
| **Alpha Vantage** | Global | Free tier 25 req/day, ~100-day history; a coverage gate makes thin responses fall through to deeper sources |
| **AkShare** | Chinese A-shares + HK | Auto-triggered for 6-digit codes; East Money + industry benchmarks + native CN news |
| **Tencent** | A-share daily bars + spot table, dual-market benchmarks | CN-host-verifiable fallback (`qt.gtimg.cn` quotes, ifzq kline) when East Money is domain-blocked or Yahoo is rate-limited |
| **Sina** | US history + sector-ETF benchmarks | CN-host-viable US daily bars (`stock_us_daily`); third leg for SPDR sector-ETF benchmark history when Yahoo is dark |
| **Yahoo chart API / Stooq** | Global | Last-resort fallbacks |
| **SSE options + QVIX** | CN market-level options signals | Official SSE per-contract IV + official PCR (via AkShare) and the QVIX index (third-party host, mirrored to a local SQLite store so outages serve the last known closes); annotation-only — never feeds scores or decisions |
| **THS forecasts + Sina ratings** | CN analyst consensus | THS annual EPS consensus + Sina institute detail (target prices, ratings) via AkShare; per-symbol annotation under `financial_data["consensus"]` — never feeds scores or decisions |

Providers chain automatically on failure, and every fallback seam records
its outcome (ok / fail / fallback) into in-process provider-health counters
exposed at `GET /api/monitoring/data-sources` and on the frontend monitoring
page — provider outages are visible without log archaeology. Statements
become visible only after a reporting lag (point-in-time), and `as_of` gates
every metric.

### Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ZHIPUAI_API_KEY` | Zhipu AI API key (primary LLM) | — |
| `OPENAI_API_KEY` | OpenAI API key (fallback) | — |
| `PRIMARY_LLM_MODEL` | LLM model for analysis | `glm-5.3-flash` |
| `DATABASE_URL` | Optional PostgreSQL checkpoint-manager connection | `postgresql://...` |
| `MAX_RETRIES` | Max retry attempts per agent | `3` |
| `TIMEOUT_PER_AGENT` | Timeout per agent (seconds) | `300` |
| `REACT_TOOL_TIMEOUT` | Per-tool-invocation wall clock in the ReAct loop — a hung upstream call never raises; this bound keeps the loop (and its analysis-capacity slot) from stalling forever. 0 disables | `120` |
| `REACT_RUN_TIMEOUT` | Overall wall clock for one ReAct run — the worst-case bounded run (capped iterations × bounded tools) still holds a capacity slot for tens of minutes without it. 0 disables | `900` |
| `PIPELINE_RUN_TIMEOUT` | Overall wall clock for one pipeline run — the pipeline twin of the knob above (nodes × per-node budget × retries is still tens of minutes). 0 disables | `1800` |
| `LLM_TIMEOUT` | HTTP ceiling for every LLM client; research budgets (narrator 45s / panel 90s) stay at or below it | `90` |
| `OPTION_SIGNALS_ENABLED` | CN option-implied annotation layer — SSE options trio + QVIX market-regime label; pure annotation, no scoring reads it | `true` |
| `CONSENSUS_ENABLED` | CN analyst-consensus annotation layer — THS EPS forecasts + Sina target prices/ratings per symbol; pure annotation, no scoring reads it | `true` |
| `TREND_DEPTH_ENABLED` | Fundamental trend annotation layer — CN full Sina indicator history (same-period YoY) + US/HK quarterly statements (4-quarter QoQ); pure annotation, no scoring reads it | `true` |
| `RATE_LIMIT_ENABLED` | Per-client sliding-window rate limit on the expensive POSTs (analyze/agent analyze, backtest; GETs unlimited). 10 analysis / 30 backtest per 10 min, tunable via `RATE_LIMIT_*` | `true` |
| `MAX_CONCURRENT_ANALYSES` | Global cap on concurrently running analysis workflows — 503 when the server is at capacity (the rate limiter bounds one client; this bounds the server total). 0 disables | `2` |
| `MAX_SYMBOLS_PER_REQUEST` | Cap on symbols per analyze request (pipeline + ReAct) — request size is the input axis neither the rate limiter nor the capacity gate bounds. 0 disables | `10` |
| `DAILY_RUN_ENABLED` | Opt-in daily watchlist analysis scheduler | `false` |
| `DAILY_RUN_SYMBOLS` | Comma-separated watchlist for the daily run (cross-sector CN default; IC views need ≥3 scored symbols per run) | `600519,600036,601088,600276,002415,600887` |
| `DAILY_RUN_TIME` | Daily-run trigger time, server local `HH:MM` | `16:00` |

The daily run executes one analysis workflow per calendar day over the
configured watchlist, persisted to analysis history exactly like a manual
run (thread_id `daily-YYYYMMDD` makes it exactly-once and restart-safe; a
same-day restart catches up a missed trigger). Its records feed the same
IC / calibration replay as manual runs — the evidence base fills itself.

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
├── scripts/                 # smoke_data_chain.py — post-deploy data-chain probe
├── tests/                   # 1456 tests: unit + integration + path parity
└── docker-compose.yml
```

---

## 🗺️ Roadmap

- [x] 7-agent sequential pipeline (LangGraph) + research synthesis stage
- [x] ReAct autonomous agent (evidence-constrained tools)
- [x] Chinese A-share support (AkShare + 5-provider fallback chain)
- [x] WebSocket real-time monitoring
- [x] Circuit breaker + retry + timeout
- [x] Strategy backtesting (5 strategies, V2 costed engine)
- [x] Deterministic engines with MetricEvidence traceability
- [x] Bull/Bear debate + evidence auditor + risk committee
- [x] Walk-forward evaluation + signal calibration
- [x] Deflated Sharpe Ratio + Monte Carlo random-entry null benchmark
- [x] Signal quality: rank IC / ICIR / decay curves + confidence calibration (Brier)
- [x] IC-adaptive decision weights with formula-vintage stamping
- [x] `technical_score` strategy — backtest what the agent actually recommends
- [x] Pipeline/ReAct parity tests (bit-identical outputs)
- [x] Parallel-analysis join barrier — straggler retries no longer re-run downstream
- [x] Data-source resilience: Tencent fallbacks for A-share daily bars, spot table and dual-market benchmarks
- [x] Provider health observability: in-process ok/fail/fallback counters + `GET /api/monitoring/data-sources` + frontend panel
- [x] Decision gate: hold at zero conviction when core market data is missing — no directional call
- [x] Opt-in daily watchlist auto-run feeding the IC evidence base (exactly-once per day, restart-safe)
- [x] Post-deploy data-chain smoke script (`scripts/smoke_data_chain.py`)
- [x] Sector-ETF benchmark third leg — Sina SPDR history when Yahoo is dark
- [x] Newey-West HAC t-statistics for overlapping forward-window IC
- [x] Regime-conditional IC and top-k portfolio replay over past recommendations
- [x] Agent resilience panel — circuit breakers, retry/timeout stats on the monitoring page
- [x] Result fallback to SQLite history — reports readable after a backend restart
- [x] Market-level option-implied annotation — SSE options trio + QVIX regime label (annotation-only, fenced from scoring)
- [x] Per-symbol CN analyst-consensus annotation — THS EPS forecasts + Sina target prices/ratings (annotation-only, fenced from scoring)
- [x] API rate limiting — per-client sliding window on the expensive POST endpoints (429 + Retry-After)
- [x] Analysis concurrency cap — global in-flight limit on workflows (503 + Retry-After when the server is at capacity)
- [x] Symbols-per-request cap — 422 when a request exceeds MAX_SYMBOLS_PER_REQUEST (pipeline + ReAct; client guard mirrors it)
- [x] ReAct tool-invocation timeout — a hung tool call degrades to a ToolTimeout error instead of stalling the loop and its capacity slot forever
- [x] ReAct overall run timeout — worst-case bounded runs (900s) release the capacity slot instead of holding it for tens of minutes
- [x] Pipeline overall run timeout — the pipeline twin (1800s); both architectures now have end-to-end wall-clock bounds
- [ ] Phase 4: filings RAG, expectations data
- [ ] Portfolio optimization agent
- [ ] Multi-language reports (EN/ZH auto-switch)

---

## 🧪 Testing

```bash
poetry run pytest tests/ -q          # 1456 passed (4 network tests deselected)
```

Coverage highlights: every engine has golden-value tests; pipeline/ReAct
**parity tests** assert bit-identical outputs for fundamental, risk,
sentiment and the decision formula; functional tests run the full
seven-agent sequence and the backtest API through the real engine;
point-in-time and no-look-ahead rules are pinned by dedicated suites.

The frontend carries its own vitest net (`npm test` in `frontend/`):
pure-logic pins for the formatting / verdict / form-parse helpers plus
component and interaction tests for the signal-quality card and the
backtest form.

Post-deploy, the data chain is verified in the production container —
each check is an independent PASS/FAIL/SKIP line (A-share Tencent
fallbacks and the sector-ETF benchmark chain included), and `--full`
adds an end-to-end analysis plus a provider-health check:

```bash
ssh <host> "docker exec -i stock_agent_api python -" < scripts/smoke_data_chain.py
```

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

- **双执行路径·单一事实源**:LangGraph 流水线(两级 map-reduce 扇出:三个分析 Agent 并行 superstep,风险后研究合成与决策并行,报告汇合)+ ReAct 自主 Agent,共享同一组确定性引擎
- **8 阶段流水线**:数据采集、技术/基本面/舆情分析(并行)、风险评估、研究合成(多空辩论→证据审计→风险委员会)与决策(并行)、报告
- **A 股支持**:6 位股票代码自动触发 AkShare 数据源(原生 CN 新闻 + 行业基准)
- **数据源韧性**:东财 push2his 域名封禁、Yahoo 限流时,腾讯接口自动兜底(A 股日K、全市场快照表、双市场基准指数),美股行业基准在 Yahoo 不可用时由新浪 SPDR 历史兜底;每个 fallback 接缝的 ok/fail/fallback 计数经 `GET /api/monitoring/data-sources` 暴露并在前端监控页展示;核心行情缺失时决策层不发方向性建议(hold、置信 0)
- **期权隐含标注层**:CN 运行附加一份 SSE 官方期权快照(逐合约 IV → ATM IV/期限结构/25-delta 偏度,官方 PCR)+ QVIX 一年分位 → 恐慌/中性/自满 市场状态标签;流水线与 ReAct 报告均渲染;纯标注——评分/权重/仓位/决策一律不读取,`OPTION_SIGNALS_ENABLED` 可整体关闭
- **分析师一致预期标注层**:A 股逐标的附加同花顺年度 EPS 预测(近两年 + 隐含增速)+ 新浪机构评级明细(180 天窗口内 ≥3 家目标价均值/中位数、评级计数、对现价隐含上行);原始帧缓存与价格解耦、上行空间每次按现价重算;流水线与 ReAct 报告均渲染;纯标注——基本面评分一律不读取,`CONSENSUS_ENABLED` 可整体关闭
- **基本面趋势标注层**:CN 挂全量新浪指标历史、US/HK 挂同一 ticker 会话的三份季报;分析层逐标的发趋势块(CN:最新财期对比同期上年——YTD 累计行唯一诚实的口径;US/HK:近四季营收/净利环比序列),流水线与 ReAct 报告均渲染;纯标注——评分一律不读取,`TREND_DEPTH_ENABLED` 可整体关闭
- **API 限流与并发闸门**:昂贵 POST 端点(分析/回测)按客户端 IP 滑动窗口限流(429 + Retry-After),GET 只读端点不限;全服务器并发分析工作流数有全局上限(满载 503),单次请求的股票代码数也有上限(超限 422),多客户端叠加也不烧穿 LLM 配额;`RATE_LIMIT_ENABLED` / `MAX_CONCURRENT_ANALYSES` / `MAX_SYMBOLS_PER_REQUEST` 可调
- **企业级容错**:每个 Agent 都有熔断器、超时、重试
- **WebSocket 实时监控**:Agent 执行事件实时推送到前端;监控页含韧性面板(熔断器、重试/超时统计)
- **策略回测**:SMA、RSI、MACD、Buy & Hold,以及 `technical_score`——逐 bar 重放决策公式技术维度;walk-forward 选参带 Deflated Sharpe 与随机入场零假设基准
- **信号质量度量**:历史推荐对账已实现收益——秩 IC/ICIR(Newey-West t 统计)/衰减曲线、按市场状态分桶 IC、top-k 组合重放、置信度校准(Brier),测得的 IC 自适应反馈进决策权重(带公式版本戳);opt-in 每日自选股例行跑(默认关,每天恰好一次、重启安全)自动为这条证据库喂料
- **多因子决策**:基本面 45% + 技术面 30% + 舆情 15% + 风控 10%(静态先验,证据充足时向实测 IC 自适应)

### 快速开始

```bash
git clone https://github.com/Bensonluo/stock_agents.git
cd stock_agents
cp .env.example .env  # 填入 ZHIPUAI_API_KEY
docker-compose up -d
# 前端:http://localhost:3002/stock  API:http://localhost:8001/docs
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
