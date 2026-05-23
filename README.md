# Stock Analysis Multi-Agent System

A production-grade multi-agent stock analysis system supporting both US/international and Chinese A-share markets, powered by LangGraph orchestration with a Next.js frontend.

## Features

- **Multi-Agent Architecture**: 7 specialized agents in a sequential pipeline
  - Data Collection (yfinance + AkShare for Chinese A-shares)
  - Technical Analysis
  - Fundamental Analysis
  - Sentiment Analysis
  - Risk Assessment
  - Decision Making
  - Report Generation

- **ReAct Agent**: An interactive ReAct agent with auto-fetching analysis tools for on-demand stock queries
- **LangGraph Orchestration**: State-based workflow with conditional retry edges and error handling
- **Enterprise Monitoring**: Real-time metrics, WebSocket event broadcasting, circuit breakers
- **Chinese A-Share Support**: Automatic AkShare data fetching when 6-digit stock codes are used
- **Next.js Frontend**: Dashboard UI for stock analysis and monitoring
- **REST API**: FastAPI-based HTTP API with async/sync analysis endpoints
- **Backtesting**: Strategy backtesting with Backtrader
- **Production Deployment**: Nginx reverse proxy, systemd service, deployment scripts included

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+ (for frontend)
- Poetry (for Python dependency management)
- PostgreSQL
- Redis (optional, for caching)

### Backend Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd stock_agents
```

2. Install Python dependencies:
```bash
poetry install
```

3. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

4. Run the backend server:
```bash
poetry run uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

The frontend will be available at `http://localhost:3000`

### Docker Deployment

```bash
docker-compose up -d
```

## API Usage

### Analyze Stocks

```bash
# Async analysis (returns workflow ID immediately)
curl -X POST "http://localhost:8000/api/analysis/analyze" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Analyze these stocks",
    "symbols": ["AAPL", "MSFT"]
  }'

# Chinese A-shares (use 6-digit codes)
curl -X POST "http://localhost:8000/api/analysis/analyze" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "分析这些股票",
    "symbols": ["600000", "000001"]
  }'

# Sync analysis (waits for completion)
curl -X POST "http://localhost:8000/api/analysis/analyze/sync" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Analyze AAPL",
    "symbols": ["AAPL"]
  }'
```

### Query Analysis History

```bash
curl "http://localhost:8000/api/history/"
```

### Run Backtest

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

### Monitoring Endpoints

- `GET /api/monitoring/health` - System health overview
- `GET /api/monitoring/metrics` - Agent execution metrics
- `GET /api/monitoring/alerts` - Alert history
- `GET /api/monitoring/circuit-breakers` - Circuit breaker status
- `WS  /api/ws/monitoring` - Real-time WebSocket event stream

## Architecture

### Agent Pipeline

```
data_collection -> technical_analysis -> sentiment_analysis -> fundamental_analysis -> risk_assessment -> decision_making -> report_generation
```

- **BaseAgent subclasses** (data, technical, fundamental): include circuit breaker, timeout, and monitoring via `agent.run()`
- **StatelessAgent subclasses** (sentiment, risk, decision, report): called via `agent.process()` with protections at the orchestrator node level

### System Overview

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
        │          │         │          │
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
| **yfinance** | US & international stocks | Always active (configurable via `YFINANCE_ENABLED`) |
| **AkShare** | Chinese A-shares | Auto-triggered for 6-digit stock codes (configurable via `AKSHARE_ENABLED`) |

### LLM Integration

Uses Zhipu AI (GLM models) as primary LLM via OpenAI-compatible API. Falls back to OpenAI if `ZHIPUAI_API_KEY` is not set.

| Model | Use Case |
|-------|----------|
| `glm-4.7` | Primary analysis (default) |
| `glm-4.5-air` | Fast / batch operations |
| `glm-4.5` | Standard tasks |

## Project Structure

```
stock_agents/
├── app/                           # Backend application
│   ├── agents/                    # Agent implementations
│   │   ├── base.py                # BaseAgent with circuit breaker
│   │   ├── data_agent.py          # yfinance data collection
│   │   ├── analysis_agent.py      # Technical + fundamental analysis
│   │   ├── sentiment_agent.py     # Sentiment analysis
│   │   ├── risk_agent.py          # Risk assessment
│   │   ├── decision_agent.py      # Decision making
│   │   └── report_agent.py        # Report generation
│   ├── react_agent/               # ReAct agent with tool use
│   ├── api/                       # FastAPI routes
│   │   └── routes/                # analysis, backtest, history, monitoring, websocket
│   ├── orchestration/             # LangGraph workflow orchestration
│   ├── monitoring/                # Metrics, WebSocket broadcast
│   ├── resilience/                # Circuit breaker, retry, timeout
│   ├── storage/                   # PostgreSQL database layer
│   ├── tools/                     # Agent tool registry
│   ├── models/                    # Data models
│   └── utils/                     # Logging, validators, helpers
├── frontend/                      # Next.js frontend dashboard
│   └── src/
│       ├── app/                   # Pages
│       ├── components/            # UI components
│       ├── hooks/                 # React hooks
│       └── lib/                   # Utilities
├── deploy/                        # Production deployment scripts
│   ├── deploy.sh                  # Automated deployment
│   ├── install-nginx.sh           # Nginx setup
│   └── nginx-full-config.conf     # Nginx configuration
├── tests/                         # Test suite
│   ├── unit/                      # Unit tests
│   ├── integration/               # Integration tests
│   └── e2e/                       # End-to-end tests
├── pyproject.toml                 # Poetry config
├── docker-compose.yml             # Docker orchestration
└── test_system.py                 # Quick validation script
```

## Configuration

Key environment variables (see `.env.example` for full list):

| Variable | Description | Default |
|----------|-------------|---------|
| `ZHIPUAI_API_KEY` | Zhipu AI API key (primary LLM) | - |
| `PRIMARY_LLM_MODEL` | LLM model for analysis | `glm-4.7` |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://...` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379` |
| `FRONTEND_URL` | Frontend URL for CORS | `http://localhost:3000` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `MAX_RETRIES` | Max retry attempts per agent | `3` |
| `TIMEOUT_PER_AGENT` | Timeout per agent (seconds) | `300` |

## Development

### Running Tests

```bash
poetry run pytest

# With coverage
poetry run pytest --cov=app tests/

# Quick validation (no pytest required)
poetry run python test_system.py
```

### Code Quality

```bash
# Format code
poetry run black app/

# Lint code
poetry run ruff check app/
```

## Production Deployment

See `deploy/` directory for automated deployment scripts:

```bash
# Deploy to server
./deploy/deploy.sh

# Install and configure Nginx
./deploy/install-nginx.sh
```

Includes Nginx reverse proxy config with API and frontend routing.

## License

MIT
