# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A multi-agent stock analysis system using LangGraph sequential workflow orchestration. Agents run in a fixed pipeline: data_collection -> technical_analysis -> sentiment_analysis -> fundamental_analysis -> risk_assessment -> decision_making -> report_generation. Chinese stock symbols (6-digit codes like "600000") trigger an additional AkShare data agent alongside yfinance.

## Common Commands

```bash
# Install dependencies
poetry install

# Run dev server
poetry run uvicorn app.main:app --reload

# Run all tests
poetry run pytest

# Run single test file
poetry run pytest tests/unit/agents/test_data_agent.py

# Run tests with coverage
poetry run pytest --cov=app tests/

# Quick validation (no pytest required)
poetry run python test_system.py

# Format
poetry run black app/

# Lint
poetry run ruff check app/
```

Note: `mypy` is referenced in the old docs but is **not** in `pyproject.toml` dev dependencies.

## Architecture

### Workflow Execution

The orchestrator (`app/orchestration/orchestrator.py`) builds a LangGraph `StateGraph` with conditional retry edges. Each agent is a graph node. The actual execution order is:

```
data_collection -> technical_analysis -> sentiment_analysis -> fundamental_analysis -> risk_assessment -> decision_making -> report_generation
```

Each node wraps the agent call with monitoring hooks, WebSocket broadcasts, and error handling. After each node, a conditional edge checks for errors and either retries, continues to the next node, or routes to the error handler.

**Important**: The `get_workflow_summary()` in `workflow.py` shows an incorrect/idealized DAG. The real flow is the sequential pipeline above.

### Agent Calling Pattern

The orchestrator calls agents differently depending on their type:
- **BaseAgent subclasses** (data, technical, fundamental): called via `agent.run(state)` which wraps `execute()` with circuit breaker, timeout, and monitoring.
- **StatelessAgent subclasses** (sentiment, risk, decision, report): called via `agent.process(state)` directly in the orchestrator node, which then assigns the result to the corresponding state key.

This means StatelessAgents skip the circuit breaker/timeout/retry wrapper in `BaseAgent.run()` — those protections are handled at the orchestrator node level instead.

### State Management

`app/orchestration/state.py` defines `AgentState` (TypedDict). State is treated as immutable — always use helper functions (`update_state_immutable`, `set_agent_status`, `add_agent_output`, `add_error`) which create new dicts rather than mutating. The `agent_outputs` and `errors` fields use `Annotated[List[Dict], add]` for LangGraph's built-in list accumulation.

### NumPy Serialization

Analysis agents produce numpy types (np.float64, np.int64, np.ndarray) that aren't JSON-serializable. The orchestrator applies `_convert_to_serializable()` to all agent results before merging into state. Any new agent code that returns data for API responses must ensure numpy types are converted.

### LLM Integration

`app/api/dependencies.py` creates the LLM via `ChatOpenAI` with Zhipu AI's OpenAI-compatible endpoint (`https://open.bigmodel.cn/api/paas/v4/`). Zhipu AI has priority; falls back to OpenAI if `ZHIPUAI_API_KEY` is not set. The orchestrator is a singleton created by `get_orchestrator()` on first use.

### Data Sources

- **yfinance** (`DataCollectionAgent`): US and international stocks
- **AkShare** (`AkShareDataAgent`): Chinese A-shares (triggered when symbols are 6-digit numbers)
- Both can be enabled/disabled via `YFINANCE_ENABLED` / `AKSHARE_ENABLED` settings

### API Layer

FastAPI routes in `app/api/routes/`:
- `analysis.py` — `/api/analysis/analyze` (async background), `/api/analysis/analyze/sync` (waits for completion)
- `backtest.py` — `/api/backtest/run`
- `history.py` — `/api/history/` — query past analysis records from SQLite
- `monitor.py` — `/api/monitor/` — in-memory workflow state (separate from the monitoring module)
- `monitoring.py` — `/api/monitoring/` — agent health, metrics, circuit breakers
- `websocket.py` — `/api/ws/monitoring` — real-time agent events via WebSocket

Workflow results are stored in an **in-memory dict** (`workflows` in `analysis.py`) and persisted to SQLite via `app/storage/database.py`. The in-memory status cache is lost on restart; completed history survives.

### Monitoring & Resilience

- `app/monitoring/monitor.py` — `AgentMonitor` tracks agent execution metrics, health scores, and broadcasts WebSocket events
- `app/monitoring/broadcast.py` — `ConnectionManager` handles WebSocket connections and real-time event broadcasting
- `app/resilience/` — circuit breaker (`CLOSED/OPEN/HALF_OPEN`), exponential backoff with jitter, per-agent timeout
- Global singletons accessed via `get_monitor()`, `get_circuit_breaker_registry()`, `get_retry_manager()`, `get_time_limiter()`

## Configuration

Environment variables loaded via `pydantic-settings` from `.env` (copy from `.env.example`). Key variables:
- `ZHIPUAI_API_KEY` — Primary LLM (GLM models via OpenAI-compatible API)
- `PRIMARY_LLM_MODEL` — `glm-5.3-flash` (default)
- `DATABASE_URL` — optional PostgreSQL connection for the checkpoint manager; the active LangGraph saver is currently memory-backed
- `REDIS_URL` — Redis for caching (configured but usage varies)
- `MAX_RETRIES`, `TIMEOUT_PER_AGENT` — Resilience settings

## Testing

Tests mirror `app/` structure under `tests/`:
- `tests/unit/` — unit tests for agents, orchestration, monitoring, resilience
- `tests/integration/` — integration tests
- `tests/e2e/` — end-to-end tests (placeholder)
- `test_system.py` at root for quick validation without pytest
- Uses `pytest-asyncio` for async agent tests

## Ruff & Black Config

Both configured for line-length 100, target Python 3.11. Ruff selects E, F, I, N, W, UP rules, ignores E501.
