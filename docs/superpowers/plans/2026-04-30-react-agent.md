# ReAct Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the stock analysis system from a fixed sequential pipeline into an autonomous ReAct agent with tool use, reasoning, and reflection.

**Architecture:** A single ReAct agent using LangGraph's StateGraph with `agent_reason → tool_execute → observe → reflect → (loop or END)` nodes. Existing agent computation logic is extracted into standalone `@tool` functions. GLM-4.7 drives reasoning via ZhipuAI's OpenAI-compatible API.

**Tech Stack:** Python 3.11, Poetry, FastAPI, LangGraph, LangChain (`langchain-openai` with ZhipuAI), Pydantic, pytest-asyncio

---

## File Structure

### New Files

| File | Responsibility |
|---|---|
| `app/react_agent/__init__.py` | Package init, exports `ReActAgent` |
| `app/react_agent/state.py` | `ReActState` TypedDict with all fields (backward compatible) |
| `app/react_agent/prompts.py` | System prompt, reflection prompt, prompt versioning |
| `app/react_agent/react_agent.py` | Main ReAct agent: graph builder + node implementations |
| `app/tools/__init__.py` | Package init, lazy tool registration |
| `app/tools/registry.py` | Tool registry: discover, register, and retrieve tools |
| `app/tools/data/market_data.py` | `fetch_stock_data` tool (extracted from DataCollectionAgent) |
| `app/tools/data/historical.py` | `get_historical_prices` tool (new) |
| `app/tools/analysis/technical.py` | `analyze_technical` tool (extracted from TechnicalAnalysisAgent) |
| `app/tools/analysis/fundamental.py` | `analyze_fundamental` tool (extracted from FundamentalAnalysisAgent) |
| `app/tools/analysis/sentiment.py` | `analyze_sentiment` tool (extracted from SentimentAnalysisAgent) |
| `app/tools/risk/assessment.py` | `assess_risk` tool (extracted from RiskAssessmentAgent) |
| `app/tools/decision/portfolio.py` | `calculate_position_size` tool (extracted from DecisionMakingAgent) |
| `app/tools/report/generate.py` | `generate_report` tool (extracted from ReportGenerationAgent) |
| `app/api/routes/agent.py` | New API endpoints: `/api/agent/analyze`, `/api/agent/result/{id}` |
| `tests/unit/react_agent/test_state.py` | Tests for ReActState |
| `tests/unit/react_agent/test_graph.py` | Tests for graph structure and routing |
| `tests/integration/test_react_agent.py` | Integration tests with mock LLM |
| `tests/unit/tools/test_registry.py` | Tests for tool registry |
| `tests/unit/tools/test_data_tools.py` | Tests for data tools (mocked yfinance) |
| `tests/unit/tools/test_analysis_tools.py` | Tests for analysis tools |
| `tests/unit/tools/test_risk_tools.py` | Tests for risk tools |

### Modified Files

| File | Changes |
|---|---|
| `app/config.py` | Add `agent_max_iterations`, `agent_cost_limit`, `agent_reasoning_model`, `agent_reflection_model` |
| `app/main.py` | Register new `/api/agent` router |

---

## Task 1: Create Directory Structure

**Files:**
- Create: `app/react_agent/__init__.py`
- Create: `app/tools/__init__.py`
- Create: `app/tools/data/__init__.py`
- Create: `app/tools/analysis/__init__.py`
- Create: `app/tools/risk/__init__.py`
- Create: `app/tools/decision/__init__.py`
- Create: `app/tools/report/__init__.py`
- Create: `tests/unit/react_agent/__init__.py`
- Create: `tests/unit/tools/__init__.py`

- [ ] **Step 1: Create all `__init__.py` files**

```bash
mkdir -p app/react_agent app/tools/data app/tools/analysis app/tools/risk app/tools/decision app/tools/report tests/unit/react_agent tests/unit/tools tests/integration
```

Create each `__init__.py` with appropriate exports. `app/react_agent/__init__.py`:
```python
"""ReAct autonomous agent package."""

from app.react_agent.react_agent import ReActAgent

__all__ = ["ReActAgent"]
```

`app/tools/__init__.py`:
```python
"""Tool registry and tools for the ReAct agent."""

from app.tools.registry import get_all_tools, get_tool, register_tool

__all__ = ["get_all_tools", "get_tool", "register_tool"]
```

Other `__init__.py` files can be empty.

- [ ] **Step 2: Verify directory structure**

```bash
find app/react_agent app/tools tests/unit/react_agent tests/unit/tests tests/integration -type f | sort
```

Expected: All `__init__.py` files listed.

---

## Task 2: Update Configuration

**Files:**
- Modify: `app/config.py`
- Test: `tests/unit/test_config.py` (new assertions)

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_config.py`:

```python
def test_agent_settings_exist():
    from app.config import settings
    
    assert hasattr(settings, "agent_max_iterations")
    assert settings.agent_max_iterations == 15
    assert hasattr(settings, "agent_cost_limit")
    assert settings.agent_cost_limit == 0.50
    assert hasattr(settings, "agent_reasoning_model")
    assert settings.agent_reasoning_model == "glm-5.2"
    assert hasattr(settings, "agent_reflection_model")
    assert settings.agent_reflection_model == "glm-5.2"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/unit/test_config.py::test_agent_settings_exist -v
```

Expected: `AttributeError: 'Settings' object has no attribute 'agent_max_iterations'`

- [ ] **Step 3: Add settings to config.py**

Add after line 70 (after `llm_timeout`):

```python
    # Agent Settings (ReAct)
    agent_max_iterations: int = 15
    agent_cost_limit: float = 0.50  # USD
    agent_reasoning_model: str = "glm-5.2"
    agent_reflection_model: str = "glm-5.2"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/unit/test_config.py::test_agent_settings_exist -v
```

Expected: PASS

---

## Task 3: Create ReAct State

**Files:**
- Create: `app/react_agent/state.py`
- Test: `tests/unit/react_agent/test_state.py`

- [ ] **Step 1: Write failing test**

`tests/unit/react_agent/test_state.py`:

```python
import pytest
from typing import get_type_hints
from app.react_agent.state import ReActState
from app.orchestration.state import AgentState


def test_react_state_has_all_agent_state_fields():
    """ReActState must include all AgentState fields (backward compatibility)."""
    agent_fields = set(AgentState.__annotations__.keys())
    react_fields = set(ReActState.__annotations__.keys())
    
    assert agent_fields.issubset(react_fields), (
        f"Missing fields: {agent_fields - react_fields}"
    )


def test_react_state_has_new_fields():
    """ReActState must have new ReAct-specific fields."""
    fields = ReActState.__annotations__
    
    assert "messages" in fields
    assert "iteration" in fields
    assert "max_iterations" in fields
    assert "tools_used" in fields
    assert "tool_call_history" in fields
    assert "final_answer" in fields
    assert "accumulated_cost" in fields
    assert "accumulated_tokens" in fields


