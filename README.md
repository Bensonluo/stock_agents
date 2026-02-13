# Stock Analysis Multi-Agent System

A production-grade multi-agent system for stock market analysis powered by LangGraph orchestration.

## Features

- **Multi-Agent Architecture**: 7 specialized agents working together
  - Data Collection Agent
  - Technical Analysis Agent
  - Fundamental Analysis Agent
  - Sentiment Analysis Agent
  - Risk Assessment Agent
  - Decision Making Agent
  - Report Generation Agent

- **LangGraph Orchestration**: State-based workflow management with persistence
- **Enterprise Monitoring**: Real-time metrics, event tracking, and alerts
- **Resilience Patterns**: Retry, circuit breaker, and timeout protection
- **REST API**: FastAPI-based HTTP API
- **Backtesting**: Strategy backtesting with Backtrader

## Quick Start

### Prerequisites

- Python 3.11+
- Poetry (for dependency management)
- Docker (optional, for containerized deployment)

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd stock_agent
```

2. Install dependencies with Poetry:
```bash
poetry install
```

3. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

4. Run the application:
```bash
poetry run uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`

### Docker Deployment

```bash
docker-compose up -d
```

## API Usage

### Analyze Stocks

```bash
curl -X POST "http://localhost:8000/api/analysis/analyze" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Analyze these stocks",
    "symbols": ["AAPL", "MSFT"]
  }'
```

### Check Workflow Status

```bash
curl "http://localhost:8000/api/analysis/workflow/{thread_id}"
```

### Get Analysis Result

```bash
curl "http://localhost:8000/api/analysis/result/{thread_id}"
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

- `/api/monitoring/health` - System health overview
- `/api/monitoring/metrics` - Agent metrics
- `/api/monitoring/alerts` - Alert history
- `/api/monitoring/circuit-breakers` - Circuit breaker status

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     FastAPI API Layer                    │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                 LangGraph Orchestrator                  │
│  ┌──────────────────────────────────────────────────┐   │
│  │              State Management                      │   │
│  │      (PostgreSQL Checkpoint Persistence)          │   │
│  └──────────────────────────────────────────────────┘   │
└──────────┬──────────────────────────────────────────────┘
           │
    ┌──────┴──────┬──────────────┬──────────────┬─────────┐
    │             │              │              │         │
┌───▼────┐  ┌───▼─────┐  ┌───▼─────┐  ┌───▼─────┐ ┌───▼────┐
│  Data  │  │Analysis │  │  Risk  │  │Decision│ │ Report │
│ Agent  │  │ Agents  │  │ Agent  │  │ Agent  │ │ Agent  │
└────┬───┘  └────┬────┘  └────┬────┘  └────┬────┘ └────┬───┘
     │            │            │            │           │
     └────────────┴────────────┴────────────┴───────────┘
                          │
    ┌─────────────────────┴─────────────────────┐
    │         Monitoring & Resilience Layer      │
    │  • Metrics Collection  • Circuit Breaker   │
    │  • Alert Management    • Retry Logic        │
    │  • Event Logging       • Timeout Control    │
    └────────────────────────────────────────────┘
```

## Project Structure

```
stock_agent/
├── app/                          # Application core
│   ├── agents/                   # Agent implementations
│   ├── api/                      # FastAPI routes
│   ├── db/                       # Database layer
│   ├── models/                   # Data models
│   ├── monitoring/               # Monitoring system
│   ├── orchestration/            # LangGraph orchestration
│   ├── resilience/               # Resilience patterns
│   ├── services/                 # Business services
│   └── utils/                    # Utilities
├── deployment/                   # Deployment configs
├── tests/                        # Test suite
├── pyproject.toml                # Poetry dependencies
└── docker-compose.yml            # Docker orchestration
```

## Configuration

Key environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | postgresql://... |
| `REDIS_URL` | Redis connection string | redis://localhost:6379 |
| `OPENAI_API_KEY` | OpenAI API key (for LLM features) | - |
| `LOG_LEVEL` | Logging level | INFO |
| `MAX_RETRIES` | Max retry attempts per agent | 3 |
| `TIMEOUT_PER_AGENT` | Timeout per agent (seconds) | 300 |

## Development

### Running Tests

```bash
poetry run pytest
```

### Code Quality

```bash
# Format code
poetry run black app/

# Lint code
poetry run ruff check app/

# Type check
poetry run mypy app/
```

## Learning Focus

This project is designed to help you learn:

1. **Multi-Agent Orchestration**: Using LangGraph for complex workflows
2. **State Management**: Patterns for managing distributed state
3. **Resilience Patterns**: Retry, circuit breaker, timeout control
4. **Monitoring**: Building enterprise-grade monitoring systems
5. **Production Deployment**: Docker Compose for local development

## License

MIT