def test_create_initial_react_state():
    """Test creating initial state with helper."""
    from app.react_agent.state import create_initial_react_state
    
    state = create_initial_react_state(
        query="Should I buy AAPL?",
        symbols=["AAPL"],
        thread_id="test-123",
    )
    
    assert state["query"] == "Should I buy AAPL?"
    assert state["symbols"] == ["AAPL"]
    assert state["thread_id"] == "test-123"
    assert state["iteration"] == 0
    assert state["max_iterations"] == 15
    assert state["messages"] == []
    assert state["tools_used"] == []
    assert state["tool_call_history"] == []
    assert state["final_answer"] is None
    assert state["accumulated_cost"] == 0.0
    assert state["accumulated_tokens"] == {"input": 0, "output": 0}
    assert "execution_metadata" in state
    assert state["execution_metadata"]["prompt_version"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/unit/react_agent/test_state.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement ReActState**

`app/react_agent/state.py`:

```python
"""ReAct agent state management.

ReActState is a standalone TypedDict that includes ALL fields from AgentState
plus new ReAct-specific fields. This ensures backward compatibility with the
existing checkpoint system and database serialization.
"""

from typing import Annotated, Any, List, Optional

from langchain_core.messages import BaseMessage
from typing_extensions import TypedDict

from app.config import settings


def add_messages(left: list, right: list) -> list:
    """Reducer for messages: append new messages."""
    return left + right


def add_items(left: list, right: list) -> list:
    """Reducer for lists: append items."""
    return left + right


class ReActState(TypedDict):
    """State for the ReAct autonomous agent.
    
    Includes all fields from the original AgentState for backward compatibility,
    plus new fields for the ReAct loop.
    """

    # --- Original AgentState fields (preserved for backward compatibility) ---
    query: str
    symbols: List[str]
    thread_id: Optional[str]
    market_data: dict
    financial_data: dict
    news_data: List[dict]
    technical_analysis: dict
    fundamental_analysis: dict
    sentiment_analysis: dict
    risk_assessment: dict
    decision: dict
    report: Optional[dict]
    agent_outputs: Annotated[List[dict], add_items]
    errors: Annotated[List[dict], add_items]
    retry_count: int
    agent_status: dict
    execution_metadata: dict
    current_agent: str
    current_step: int
    max_retries: int
    timeout_per_agent: int
    parallel_execution: bool

    # --- New ReAct fields ---
    messages: Annotated[List[BaseMessage], add_messages]
    iteration: int
    max_iterations: int
    tools_used: Annotated[List[str], add_items]
    tool_call_history: Annotated[List[dict], add_items]
    final_answer: Optional[str]
    accumulated_cost: float
    accumulated_tokens: dict


def create_initial_react_state(
    query: str,
    symbols: list[str],
    thread_id: str,
    max_iterations: Optional[int] = None,
) -> dict[str, Any]:
    """Create initial ReAct state.
    
    Args:
        query: User query
        symbols: Stock symbols to analyze
        thread_id: Unique thread identifier
        max_iterations: Maximum ReAct iterations (defaults to config)
    
    Returns:
        Initial state dictionary matching ReActState
    """
    from app.react_agent.prompts import PROMPT_VERSION
    
    return {
        # Input
        "query": query,
        "symbols": symbols,
        "thread_id": thread_id,
        
        # ReAct Loop
        "messages": [],
        "iteration": 0,
        "max_iterations": max_iterations or settings.agent_max_iterations,
        
        # Tool tracking
        "tools_used": [],
        "tool_call_history": [],
        
        # Collected data (original AgentState fields)
        "market_data": {},
        "financial_data": {},
        "news_data": [],
        "technical_analysis": {},
        "fundamental_analysis": {},
        "sentiment_analysis": {},
        "risk_assessment": {},
        "decision": {},
        "report": None,
        
        # Final output
        "final_answer": None,
        
        # Cost tracking
        "accumulated_cost": 0.0,
        "accumulated_tokens": {"input": 0, "output": 0},
        
        # Execution tracking (original AgentState fields)
        "agent_outputs": [],
        "errors": [],
        "retry_count": 0,
        "agent_status": {},
        "execution_metadata": {
            "prompt_version": PROMPT_VERSION,
        },
        "current_agent": "",
        "current_step": 0,
        "max_retries": settings.max_retries,
        "timeout_per_agent": settings.timeout_per_agent,
        "parallel_execution": settings.parallel_execution,
    }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/unit/react_agent/test_state.py -v
```

Expected: All 3 tests PASS

---

## Task 4: Create Prompts

**Files:**
- Create: `app/react_agent/prompts.py`
- Test: `tests/unit/react_agent/test_prompts.py`

- [ ] **Step 1: Write failing test**

`tests/unit/react_agent/test_prompts.py`:

```python
from app.react_agent.prompts import (
    REASONING_SYSTEM_PROMPT,
    REFLECTION_PROMPT,
    PROMPT_VERSION,
    format_reflection_prompt,
)


def test_system_prompt_exists():
    assert isinstance(REASONING_SYSTEM_PROMPT, str)
    assert len(REASONING_SYSTEM_PROMPT) > 100
    assert "tools" in REASONING_SYSTEM_PROMPT.lower()


def test_reflection_prompt_exists():
    assert isinstance(REFLECTION_PROMPT, str)
    assert len(REFLECTION_PROMPT) > 50


def test_prompt_version_exists():
    assert isinstance(PROMPT_VERSION, str)
    assert len(PROMPT_VERSION.split(".")) >= 2


def test_format_reflection_prompt():
    prompt = format_reflection_prompt(
        iteration=3,
        max_iterations=15,
        tools_used=["fetch_stock_data", "analyze_technical"],
        query="Should I buy AAPL?",
    )
    assert "3/15" in prompt
    assert "fetch_stock_data" in prompt
    assert "AAPL" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/unit/react_agent/test_prompts.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement prompts.py**

`app/react_agent/prompts.py`:

```python
"""Prompts for the ReAct agent."""

PROMPT_VERSION = "1.0.0"

REASONING_SYSTEM_PROMPT = """You are an expert stock analysis agent. You analyze stocks autonomously using the tools available to you.

AVAILABLE TOOLS:
- fetch_stock_data: Get market data, financials, and news for stocks. ALWAYS call this first.
- analyze_technical: Compute technical indicators (RSI, MACD, Bollinger Bands, support/resistance).
- analyze_fundamental: Evaluate financial health, profitability, and valuation (PE, PB, ROE, etc.).
- analyze_sentiment: Assess market sentiment from recent news.
- assess_risk: Calculate risk metrics (volatility, VaR, max drawdown, risk score).
- calculate_position_size: Determine recommended position size based on risk assessment.
- generate_report: Produce the final structured analysis report.
- get_historical_prices: Get extended price history for backtesting or detailed chart analysis.

REASONING APPROACH:
1. Understand the user's query — what do they need?
2. Fetch relevant data first using fetch_stock_data.
3. Apply appropriate analysis tools based on the data and query.
4. Evaluate results — is the analysis thorough enough?
5. If gaps exist, gather more data or run additional analysis.
6. When satisfied, generate a final report using generate_report.

RULES:
- Always fetch data before analyzing.
- Don't run analysis tools without data.
- Use at least 2-3 analysis perspectives before concluding.
- If data is insufficient, say so rather than guessing.
- Keep iterations focused — don't repeat the same analysis.
- Each tool call must include all required arguments.
"""

REFLECTION_PROMPT_TEMPLATE = """Evaluate the analysis progress so far.

Current iteration: {iteration}/{max_iterations}
Tools used so far: {tools_used}

Given the user's query: "{query}"

Review what has been learned and what gaps remain:
1. Has the user's question been adequately addressed?
2. Are there missing perspectives (technical, fundamental, sentiment, risk)?
3. Is the data quality sufficient?
4. Has any tool failed repeatedly?

Decide:
- If the analysis is complete and thorough → respond with "finish"
- If more analysis is needed → respond with "continue" and suggest the next tool
- If there are repeated failures or the query cannot be answered → respond with "error"

Respond with a JSON object:
{{
  "decision": "continue" | "finish" | "error",
  "reasoning": "Brief explanation of your decision",
  "next_tool": "Suggested next tool if continuing (optional)",
  "guidance": "Specific guidance for the next reasoning step (optional)"
}}
"""


def format_reflection_prompt(
    iteration: int,
    max_iterations: int,
    tools_used: list[str],
    query: str,
) -> str:
    """Format the reflection prompt with current state."""
    return REFLECTION_PROMPT_TEMPLATE.replace(
        "{iteration}", str(iteration)
    ).replace(
        "{max_iterations}", str(max_iterations)
    ).replace(
        "{tools_used}", ", ".join(tools_used) if tools_used else "none"
    ).replace(
        "{query}", query
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/unit/react_agent/test_prompts.py -v
```

Expected: All 4 tests PASS

---

## Task 5: Create Tool Registry

**Files:**
- Create: `app/tools/registry.py`
- Test: `tests/unit/tools/test_registry.py`

- [ ] **Step 1: Write failing test**

`tests/unit/tools/test_registry.py`:

```python
import pytest
from langchain_core.tools import tool

from app.tools.registry import get_all_tools, get_tool, register_tool, clear_registry


@pytest.fixture
def sample_tool():
    @tool
    def mock_tool(query: str) -> str:
        """A mock tool for testing."""
        return f"Result for {query}"
    return mock_tool


@pytest.fixture(autouse=True)
def clean_registry():
    clear_registry()
    yield
    clear_registry()


def test_register_and_get_tool(sample_tool):
    register_tool(sample_tool)
    
    retrieved = get_tool("mock_tool")
    assert retrieved is sample_tool


def test_get_all_tools(sample_tool):
    register_tool(sample_tool)
    tools = get_all_tools()
    
    assert len(tools) == 1
    assert tools[0] == sample_tool


def test_get_tool_not_found():
    result = get_tool("nonexistent")
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/unit/tools/test_registry.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement registry.py**

`app/tools/registry.py`:

```python
"""Tool registry for the ReAct agent.

Tools are registered centrally so the agent can discover and invoke them.
"""

from typing import Optional

from langchain_core.tools import BaseTool

# Global tool registry
_TOOLS: dict[str, BaseTool] = {}


def register_tool(tool: BaseTool) -> None:
    """Register a tool in the global registry.
    
    Args:
        tool: A LangChain tool instance
    """
    _TOOLS[tool.name] = tool


def get_tool(name: str) -> Optional[BaseTool]:
    """Get a tool by name.
    
    Args:
        name: Tool name
    
    Returns:
        The tool or None if not found
    """
    return _TOOLS.get(name)


def get_all_tools() -> list[BaseTool]:
    """Get all registered tools.
    
    Returns:
        List of all registered tools
    """
    return list(_TOOLS.values())


def clear_registry() -> None:
    """Clear all registered tools. Useful for testing."""
    _TOOLS.clear()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/unit/tools/test_registry.py -v
```

Expected: All 4 tests PASS

---

## Task 6: Create Data Tools

**Files:**
- Create: `app/tools/data/market_data.py`
- Create: `app/tools/data/historical.py`
- Test: `tests/unit/tools/test_data_tools.py`

- [ ] **Step 1: Write failing test**

`tests/unit/tools/test_data_tools.py`:

```python
import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.asyncio
async def test_fetch_stock_data_mocked():
    """Test fetch_stock_data with mocked yfinance."""
    from app.tools.data.market_data import fetch_stock_data
    
    mock_ticker = MagicMock()
    mock_ticker.info = {
        "currentPrice": 150.0,
        "previousClose": 145.0,
        "volume": 1000000,
        "marketCap": 2000000000,
        "longName": "Apple Inc",
        "sector": "Technology",
    }
    mock_hist = MagicMock()
    mock_hist.empty = False
    mock_hist.index = [MagicMock(strftime=lambda fmt: "2024-01-01")]
    mock_hist.__getitem__ = lambda self, key: MagicMock(tolist=lambda: [150.0])
    mock_ticker.history.return_value = mock_hist
    
    with patch("yfinance.Ticker", return_value=mock_ticker):
        result = await fetch_stock_data.ainvoke({"symbols": ["AAPL"]})
    
    assert "AAPL" in result
    assert result["AAPL"]["market_data"]["current_price"] == 150.0


@pytest.mark.asyncio
async def test_get_historical_prices_mocked():
    """Test get_historical_prices with mocked yfinance."""
    from app.tools.data.historical import get_historical_prices
    
    mock_ticker = MagicMock()
    mock_hist = MagicMock()
    mock_hist.empty = False
    mock_hist.index = [MagicMock(strftime=lambda fmt: "2024-01-01")]
    mock_hist.__getitem__ = lambda self, key: MagicMock(tolist=lambda: [150.0])
    mock_ticker.history.return_value = mock_hist
    
    with patch("yfinance.Ticker", return_value=mock_ticker):
        result = await get_historical_prices.ainvoke({
            "symbol": "AAPL",
            "period": "1mo",
        })
    
    assert "dates" in result
    assert "close" in result
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/unit/tools/test_data_tools.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement data tools**

`app/tools/data/market_data.py`:

```python
"""Data collection tools for the ReAct agent.

Extracted from app/agents/data_agent.py
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import yfinance as yf
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.utils.logging import get_logger

logger = get_logger(__name__)


def _convert_to_yahoo_symbol(symbol: str) -> str:
    """Convert local symbol to Yahoo Finance format."""
    if symbol.isalpha() and len(symbol) <= 5:
        return symbol
    if ".HK" in symbol.upper():
        return symbol.upper()
    if symbol.isdigit() and len(symbol) == 6:
        if symbol.startswith("6"):
            return f"{symbol}.SS"
        elif symbol.startswith("0") or symbol.startswith("3"):
            return f"{symbol}.SZ"
        return f"{symbol}.SS"
    return symbol


def _historical_data_to_dict(df: pd.DataFrame) -> dict:
    """Convert historical DataFrame to dict."""
    if df is None or df.empty:
        return {}
    return {
        "dates": [d.strftime("%Y-%m-%d") for d in df.index],
        "open": df["Open"].tolist(),
        "high": df["High"].tolist(),
        "low": df["Low"].tolist(),
        "close": df["Close"].tolist(),
        "volume": df["Volume"].tolist(),
    }


def _financial_statement_to_dict(df: pd.DataFrame) -> dict:
    """Convert financial statement DataFrame to dict."""
    if df is None or df.empty:
        return {}
    return {
        "dates": [d.strftime("%Y-%m-%d") for d in df.columns],
        "data": {row: df.loc[row].tolist() for row in df.index},
    }


class FetchStockDataInput(BaseModel):
    symbols: list[str] = Field(description="Stock ticker symbols (e.g., ['AAPL', '601888'])")
    source: str = Field(default="auto", description="Data source: 'yfinance', 'akshare', or 'auto'")


@tool(args_schema=FetchStockDataInput)
async def fetch_stock_data(symbols: list[str], source: str = "auto") -> dict[str, Any]:
    """Fetch real-time and historical stock market data, financials, and news.
    
    This is the FIRST tool you should call. It provides the raw data needed
    for all other analysis tools.
    
    Args:
        symbols: List of stock symbols (e.g., ['AAPL', '601888.SS', '0700.HK'])
        source: Data source - use 'auto' to let the system decide
    
    Returns:
        Dictionary mapping each symbol to its market data, financial data, and news.
    """
    tasks = [_fetch_single_symbol_data(s) for s in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    output = {}
    for symbol, result in zip(symbols, results):
        if isinstance(result, Exception):
            logger.error(f"Failed to fetch data for {symbol}: {result}")
            continue
        if result:
            output[symbol] = result
    
    return output


async def _fetch_single_symbol_data(symbol: str) -> dict[str, Any] | None:
    """Fetch all data for a single symbol."""
    try:
        yahoo_symbol = _convert_to_yahoo_symbol(symbol)
        ticker = yf.Ticker(yahoo_symbol)
        
        info = ticker.info
        end_date = datetime.now()
        start_date = end_date - timedelta(days=90)
        hist = ticker.history(start=start_date, end=end_date)
        
        market_data = {}
        if not hist.empty:
            market_data = {
                "symbol": symbol,
                "yahoo_symbol": yahoo_symbol,
                "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "previous_close": info.get("previousClose"),
                "change": info.get("currentPrice") - info.get("previousClose", 0)
                if info.get("currentPrice") and info.get("previousClose")
                else None,
                "change_percent": (
                    (info.get("currentPrice") - info.get("previousClose", 0))
                    / info.get("previousClose", 1) * 100
                    if info.get("currentPrice") and info.get("previousClose")
                    else None
                ),
                "volume": info.get("volume"),
                "avg_volume": info.get("averageVolume"),
                "market_cap": info.get("marketCap"),
                "52_week_high": info.get("fiftyTwoWeekHigh"),
                "52_week_low": info.get("fiftyTwoWeekLow"),
                "company_name": info.get("longName"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "historical_data": _historical_data_to_dict(hist),
            }
        
        # Financial data
        financial_data = {}
        try:
            financial_data = {
                "metrics": {
                    "roe": info.get("returnOnEquity"),
                    "roa": info.get("returnOnAssets"),
                    "profit_margin": info.get("profitMargins"),
                    "operating_margin": info.get("operatingMargins"),
                    "pe_ratio": info.get("trailingPE"),
                    "forward_pe": info.get("forwardPE"),
                    "pb_ratio": info.get("priceToBook"),
                    "ps_ratio": info.get("priceToSalesTrailing12Months"),
                    "peg_ratio": info.get("pegRatio"),
                    "enterprise_value": info.get("enterpriseValue"),
                    "ev_ebitda": info.get("enterpriseToEbitda"),
                    "debt_to_equity": info.get("debtToEquity"),
                    "current_ratio": info.get("currentRatio"),
                    "quick_ratio": info.get("quickRatio"),
                    "total_cash": info.get("totalCash"),
                    "total_debt": info.get("totalDebt"),
                    "total_revenue": info.get("totalRevenue"),
                    "dividend_yield": info.get("dividendYield"),
                    "payout_ratio": info.get("payoutRatio"),
                }
            }
        except Exception:
            pass
        
        # News
        news_data = []
        try:
            raw_news = ticker.news
            for item in (raw_news or [])[:20]:
                content = item.get("content", {})
                title = content.get("title") or item.get("title")
                summary = content.get("summary") or item.get("summary")
                link = None
                if content.get("canonicalUrl"):
                    link = content["canonicalUrl"].get("url")
                if not link and item.get("link"):
                    link = item.get("link")
                
                provider = content.get("provider", {})
                source_name = provider.get("displayName") or item.get("publisher")
                published = content.get("pubDate") or item.get("providerPublishTime")
                
                related = item.get("relatedTickers", [])
                if symbol not in related:
                    related.append(symbol)
                
                if title:
                    news_data.append({
                        "title": title,
                        "link": link,
                        "published": published,
                        "source": source_name,
                        "summary": summary,
                        "related_symbols": related,
                        "original_symbol": symbol,
                    })
        except Exception:
            pass
        
        return {
            "market_data": market_data,
            "financial_data": financial_data,
            "news_data": news_data,
        }
    
    except Exception as e:
        logger.error(f"Error collecting data for {symbol}: {e}")
        return None
```

`app/tools/data/historical.py`:

```python
"""Historical price data tool."""

from typing import Any

import yfinance as yf
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.utils.logging import get_logger

logger = get_logger(__name__)


class GetHistoricalPricesInput(BaseModel):
    symbol: str = Field(description="Stock symbol (e.g., 'AAPL', '601888.SS')")
    period: str = Field(default="3mo", description="Time period: '1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'ytd', 'max'")
    interval: str = Field(default="1d", description="Data interval: '1d', '1wk', '1mo'")


@tool(args_schema=GetHistoricalPricesInput)
async def get_historical_prices(
    symbol: str,
    period: str = "3mo",
    interval: str = "1d",
) -> dict[str, Any]:
    """Get historical price data for a stock.
    
    Use this when you need extended price history for backtesting or detailed
    chart analysis beyond what fetch_stock_data provides.
    
    Args:
        symbol: Stock symbol
        period: Time period (e.g., '1mo', '3mo', '1y')
        interval: Data interval ('1d' for daily, '1wk' for weekly)
    
    Returns:
        Dictionary with dates, open, high, low, close, volume arrays.
    """
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period, interval=interval)
        
        if hist.empty:
            return {"error": f"No historical data found for {symbol}"}
        
        return {
            "symbol": symbol,
            "period": period,
            "interval": interval,
            "dates": [d.strftime("%Y-%m-%d") for d in hist.index],
            "open": hist["Open"].tolist(),
            "high": hist["High"].tolist(),
            "low": hist["Low"].tolist(),
            "close": hist["Close"].tolist(),
            "volume": hist["Volume"].tolist(),
        }
    
    except Exception as e:
        logger.error(f"Error fetching historical prices for {symbol}: {e}")
        return {"error": str(e)}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/unit/tools/test_data_tools.py -v
```

Expected: Both tests PASS

---

## Task 7: Create Analysis Tools

**Files:**
- Create: `app/tools/analysis/technical.py`
- Create: `app/tools/analysis/fundamental.py`
- Create: `app/tools/analysis/sentiment.py`
- Test: `tests/unit/tools/test_analysis_tools.py`

- [ ] **Step 1: Write failing test**

`tests/unit/tools/test_analysis_tools.py`:

```python
import pytest


def test_analyze_technical():
    """Test technical analysis with synthetic data."""
    from app.tools.analysis.technical import analyze_technical
    
    market_data = {
        "AAPL": {
            "current_price": 150.0,
            "historical_data": {
                "dates": ["2024-01-" + str(i).zfill(2) for i in range(1, 31)],
                "open": [100.0 + i for i in range(30)],
                "high": [101.0 + i for i in range(30)],
                "low": [99.0 + i for i in range(30)],
                "close": [100.0 + i for i in range(30)],
                "volume": [1000000] * 30,
            }
        }
    }
    
    result = analyze_technical.invoke({"market_data": market_data})
    
    assert "AAPL" in result
    assert "indicators" in result["AAPL"]
    assert "signals" in result["AAPL"]
    assert "sentiment" in result["AAPL"]


def test_analyze_fundamental():
    """Test fundamental analysis."""
    from app.tools.analysis.fundamental import analyze_fundamental
    
    financial_data = {
        "AAPL": {
            "metrics": {
                "roe": 0.25,
                "roa": 0.15,
                "profit_margin": 0.20,
                "operating_margin": 0.25,
                "pe_ratio": 20.0,
                "pb_ratio": 5.0,
                "ps_ratio": 6.0,
                "ev_ebitda": 15.0,
                "debt_to_equity": 1.5,
                "current_ratio": 1.2,
                "quick_ratio": 1.0,
            }
        }
    }
    
    market_data = {"AAPL": {"current_price": 150.0}}
    
    result = analyze_fundamental.invoke({
        "financial_data": financial_data,
        "market_data": market_data,
    })
    
    assert "AAPL" in result
    assert "overall_score" in result["AAPL"]
    assert "recommendation" in result["AAPL"]


def test_analyze_sentiment():
    """Test sentiment analysis."""
    from app.tools.analysis.sentiment import analyze_sentiment
    
    news_data = [
        {
            "title": "Apple stock surges on strong earnings",
            "summary": "Apple reported record profits",
            "related_symbols": ["AAPL"],
            "original_symbol": "AAPL",
        },
        {
            "title": "Market falls on recession fears",
            "summary": "Global markets decline",
            "related_symbols": ["AAPL"],
            "original_symbol": "AAPL",
        },
    ]
    
    result = analyze_sentiment.invoke({
        "news_data": news_data,
        "symbols": ["AAPL"],
    })
    
    assert "sentiment_by_symbol" in result
    assert "AAPL" in result["sentiment_by_symbol"]
    assert "score" in result["sentiment_by_symbol"]["AAPL"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/unit/tools/test_analysis_tools.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement analysis tools**

`app/tools/analysis/technical.py`:

```python
"""Technical analysis tools. Extracted from app/agents/analysis_agent.py"""

from typing import Any, Tuple

import numpy as np
import pandas as pd
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.utils.logging import get_logger

logger = get_logger(__name__)


class AnalyzeTechnicalInput(BaseModel):
    market_data: dict = Field(description="Market data from fetch_stock_data")


@tool(args_schema=AnalyzeTechnicalInput)
def analyze_technical(market_data: dict) -> dict[str, Any]:
    """Compute technical indicators (RSI, MACD, Bollinger Bands, support/resistance).
    
    Args:
        market_data: Market data dictionary from fetch_stock_data
    
    Returns:
        Technical analysis by symbol with indicators, signals, and sentiment score.
    """
    results = {}
    
    for symbol, data in market_data.items():
        hist = data.get("historical_data")
        if not hist:
            continue
        
        try:
            df = _to_dataframe(hist)
            if df.empty or len(df) < 20:
                continue
            
            indicators = _calculate_indicators(df)
            signals = _generate_signals(df, indicators)
            support, resistance = _find_support_resistance(df)
            patterns = _detect_patterns(df)
            sentiment = _calculate_sentiment(signals, indicators)
            
            results[symbol] = {
                "symbol": symbol,
                "current_price": data.get("current_price"),
                "indicators": indicators,
                "signals": signals,
                "support": support,
                "resistance": resistance,
                "patterns": patterns,
                "sentiment": sentiment,
            }
        except Exception as e:
            logger.error(f"Technical analysis failed for {symbol}: {e}")
    
    return results


def _to_dataframe(hist: dict) -> pd.DataFrame:
    df = pd.DataFrame({
        "open": hist.get("open", []),
        "high": hist.get("high", []),
        "low": hist.get("low", []),
        "close": hist.get("close", []),
        "volume": hist.get("volume", []),
    }, index=pd.to_datetime(hist.get("dates", [])))
    return df.dropna()


def _calculate_indicators(df: pd.DataFrame) -> dict:
    close = df["close"]
    indicators = {}
    
    indicators["sma_20"] = float(close.rolling(20).mean().iloc[-1])
    indicators["sma_50"] = float(close.rolling(50).mean().iloc[-1])
    indicators["ema_12"] = float(close.ewm(span=12).mean().iloc[-1])
    indicators["ema_26"] = float(close.ewm(span=26).mean().iloc[-1])
    
    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    indicators["rsi"] = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else None
    
    # MACD
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9).mean()
    indicators["macd"] = {
        "macd": float(macd_line.iloc[-1]),
        "signal": float(signal_line.iloc[-1]),
        "histogram": float(macd_line.iloc[-1] - signal_line.iloc[-1]),
    }
    
    # Bollinger
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    indicators["bollinger_bands"] = {
        "upper": float(sma20.iloc[-1] + std20.iloc[-1] * 2),
        "middle": float(sma20.iloc[-1]),
        "lower": float(sma20.iloc[-1] - std20.iloc[-1] * 2),
    }
    
    return indicators


def _generate_signals(df: pd.DataFrame, indicators: dict) -> dict:
    signals = {}
    current = df["close"].iloc[-1]
    sma20 = indicators.get("sma_20")
    sma50 = indicators.get("sma_50")
    
    if sma20 and sma50:
        if current > sma20 > sma50:
            signals["trend"] = "strong_bullish"
        elif current > sma20:
            signals["trend"] = "bullish"
        elif current < sma20 < sma50:
            signals["trend"] = "strong_bearish"
        elif current < sma20:
            signals["trend"] = "bearish"
        else:
            signals["trend"] = "neutral"
    
    rsi = indicators.get("rsi")
    if rsi:
        if rsi > 70: signals["rsi"] = "overbought"
        elif rsi > 60: signals["rsi"] = "bullish"
        elif rsi < 30: signals["rsi"] = "oversold"
        elif rsi < 40: signals["rsi"] = "bearish"
        else: signals["rsi"] = "neutral"
    
    macd = indicators.get("macd", {})
    if macd.get("histogram", 0) > 0:
        signals["macd"] = "bullish" if macd.get("macd", 0) > macd.get("signal", 0) else "neutral"
    else:
        signals["macd"] = "bearish"
    
    return signals


def _find_support_resistance(df: pd.DataFrame, window: int = 20) -> Tuple[dict, dict]:
    close = df["close"]
    recent = close.tail(window)
    
    local_min, local_max = [], []
    for i in range(2, len(recent) - 2):
        if (recent.iloc[i] < recent.iloc[i-1] and recent.iloc[i] < recent.iloc[i-2] and
            recent.iloc[i] < recent.iloc[i+1] and recent.iloc[i] < recent.iloc[i+2]):
            local_min.append(recent.iloc[i])
        if (recent.iloc[i] > recent.iloc[i-1] and recent.iloc[i] > recent.iloc[i-2] and
            recent.iloc[i] > recent.iloc[i+1] and recent.iloc[i] > recent.iloc[i+2]):
            local_max.append(recent.iloc[i])
    
    current = close.iloc[-1]
    support = sorted([l for l in local_min if l < current], reverse=True)
    resistance = sorted([l for l in local_max if l > current])
    
    return (
        {"s1": float(support[0]) if support else None, "s2": float(support[1]) if len(support) > 1 else None},
        {"r1": float(resistance[0]) if resistance else None, "r2": float(resistance[1]) if len(resistance) > 1 else None},
    )


def _detect_patterns(df: pd.DataFrame) -> dict:
    patterns = {}
    if len(df) < 3:
        return patterns
    
    recent = df.tail(5).to_dict("records")
    latest = recent[-1]
    
    body_size = abs(latest["close"] - latest["open"])
    range_size = latest["high"] - latest["low"]
    if range_size > 0 and body_size / range_size < 0.1:
        patterns["doji"] = True
    
    return patterns


def _calculate_sentiment(signals: dict, indicators: dict) -> dict:
    score = 0
    
    trend = signals.get("trend", "neutral")
    if trend == "strong_bullish": score += 30
    elif trend == "bullish": score += 15
    elif trend == "bearish": score -= 15
    elif trend == "strong_bearish": score -= 30
    
    rsi = signals.get("rsi", "neutral")
    if rsi == "oversold": score += 20
    elif rsi == "bullish": score += 10
    elif rsi == "bearish": score -= 10
    elif rsi == "overbought": score -= 20
    
    macd = signals.get("macd", "neutral")
    if macd == "bullish": score += 20
    elif macd == "bearish": score -= 20
    
    if score >= 60: sentiment = "strong_buy"
    elif score >= 30: sentiment = "buy"
    elif score >= 10: sentiment = "moderate_buy"
    elif score <= -60: sentiment = "strong_sell"
    elif score <= -30: sentiment = "sell"
    elif score <= -10: sentiment = "moderate_sell"
    else: sentiment = "hold"
    
    return {"score": score, "sentiment": sentiment, "strength": abs(score)}
```

`app/tools/analysis/fundamental.py`:

```python
"""Fundamental analysis tools. Extracted from app/agents/analysis_agent.py"""

from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.utils.logging import get_logger

logger = get_logger(__name__)


class AnalyzeFundamentalInput(BaseModel):
    financial_data: dict = Field(description="Financial data from fetch_stock_data")
    market_data: dict = Field(default={}, description="Market data for additional context")


@tool(args_schema=AnalyzeFundamentalInput)
def analyze_fundamental(financial_data: dict, market_data: dict = None) -> dict[str, Any]:
    """Evaluate financial health, profitability, and valuation.
    
    Args:
        financial_data: Financial data from fetch_stock_data
        market_data: Optional market data for context
    
    Returns:
        Fundamental analysis by symbol with scores and recommendations.
    """
    results = {}
    market_data = market_data or {}
    
    for symbol, fin in financial_data.items():
        try:
            metrics = fin.get("metrics", {})
            mkt = market_data.get(symbol, {})
            
            profitability = _analyze_profitability(metrics)
            valuation = _analyze_valuation(metrics, mkt)
            health = _analyze_financial_health(metrics)
            
            p_score = profitability["score"]
            v_score = valuation["score"]
            h_score = health["score"]
            overall = p_score * 0.35 + v_score * 0.30 + h_score * 0.25 + 50 * 0.10
            
            results[symbol] = {
                "symbol": symbol,
                "profitability": profitability,
                "valuation": valuation,
                "financial_health": health,
                "overall_score": {
                    "score": round(overall, 2),
                    "rating": _score_to_rating(overall, 100),
                },
                "recommendation": _recommendation(overall),
            }
        except Exception as e:
            logger.error(f"Fundamental analysis failed for {symbol}: {e}")
    
    return results


def _analyze_profitability(metrics: dict) -> dict:
    score = 0
    details = {}
    
    roe = metrics.get("roe")
    if roe:
        details["roe"] = float(roe)
        if roe >= 0.20: score += 40
        elif roe >= 0.15: score += 30
        elif roe >= 0.10: score += 20
        elif roe >= 0.05: score += 10
    
    roa = metrics.get("roa")
    if roa:
        details["roa"] = float(roa)
        if roa >= 0.10: score += 20
        elif roa >= 0.05: score += 15
        elif roa >= 0.02: score += 10
    
    pm = metrics.get("profit_margin")
    if pm:
        details["profit_margin"] = float(pm)
        if pm >= 0.20: score += 20
        elif pm >= 0.10: score += 15
        elif pm >= 0.05: score += 10
    
    om = metrics.get("operating_margin")
    if om:
        details["operating_margin"] = float(om)
        if om >= 0.15: score += 20
        elif om >= 0.10: score += 15
        elif om >= 0.05: score += 10
    
    return {"score": score, "rating": _score_to_rating(score, 100), "details": details}


def _analyze_valuation(metrics: dict, mkt: dict) -> dict:
    score = 0
    details = {}
    
    pe = metrics.get("pe_ratio")
    if pe and 0 < pe <= 40:
        details["pe_ratio"] = float(pe)
        if pe <= 15: score += 30
        elif pe <= 25: score += 20
        elif pe <= 40: score += 10
    
    pb = metrics.get("pb_ratio")
    if pb and 0 < pb <= 3:
        details["pb_ratio"] = float(pb)
        if pb <= 1: score += 25
        elif pb <= 2: score += 20
        elif pb <= 3: score += 15
    
    ps = metrics.get("ps_ratio")
    if ps and 0 < ps <= 6:
        details["ps_ratio"] = float(ps)
        if ps <= 2: score += 25
        elif ps <= 4: score += 20
        elif ps <= 6: score += 15
    
    ev = metrics.get("ev_ebitda")
    if ev and 0 < ev <= 16:
        details["ev_ebitda"] = float(ev)
        if ev <= 8: score += 20
        elif ev <= 12: score += 15
        elif ev <= 16: score += 10
    
    return {"score": score, "rating": _score_to_rating(score, 100), "details": details}


def _analyze_financial_health(metrics: dict) -> dict:
    score = 0
    details = {}
    
    de = metrics.get("debt_to_equity")
    if de is not None:
        details["debt_to_equity"] = float(de)
        if de <= 0.5: score += 40
        elif de <= 1: score += 30
        elif de <= 1.5: score += 20
        elif de <= 2: score += 10
    
    cr = metrics.get("current_ratio")
    if cr:
        details["current_ratio"] = float(cr)
        if cr >= 2: score += 30
        elif cr >= 1.5: score += 25
        elif cr >= 1: score += 15
    
    qr = metrics.get("quick_ratio")
    if qr:
        details["quick_ratio"] = float(qr)
        if qr >= 1.5: score += 30
        elif qr >= 1: score += 25
        elif qr >= 0.8: score += 15
    
    return {"score": score, "rating": _score_to_rating(score, 100), "details": details}


def _score_to_rating(score: float, max_score: float) -> str:
    pct = score / max_score if max_score > 0 else 0
    if pct >= 0.8: return "excellent"
    elif pct >= 0.6: return "good"
    elif pct >= 0.4: return "fair"
    elif pct >= 0.2: return "poor"
    else: return "very_poor"


def _recommendation(score: float) -> str:
    if score >= 75: return "strong_buy"
    elif score >= 60: return "buy"
    elif score >= 45: return "hold"
    elif score >= 30: return "sell"
    else: return "strong_sell"
```

`app/tools/analysis/sentiment.py`:

```python
"""Sentiment analysis tools. Extracted from app/agents/sentiment_agent.py"""

from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.utils.logging import get_logger

logger = get_logger(__name__)

POSITIVE_WORDS = {
    "up", "rise", "gain", "growth", "strong", "beat", "top", "best",
    "surge", "rally", "bull", "buy", "outperform", "upgrade", "profit",
    "record", "high", "breakthrough", "expansion", "dividend", "success",
}

NEGATIVE_WORDS = {
    "down", "fall", "drop", "loss", "weak", "miss", "bottom", "worst",
    "plunge", "crash", "bear", "sell", "underperform", "downgrade", "debt",
    "low", "cut", "reduction", "layoff", "lawsuit", "fraud", "risk",
}


class AnalyzeSentimentInput(BaseModel):
    news_data: list = Field(description="News articles from fetch_stock_data")
    symbols: list[str] = Field(description="Stock symbols to analyze")


@tool(args_schema=AnalyzeSentimentInput)
def analyze_sentiment(news_data: list, symbols: list[str]) -> dict[str, Any]:
    """Assess market sentiment from recent news.
    
    Args:
        news_data: News articles from fetch_stock_data
        symbols: Stock symbols to analyze sentiment for
    
    Returns:
        Sentiment analysis by symbol and overall summary.
    """
    results = {}
    
    for symbol in symbols:
        symbol_news = [
            n for n in news_data
            if symbol in n.get("related_symbols", []) or n.get("original_symbol") == symbol
        ]
        
        if not symbol_news:
            results[symbol] = _empty_sentiment()
            continue
        
        total_score = 0
        analyzed = 0
        recent_scores = []
        
        for article in symbol_news:
            text = (article.get("title", "") + " " + article.get("summary", "")).lower()
            score = sum(1 for w in POSITIVE_WORDS if w in text) - sum(1 for w in NEGATIVE_WORDS if w in text)
            
            if score != 0:
                total_score += score
                analyzed += 1
                recent_scores.append(score)
        
        if analyzed > 0:
            normalized = max(-100, min(100, (total_score / analyzed) * 20))
        else:
            normalized = 0
        
        if normalized >= 40: sentiment = "very_positive"
        elif normalized >= 15: sentiment = "positive"
        elif normalized <= -40: sentiment = "very_negative"
        elif normalized <= -15: sentiment = "negative"
        else: sentiment = "neutral"
        
        results[symbol] = {
            "sentiment": sentiment,
            "score": normalized,
            "article_count": analyzed,
            "recent_scores": recent_scores[-10:],
            "trend": _calculate_trend(recent_scores),
        }
    
    return {
        "sentiment_by_symbol": results,
        "overall_sentiment": _calculate_overall(results),
    }


def _empty_sentiment() -> dict:
    return {"sentiment": "neutral", "score": 0, "article_count": 0, "recent_scores": [], "trend": "no_data"}


def _calculate_trend(scores: list) -> str:
    if len(scores) < 3:
        return "insufficient_data"
    recent = scores[-3:]
    if all(s > 0 for s in recent): return "improving"
    elif all(s < 0 for s in recent): return "declining"
    elif recent[-1] > recent[0]: return "improving"
    elif recent[-1] < recent[0]: return "declining"
    else: return "stable"


def _calculate_overall(results: dict) -> dict:
    if not results:
        return {"sentiment": "neutral", "score": 0}
    
    scores = [r.get("score", 0) for r in results.values()]
    avg = sum(scores) / len(scores) if scores else 0
    
    if avg >= 30: sentiment = "positive"
    elif avg <= -30: sentiment = "negative"
    else: sentiment = "neutral"
    
    return {
        "sentiment": sentiment,
        "score": avg,
        "positive_count": sum(1 for s in results.values() if s.get("score", 0) > 15),
        "negative_count": sum(1 for s in results.values() if s.get("score", 0) < -15),
        "neutral_count": sum(1 for s in results.values() if -15 <= s.get("score", 0) <= 15),
    }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/unit/tools/test_analysis_tools.py -v
```

Expected: All 3 tests PASS

---

## Task 8: Create Risk and Decision Tools

**Files:**
- Create: `app/tools/risk/assessment.py`
- Create: `app/tools/decision/portfolio.py`
- Test: `tests/unit/tools/test_risk_tools.py`

- [ ] **Step 1: Write failing test**

`tests/unit/tools/test_risk_tools.py`:

```python
import pytest
import numpy as np


def test_assess_risk():
    """Test risk assessment with synthetic data."""
    from app.tools.risk.assessment import assess_risk
    
    market_data = {
        "AAPL": {
            "historical_data": {
                "close": list(100.0 + np.random.randn(50).cumsum()),
            }
        }
    }
    
    result = assess_risk.invoke({"market_data": market_data})
    
    assert "AAPL" in result
    assert "risk_score" in result["AAPL"]
    assert "risk_level" in result["AAPL"]
    assert "metrics" in result["AAPL"]


def test_calculate_position_size():
    """Test position sizing."""
    from app.tools.decision.portfolio import calculate_position_size
    
    risk_data = {
        "AAPL": {
            "risk_score": 50,
            "risk_level": "medium",
            "position_recommendation": {
                "max_position_size": 10.0,
                "stop_loss_percentage": 5.0,
            }
        }
    }
    
    result = calculate_position_size.invoke({"risk_data": risk_data})
    
    assert "AAPL" in result
    assert "position_size" in result["AAPL"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/unit/tools/test_risk_tools.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement risk and decision tools**

`app/tools/risk/assessment.py`:

```python
"""Risk assessment tools. Extracted from app/agents/risk_agent.py"""

from typing import Any

import numpy as np
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.utils.logging import get_logger

logger = get_logger(__name__)


class AssessRiskInput(BaseModel):
    market_data: dict = Field(description="Market data with historical prices")


@tool(args_schema=AssessRiskInput)
def assess_risk(market_data: dict) -> dict[str, Any]:
    """Calculate risk metrics (volatility, VaR, max drawdown, risk score).
    
    Args:
        market_data: Market data from fetch_stock_data containing historical_data
    
    Returns:
        Risk assessment by symbol with scores, metrics, and position recommendations.
    """
    results = {}
    
    for symbol, data in market_data.items():
        try:
            hist = data.get("historical_data", {})
            closes = np.array(hist.get("close", []))
            
            if len(closes) < 20:
                results[symbol] = _minimal_risk(data)
                continue
            
            returns = np.diff(closes) / closes[:-1]
            volatility = float(np.std(returns))
            var_95 = float(np.percentile(returns, 5))
            var_99 = float(np.percentile(returns, 1))
            max_dd = _max_drawdown(closes)
            downside = _downside_risk(returns)
            beta = 1.0  # Placeholder
            
            risk_score = _calculate_score(volatility, max_dd, var_95, beta)
            risk_level = _score_to_level(risk_score)
            
            results[symbol] = {
                "symbol": symbol,
                "risk_score": risk_score,
                "risk_level": risk_level,
                "metrics": {
                    "volatility": volatility,
                    "volatility_annualized": float(volatility * np.sqrt(252)),
                    "var_95": var_95,
                    "var_99": var_99,
                    "max_drawdown": max_dd,
                    "downside_risk": downside,
                    "beta": beta,
                },
                "position_recommendation": {
                    "max_position_size": _position_size(risk_score),
                    "stop_loss_percentage": float(volatility * 2 * 100),
                },
                "warnings": _warnings(risk_level, volatility, max_dd),
            }
        except Exception as e:
            logger.error(f"Risk assessment failed for {symbol}: {e}")
            results[symbol] = _minimal_risk(data)
    
    return results


def _max_drawdown(prices: np.ndarray) -> float:
    cummax = np.maximum.accumulate(prices)
    drawdown = (cummax - prices) / cummax
    return float(np.max(drawdown))


def _downside_risk(returns: np.ndarray) -> float:
    neg = returns[returns < 0]
    return float(np.std(neg)) if len(neg) > 0 else 0.0


def _calculate_score(vol: float, dd: float, var: float, beta: float) -> float:
    score = 0
    if vol >= 0.03: score += 30
    elif vol >= 0.02: score += 20
    elif vol >= 0.015: score += 10
    
    if dd >= 0.3: score += 30
    elif dd >= 0.2: score += 20
    elif dd >= 0.1: score += 10
    
    if abs(var) >= 0.05: score += 20
    elif abs(var) >= 0.03: score += 15
    elif abs(var) >= 0.02: score += 10
    
    if beta >= 1.5: score += 20
    elif beta >= 1.2: score += 15
    elif beta <= 0.5: score += 5
    
    return min(100, score)


def _score_to_level(score: float) -> str:
    if score >= 70: return "very_high"
    elif score >= 50: return "high"
    elif score >= 30: return "medium"
    elif score >= 15: return "low"
    else: return "very_low"


def _position_size(score: float) -> float:
    if score >= 70: return 2.0
    elif score >= 50: return 5.0
    elif score >= 30: return 10.0
    elif score >= 15: return 15.0
    else: return 20.0


def _warnings(level: str, vol: float, dd: float) -> list:
    warnings = []
    if level in ["high", "very_high"]:
        warnings.append("High risk stock. Consider smaller position size.")
    if vol > 0.03:
        warnings.append(f"High daily volatility ({vol*100:.1f}%).")
    if dd > 0.3:
        warnings.append(f"History of deep drawdowns ({dd*100:.1f}%).")
    return warnings


def _minimal_risk(data: dict) -> dict:
    return {
        "symbol": data.get("symbol", ""),
        "risk_score": 50,
        "risk_level": "medium",
        "metrics": {},
        "position_recommendation": {"max_position_size": 10.0},
        "warnings": ["Insufficient data for detailed risk assessment"],
    }
```

`app/tools/decision/portfolio.py`:

```python
"""Decision/position sizing tools. Extracted from app/agents/decision_agent.py"""

from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field


class CalculatePositionSizeInput(BaseModel):
    risk_data: dict = Field(description="Risk assessment data from assess_risk")
    scores: dict = Field(default={}, description="Optional analysis scores")


@tool(args_schema=CalculatePositionSizeInput)
def calculate_position_size(risk_data: dict, scores: dict = None) -> dict[str, Any]:
    """Calculate recommended position size based on risk assessment.
    
    Args:
        risk_data: Risk assessment from assess_risk
        scores: Optional analysis scores to refine sizing
    
    Returns:
        Position size recommendations by symbol.
    """
    results = {}
    scores = scores or {}
    
    for symbol, risk in risk_data.items():
        risk_score = risk.get("risk_score", 50)
        risk_level = risk.get("risk_level", "medium")
        max_from_risk = risk.get("position_recommendation", {}).get("max_position_size", 10.0)
        
        if risk_score >= 70: base = 2.0
        elif risk_score >= 50: base = 5.0
        elif risk_score >= 30: base = 10.0
        elif risk_score >= 15: base = 15.0
        else: base = 20.0
        
        final = min(base, max_from_risk)
        
        results[symbol] = {
            "symbol": symbol,
            "position_size": final,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "rationale": f"Based on risk score {risk_score}/100",
        }
    
    return results
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/unit/tools/test_risk_tools.py -v
```

Expected: Both tests PASS

---

## Task 9: Create Report Tool

**Files:**
- Create: `app/tools/report/generate.py`
- Test: `tests/unit/tools/test_report_tool.py`

- [ ] **Step 1: Write failing test**

`tests/unit/tools/test_report_tool.py`:

```python
import pytest


def test_generate_report():
    """Test report generation."""
    from app.tools.report.generate import generate_report
    
    data = {
        "query": "Should I buy AAPL?",
        "symbols": ["AAPL"],
        "market_data": {
            "AAPL": {"current_price": 150.0, "company_name": "Apple Inc"}
        },
        "technical_analysis": {
            "AAPL": {"sentiment": {"score": 30, "sentiment": "buy"}}
        },
        "fundamental_analysis": {
            "AAPL": {"overall_score": {"score": 65}, "recommendation": "buy"}
        },
        "sentiment_analysis": {
            "sentiment_by_symbol": {
                "AAPL": {"sentiment": "positive", "score": 25}
            }
        },
        "risk_assessment": {
            "AAPL": {"risk_level": "medium", "risk_score": 40}
        },
        "decision": {
            "AAPL": {"action": "buy", "confidence": 75}
        },
    }
    
    result = generate_report.invoke({"data": data})
    
    assert "title" in result
    assert "executive_summary" in result
    assert "sections" in result
    assert "AAPL" in result["sections"]["recommendations"]["by_symbol"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/unit/tools/test_report_tool.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement report tool**

`app/tools/report/generate.py`:

```python
"""Report generation tool. Extracted from app/agents/report_agent.py"""

from datetime import datetime
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field


class GenerateReportInput(BaseModel):
    data: dict = Field(description="All analysis data to compile into a report")


@tool(args_schema=GenerateReportInput)
def generate_report(data: dict) -> dict[str, Any]:
    """Generate a structured investment analysis report.
    
    This is the FINAL tool you should call. It compiles all analysis results
    into a comprehensive report.
    
    Args:
        data: Dictionary containing all analysis results:
            - query: Original user query
            - symbols: List of analyzed symbols
            - market_data: Market data
            - technical_analysis: Technical analysis results
            - fundamental_analysis: Fundamental analysis results
            - sentiment_analysis: Sentiment analysis results
            - risk_assessment: Risk assessment results
            - decision: Decision/sizing results
    
    Returns:
        Structured report with executive summary and sections.
    """
    query = data.get("query", "")
    symbols = data.get("symbols", [])
    
    sections = {
        "overview": _overview(data),
        "technical_analysis": _technical_section(data),
        "fundamental_analysis": _fundamental_section(data),
        "sentiment_analysis": _sentiment_section(data),
        "risk_analysis": _risk_section(data),
        "recommendations": _recommendations_section(data),
    }
    
    return {
        "title": _title(query, symbols),
        "generated_at": datetime.now().isoformat(),
        "executive_summary": _executive_summary(data, sections),
        "sections": sections,
        "metadata": {
            "symbols": symbols,
            "query": query,
        },
    }


def _title(query: str, symbols: list) -> str:
    if symbols:
        if len(symbols) == 1:
            return f"Investment Research Report: {symbols[0]}"
        return f"Investment Research Report: {', '.join(symbols[:3])}{'...' if len(symbols) > 3 else ''}"
    return "Investment Research Report"


def _overview(data: dict) -> dict:
    symbols = data.get("symbols", [])
    market = data.get("market_data", {})
    return {
        "symbols_analyzed": symbols,
        "analysis_date": datetime.now().strftime("%Y-%m-%d"),
        "market_summary": {
            s: {
                "company_name": market.get(s, {}).get("company_name"),
                "current_price": market.get(s, {}).get("current_price"),
                "sector": market.get(s, {}).get("sector"),
            }
            for s in symbols
        },
    }


def _technical_section(data: dict) -> dict:
    technical = data.get("technical_analysis", {})
    bullish = sum(1 for a in technical.values() if a.get("sentiment", {}).get("score", 0) > 20)
    bearish = sum(1 for a in technical.values() if a.get("sentiment", {}).get("score", 0) < -20)
    
    outlook = "bullish" if bullish > bearish else "bearish" if bearish > bullish else "neutral"
    
    return {
        "by_symbol": {
            s: {
                "trend": a.get("signals", {}).get("trend", "neutral"),
                "rsi": a.get("signals", {}).get("rsi", "neutral"),
                "sentiment_score": a.get("sentiment", {}).get("score", 0),
            }
            for s, a in technical.items()
        },
        "overall_outlook": outlook,
    }


def _fundamental_section(data: dict) -> dict:
    fundamental = data.get("fundamental_analysis", {})
    total = sum(a.get("overall_score", {}).get("score", 50) for a in fundamental.values())
    avg = total / len(fundamental) if fundamental else 50
    
    rating = "buy" if avg >= 65 else "hold" if avg >= 35 else "sell"
    
    return {
        "by_symbol": {
            s: {
                "overall_score": a.get("overall_score", {}).get("score", 50),
                "recommendation": a.get("recommendation", "hold"),
            }
            for s, a in fundamental.items()
        },
        "overall_rating": rating,
    }


def _sentiment_section(data: dict) -> dict:
    sentiment = data.get("sentiment_analysis", {})
    by_symbol = sentiment.get("sentiment_by_symbol", {})
    
    return {
        "by_symbol": {
            s: {
                "sentiment": a.get("sentiment", "neutral"),
                "score": a.get("score", 0),
            }
            for s, a in by_symbol.items()
        },
        "overall": sentiment.get("overall_sentiment", {}),
    }


def _risk_section(data: dict) -> dict:
    risk = data.get("risk_assessment", {})
    by_symbol = risk.get("risk_by_symbol", risk)
    
    return {
        "by_symbol": {
            s: {
                "risk_level": a.get("risk_level", "medium"),
                "risk_score": a.get("risk_score", 50),
            }
            for s, a in by_symbol.items()
        },
        "overall_risk": risk.get("overall_risk_level", "medium"),
    }


def _recommendations_section(data: dict) -> dict:
    decisions = data.get("decision", {})
    if isinstance(decisions, dict) and "decisions" in decisions:
        decisions = decisions["decisions"]
    
    return {
        "by_symbol": {
            s: {
                "action": d.get("action", "hold"),
                "confidence": d.get("confidence", 0),
            }
            for s, d in decisions.items()
        },
        "portfolio_actions": [
            {"symbol": s, "action": d["action"]}
            for s, d in decisions.items()
            if "buy" in d.get("action", "")
        ],
    }


def _executive_summary(data: dict, sections: dict) -> str:
    symbols = data.get("symbols", [])
    decisions = data.get("decision", {})
    if isinstance(decisions, dict) and "decisions" in decisions:
        decisions = decisions["decisions"]
    
    parts = []
    if len(symbols) == 1:
        parts.append(f"This report analyzes {symbols[0]} across technical, fundamental, sentiment, and risk dimensions.")
    else:
        parts.append(f"This report analyzes {len(symbols)} stocks.")
    
    if decisions:
        top = max(decisions.items(), key=lambda x: x[1].get("score", 0) if isinstance(x[1], dict) else 0)
        if isinstance(top[1], dict):
            parts.append(f"Top pick: {top[0]} ({top[1].get('action', 'hold')}) with {top[1].get('confidence', 0):.0f}% confidence.")
    
    risk = sections.get("risk_analysis", {})
    parts.append(f"Overall risk level: {risk.get('overall_risk', 'medium')}.")
    
    tech = sections.get("technical_analysis", {})
    parts.append(f"Technical outlook: {tech.get('overall_outlook', 'neutral')}.")
    
    return " ".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/unit/tools/test_report_tool.py -v
```

Expected: PASS

---

## Task 10: Register All Tools (Lazy)

**Files:**
- Modify: `app/tools/__init__.py`

- [ ] **Step 1: Update tools __init__ with lazy registration**

`app/tools/__init__.py`:

```python
"""Tool registry and tools for the ReAct agent."""

from app.tools.registry import get_all_tools, get_tool, register_tool

__all__ = ["get_all_tools", "get_tool", "register_tool", "register_all_tools"]


def register_all_tools() -> None:
    """Register all available tools. Call this during agent initialization."""
    from app.tools.data.market_data import fetch_stock_data
    from app.tools.data.historical import get_historical_prices
    from app.tools.analysis.technical import analyze_technical
    from app.tools.analysis.fundamental import analyze_fundamental
    from app.tools.analysis.sentiment import analyze_sentiment
    from app.tools.risk.assessment import assess_risk
    from app.tools.decision.portfolio import calculate_position_size
    from app.tools.report.generate import generate_report
    
    register_tool(fetch_stock_data)
    register_tool(get_historical_prices)
    register_tool(analyze_technical)
    register_tool(analyze_fundamental)
    register_tool(analyze_sentiment)
    register_tool(assess_risk)
    register_tool(calculate_position_size)
    register_tool(generate_report)
```

- [ ] **Step 2: Verify all tools are registered**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run python -c "
from app.tools import register_all_tools, get_all_tools
register_all_tools()
tools = get_all_tools()
print(f'Registered {len(tools)} tools:')
for t in tools:
    print(f'  - {t.name}')
"
```

Expected: 8 tools listed.

---

## Task 11: Create ReAct Agent Core

**Files:**
- Create: `app/react_agent/react_agent.py`
- Test: `tests/unit/react_agent/test_graph.py`

- [ ] **Step 1: Write failing test**

`tests/unit/react_agent/test_graph.py`:

```python
import pytest


def test_build_react_graph_returns_callable():
    """The graph builder must return a compiled graph."""
    from app.react_agent.react_agent import build_react_graph
    
    graph = build_react_graph()
    assert callable(graph.ainvoke)


def test_agent_reason_decision_routing():
    """agent_reason must route to tool_execute or finish."""
    from app.react_agent.react_agent import _agent_reason_decision
    
    # State with no tool calls -> finish
    from langchain_core.messages import AIMessage
    state_no_tools = {"messages": [AIMessage(content="Done")]}
    assert _agent_reason_decision(state_no_tools) == "finish"


def test_reflect_decision_max_iterations():
    """reflect must finish when max iterations reached."""
    from app.react_agent.react_agent import _reflect_decision
    
    state = {"iteration": 15, "max_iterations": 15, "final_answer": None}
    assert _reflect_decision(state) == "finish"
    
    state = {"iteration": 14, "max_iterations": 15, "final_answer": None}
    assert _reflect_decision(state) == "continue"


def test_reflect_decision_with_final_answer():
    """reflect must finish if final_answer is set."""
    from app.react_agent.react_agent import _reflect_decision
    
    state = {"iteration": 5, "max_iterations": 15, "final_answer": "Buy AAPL"}
    assert _reflect_decision(state) == "finish"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/unit/react_agent/test_graph.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement react_agent.py**

`app/react_agent/react_agent.py`:

```python
"""ReAct agent implementation using LangGraph.

Graph: agent_reason -> [tool_execute | END] -> observe -> reflect -> [agent_reason | END]
"""

import json
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from app.config import settings
from app.react_agent.prompts import REASONING_SYSTEM_PROMPT, format_reflection_prompt
from app.react_agent.state import ReActState, create_initial_react_state
from app.tools import get_all_tools, get_tool, register_all_tools
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Cached LLM instances
_reasoning_llm: ChatOpenAI | None = None
_reflection_llm: ChatOpenAI | None = None


def _get_reasoning_llm() -> ChatOpenAI:
    """Get cached LLM for reasoning (agent_reason node)."""
    global _reasoning_llm
    if _reasoning_llm is None:
        _reasoning_llm = ChatOpenAI(
            model=settings.agent_reasoning_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout,
            openai_api_key=settings.zhipuai_api_key,
            openai_api_base="https://open.bigmodel.cn/api/paas/v4/",
        )
    return _reasoning_llm


def _get_reflection_llm() -> ChatOpenAI:
    """Get cached LLM for reflection (cheaper model)."""
    global _reflection_llm
    if _reflection_llm is None:
        _reflection_llm = ChatOpenAI(
            model=settings.agent_reflection_model,
            temperature=0.1,
            max_tokens=500,
            timeout=settings.llm_timeout,
            openai_api_key=settings.zhipuai_api_key,
            openai_api_base="https://open.bigmodel.cn/api/paas/v4/",
        )
    return _reflection_llm


def build_react_graph():
    """Build and compile the ReAct StateGraph."""
    # Ensure tools are registered
    register_all_tools()
    
    graph = StateGraph(ReActState)
    
    graph.add_node("agent_reason", agent_reason_node)
    graph.add_node("tool_execute", tool_execute_node)
    graph.add_node("observe", observe_node)
    graph.add_node("reflect", reflect_node)
    
    graph.set_entry_point("agent_reason")
    
    graph.add_conditional_edges("agent_reason", _agent_reason_decision)
    graph.add_edge("tool_execute", "observe")
    graph.add_edge("observe", "reflect")
    graph.add_conditional_edges("reflect", _reflect_decision)
    
    return graph.compile()


def agent_reason_node(state: ReActState) -> dict[str, Any]:
    """The agent reasons and decides the next action."""
    iteration = state.get("iteration", 0)
    messages = list(state.get("messages", []))
    
    # Add system prompt if first iteration
    if iteration == 0:
        messages = [SystemMessage(content=REASONING_SYSTEM_PROMPT)] + messages
    
    # Bind tools to LLM
    llm = _get_reasoning_llm()
    tools = get_all_tools()
    llm_with_tools = llm.bind_tools(tools)
    
    # Get LLM response
    response = llm_with_tools.invoke(messages)
    
    return {
        "messages": [response],
        "iteration": iteration + 1,
    }


def _agent_reason_decision(state: ReActState) -> Literal["tool_execute", "finish"]:
    """Decide whether to execute a tool or finish."""
    messages = state.get("messages", [])
    if not messages:
        return "finish"
    
    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tool_execute"
    
    return "finish"


def tool_execute_node(state: ReActState) -> dict[str, Any]:
    """Execute the tool called by the agent."""
    messages = state.get("messages", [])
    last_message = messages[-1]
    
    if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
        return {}
    
    tool_results = []
    tool_calls = last_message.tool_calls
    tools_used = list(state.get("tools_used", []))
    tool_call_history = list(state.get("tool_call_history", []))
    errors = list(state.get("errors", []))
    
    for tool_call in tool_calls:
        tool_name = tool_call.get("name", "")
        tool_args = tool_call.get("args", {})
        tool_id = tool_call.get("id", "")
        
        tools_used.append(tool_name)
        tool_call_history.append({"tool": tool_name, "args": tool_args})
        
        tool = get_tool(tool_name)
        if not tool:
            error_msg = f"Tool '{tool_name}' not found."
            tool_results.append(ToolMessage(content=error_msg, tool_call_id=tool_id, name=tool_name))
            errors.append({
                "agent": "react_agent",
                "error_type": "ToolNotFound",
                "message": error_msg,
            })
        else:
            try:
                # Use ainvoke for async tools, to_thread for sync tools
                import asyncio
                if hasattr(tool, "coroutine") and tool.coroutine:
                    result = asyncio.run(tool.ainvoke(tool_args))
                else:
                    result = tool.invoke(tool_args)
                tool_results.append(ToolMessage(content=str(result), tool_call_id=tool_id, name=tool_name))
            except Exception as e:
                error_msg = f"Error executing {tool_name}: {str(e)}"
                tool_results.append(ToolMessage(content=error_msg, tool_call_id=tool_id, name=tool_name))
                errors.append({
                    "agent": "react_agent",
                    "error_type": "ToolExecutionError",
                    "message": error_msg,
                })
    
    return {
        "messages": tool_results,
        "tools_used": tools_used,
        "tool_call_history": tool_call_history,
        "errors": errors,
    }


def observe_node(state: ReActState) -> dict[str, Any]:
    """Format observations from tool results.
    
    Tool results are already formatted as ToolMessages which the LLM can read.
    This node is a placeholder for any additional observation processing.
    """
    return {}


def reflect_node(state: ReActState) -> dict[str, Any]:
    """Evaluate progress and decide whether to continue or finish."""
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 15)
    tools_used = state.get("tools_used", [])
    query = state.get("query", "")
    messages = list(state.get("messages", []))
    
    # Hard limit: max iterations
    if iteration >= max_iterations:
        logger.info(f"Max iterations ({max_iterations}) reached, finishing")
        return {
            "final_answer": "Analysis reached maximum iterations. Here's what was found: " + 
                           _extract_findings_from_messages(messages),
        }
    
    # Check for repetition (same tool called twice with same args)
    tool_calls = []
    for msg in messages:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append((tc.get("name"), json.dumps(tc.get("args", {}), sort_keys=True)))
    
    if len(tool_calls) >= 2 and tool_calls[-1] == tool_calls[-2]:
        logger.info("Repeated tool call detected, forcing finish")
        return {
            "messages": [HumanMessage(content="Analysis complete. Please provide your final answer.")],
        }
    
    # Cost check
    cost = state.get("accumulated_cost", 0)
    if cost >= settings.agent_cost_limit:
        logger.info(f"Cost limit (${cost}) reached, finishing")
        return {
            "final_answer": f"Analysis stopped due to cost limit (${cost}). Partial results available.",
        }
    
    # Use reflection LLM to evaluate
    reflection_prompt = format_reflection_prompt(
        iteration=iteration,
        max_iterations=max_iterations,
        tools_used=tools_used,
        query=query,
    )
    
    reflect_llm = _get_reflection_llm()
    reflection_messages = messages + [HumanMessage(content=reflection_prompt)]
    
    try:
        response = reflect_llm.invoke(reflection_messages)
        content = response.content
        
        # Parse JSON from response
        try:
            if "{" in content and "}" in content:
                start = content.find("{")
                end = content.rfind("}") + 1
                decision = json.loads(content[start:end])
                
                if decision.get("decision") == "finish":
                    return {}
                elif decision.get("decision") == "error":
                    return {
                        "final_answer": f"Error: {decision.get('reasoning', 'Analysis could not be completed')}",
                    }
                guidance = decision.get("guidance", "")
                if guidance:
                    return {"messages": [HumanMessage(content=f"Guidance: {guidance}")]}
        except json.JSONDecodeError:
            pass
    except Exception as e:
        logger.warning(f"Reflection failed: {e}, continuing")
    
    # Default: continue
    return {}


def _reflect_decision(state: ReActState) -> Literal["continue", "finish", "error"]:
    """Route based on reflection result."""
    final_answer = state.get("final_answer")
    if final_answer is not None:
        return "finish"
    
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 15)
    if iteration >= max_iterations:
        return "finish"
    
    return "continue"


def _extract_findings_from_messages(messages: list) -> str:
    """Extract key findings from message history for max-iteration fallback."""
    findings = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            findings.append(f"{msg.name}: {msg.content[:200]}")
    return "; ".join(findings[:3]) if findings else "No findings available."


class ReActAgent:
    """ReAct autonomous agent for stock analysis."""
    
    def __init__(self):
        self.graph = build_react_graph()
    
    async def analyze(self, query: str, symbols: list[str], thread_id: str) -> dict[str, Any]:
        """Run the ReAct agent to analyze stocks.
        
        Args:
            query: User query
            symbols: Stock symbols
            thread_id: Unique thread identifier
        
        Returns:
            Final analysis result
        """
        initial_state = create_initial_react_state(
            query=query,
            symbols=symbols,
            thread_id=thread_id,
        )
        
        result = await self.graph.ainvoke(initial_state)
        
        return {
            "answer": result.get("final_answer", ""),
            "report": result.get("report"),
            "iterations": result.get("iteration", 0),
            "tools_used": result.get("tools_used", []),
            "cost": result.get("accumulated_cost", 0),
        }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/unit/react_agent/test_graph.py -v
```

Expected: All 4 tests PASS

---

## Task 12: Create Agent API Routes

**Files:**
- Create: `app/api/routes/agent.py`
- Test: `tests/integration/test_agent_routes.py`

- [ ] **Step 1: Write failing test**

`tests/integration/test_agent_routes.py`:

```python
import pytest
from fastapi.testclient import TestClient


def test_agent_analyze_endpoint_returns_thread_id():
    """The agent analyze endpoint must return a thread_id."""
    from app.main import app
    
    client = TestClient(app)
    response = client.post("/api/agent/analyze", json={
        "query": "Should I buy AAPL?",
        "symbols": ["AAPL"],
    })
    
    assert response.status_code == 200
    data = response.json()
    assert "thread_id" in data
    assert data["status"] == "processing"


def test_agent_result_not_found():
    """Getting a non-existent result must return 404."""
    from app.main import app
    
    client = TestClient(app)
    response = client.get("/api/agent/result/nonexistent")
    
    assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/integration/test_agent_routes.py -v
```

Expected: 404 for `/api/agent/analyze` or import error

- [ ] **Step 3: Implement agent API routes**

`app/api/routes/agent.py`:

```python
"""API routes for the ReAct agent."""

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.react_agent.react_agent import ReActAgent
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])

# In-memory result store (replace with database in production)
_results: dict[str, dict[str, Any]] = {}


class AnalyzeRequest(BaseModel):
    query: str = Field(description="User query")
    symbols: list[str] = Field(description="Stock symbols to analyze")
    max_iterations: int = Field(default=15, ge=1, le=50)


class AnalyzeResponse(BaseModel):
    thread_id: str
    status: str


class ResultResponse(BaseModel):
    answer: str
    report: dict | None
    iterations: int
    tools_used: list[str]
    cost: float


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
):
    """Start an autonomous stock analysis.
    
    The agent will autonomously fetch data, analyze, and generate a report.
    """
    thread_id = str(uuid.uuid4())
    
    background_tasks.add_task(
        _run_analysis,
        thread_id=thread_id,
        query=request.query,
        symbols=request.symbols,
        max_iterations=request.max_iterations,
    )
    
    return AnalyzeResponse(thread_id=thread_id, status="processing")


@router.get("/result/{thread_id}", response_model=ResultResponse)
async def get_result(thread_id: str):
    """Get the result of an analysis."""
    result = _results.get(thread_id)
    
    if not result:
        raise HTTPException(status_code=404, detail="Analysis not found or still processing")
    
    return ResultResponse(**result)


async def _run_analysis(
    thread_id: str,
    query: str,
    symbols: list[str],
    max_iterations: int,
):
    """Run the analysis in the background."""
    try:
        agent = ReActAgent()
        result = await agent.analyze(
            query=query,
            symbols=symbols,
            thread_id=thread_id,
        )
        _results[thread_id] = result
        logger.info(f"Analysis complete for {thread_id}: {result['iterations']} iterations")
    except Exception as e:
        logger.error(f"Analysis failed for {thread_id}: {e}")
        _results[thread_id] = {
            "answer": f"Analysis failed: {str(e)}",
            "report": None,
            "iterations": 0,
            "tools_used": [],
            "cost": 0,
        }
```

- [ ] **Step 4: Wire into main.py**

Add to `app/main.py` (find existing router imports and add):

```python
from app.api.routes.agent import router as agent_router
```

Find existing `app.include_router` calls and add:

```python
app.include_router(agent_router, prefix="/api")
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/integration/test_agent_routes.py -v
```

Expected: Both tests PASS

---

## Task 13: Integration Tests

**Files:**
- Create: `tests/integration/test_react_agent.py`

- [ ] **Step 1: Write integration test**

`tests/integration/test_react_agent.py`:

```python
import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.asyncio
async def test_react_agent_with_mock_llm():
    """Test the full ReAct loop with a mock LLM."""
    from app.react_agent.react_agent import ReActAgent
    from app.react_agent.state import create_initial_react_state
    
    agent = ReActAgent()
    
    # Mock the LLM to simulate a simple tool call then finish
    mock_llm = MagicMock()
    
    # First call: tool call (fetch_stock_data)
    mock_response_1 = MagicMock()
    mock_response_1.tool_calls = [{
        "name": "fetch_stock_data",
        "args": {"symbols": ["AAPL"]},
        "id": "call_1",
    }]
    
    # Second call: finish (no tool calls)
    mock_response_2 = MagicMock()
    mock_response_2.tool_calls = []
    mock_response_2.content = "Based on the data, AAPL looks like a strong buy."
    
    mock_llm.bind_tools.return_value.invoke.side_effect = [mock_response_1, mock_response_2]
    
    with patch("app.react_agent.react_agent._get_reasoning_llm", return_value=mock_llm):
        state = create_initial_react_state(
            query="Should I buy AAPL?",
            symbols=["AAPL"],
            thread_id="test-123",
        )
        
        # Mock tool execution to avoid real API calls
        with patch("app.react_agent.react_agent.get_tool") as mock_get_tool:
            mock_tool = MagicMock()
            mock_tool.invoke.return_value = {"AAPL": {"market_data": {"current_price": 150.0}}}
            mock_get_tool.return_value = mock_tool
            
            result = await agent.graph.ainvoke(state)
    
    assert result["iteration"] > 0


def test_max_iteration_guard():
    """Test that the agent stops at max iterations."""
    from app.react_agent.react_agent import _reflect_decision
    
    state = {"iteration": 15, "max_iterations": 15, "final_answer": None}
    assert _reflect_decision(state) == "finish"
    
    state = {"iteration": 14, "max_iterations": 15, "final_answer": None}
    assert _reflect_decision(state) == "continue"


def test_repetition_detection():
    """Test that repeated tool calls force finish."""
    from app.react_agent.react_agent import reflect_node
    
    # Mock messages with repeated tool calls
    mock_msg = MagicMock()
    mock_msg.tool_calls = [{"name": "fetch_stock_data", "args": {"symbols": ["AAPL"]}}]
    
    state = {
        "iteration": 3,
        "max_iterations": 15,
        "tools_used": ["fetch_stock_data"],
        "query": "test",
        "messages": [mock_msg, mock_msg],  # Same tool call twice
    }
    
    result = reflect_node(state)
    
    # Should force finish by returning a guidance message
    assert "messages" in result
```

- [ ] **Step 2: Run integration tests**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/integration/test_react_agent.py -v
```

Expected: Tests PASS (may need adjustment based on actual implementation)

---

## Task 14: Run Full Test Suite

- [ ] **Step 1: Run all tests**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/ -v --tb=short
```

Expected: All new tests PASS. Existing tests should not be affected.

- [ ] **Step 2: Check test coverage**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run pytest tests/ --cov=app.react_agent --cov=app.tools --cov-report=term-missing
```

Expected: New code coverage should be 80%+

---

## Task 15: Final Verification

- [ ] **Step 1: Test the API endpoint**

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents && poetry run uvicorn app.main:app --reload &
sleep 3
curl -X POST http://localhost:8000/api/agent/analyze \
  -H "Content-Type: application/json" \
  -d '{"query": "Analyze AAPL", "symbols": ["AAPL"]}'
```

Expected: Returns `{"thread_id": "...", "status": "processing"}`

- [ ] **Step 2: Verify backward compatibility**

```bash
curl -X POST http://localhost:8000/api/analysis/analyze \
  -H "Content-Type: application/json" \
  -d '{"query": "Analyze AAPL", "symbols": ["AAPL"]}'
```

Expected: Old endpoint still works (returns thread_id)

- [ ] **Step 3: Stop dev server**

```bash
pkill -f "uvicorn app.main:app"
```

---

## Summary

This plan implements the ReAct agent in 15 tasks:

1. **Foundation** (Tasks 1-4): Directory structure, config, state, prompts
2. **Tools** (Tasks 5-9): Registry + 8 tools extracted from existing agents
3. **Agent Core** (Tasks 10-11): Tool registration + ReAct graph with cached LLMs
4. **API** (Tasks 12-13): New endpoints wired into FastAPI
5. **Testing** (Tasks 13-15): Unit, integration, and full suite tests

All tasks follow TDD: write failing test → implement → verify pass. The existing workflow remains untouched — the new agent runs alongside it.
