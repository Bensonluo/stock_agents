# ReAct Agent Design: Transforming Stock Agents from Workflow to Autonomous Agent

**Date**: 2026-04-30
**Status**: Approved
**Approach**: Custom ReAct StateGraph with LangGraph

## Problem

The current system is a fixed sequential pipeline (`data -> technical -> sentiment -> fundamental -> risk -> decision -> report`). Every request follows the same path regardless of query complexity. Agents have no autonomy — they are pure functions with no ability to reason, choose tools, skip unnecessary steps, or iterate on results. The LLM is used only for optional text generation, not for core reasoning.

## Solution

Replace the fixed pipeline with a single autonomous ReAct agent that uses GLM-4.7 as its reasoning engine. The agent decides which tools to call, in what order, and when to stop — driven by reasoning, not hardcoded edges.

## Architecture

### Directory Structure

```
app/
  react_agent/
    __init__.py
    react_agent.py          # Main ReAct agent (replaces orchestrator.py)
    state.py                # ReAct agent state (extends AgentState)
    prompts.py              # System prompt, tool descriptions, reflection prompts
  tools/
    __init__.py
    registry.py             # Tool registry
    data/
      market_data.py        # Fetch stock data (from DataCollectionAgent + AkShareDataAgent)
    analysis/
      technical.py          # Technical indicators (from TechnicalAnalysisAgent)
      fundamental.py        # Fundamental scoring (from FundamentalAnalysisAgent)
      sentiment.py          # Sentiment analysis (from SentimentAnalysisAgent)
    risk/
      assessment.py         # Risk metrics (from RiskAssessmentAgent)
    decision/
      portfolio.py          # Decision/position sizing (from DecisionMakingAgent)
    report/
      generate.py           # Report generation (from ReportGenerationAgent)
```

Note: `app/react_agent/` (singular) is distinct from `app/agents/` (plural) to avoid import confusion.

### Agent State

`ReActState` **extends** the existing `AgentState` rather than replacing it. All existing fields are preserved for backward compatibility with the checkpoint system and database serialization.

```python
class ReActState(AgentState):
    # ReAct Loop (new fields)
    messages: Annotated[list[BaseMessage], add]  # Full conversation history
    iteration: int
    max_iterations: int  # Safety limit (default: 15)
    
    # Tool tracking (new fields)
    tools_used: Annotated[list[str], add]  # Track which tools were called
    tool_call_history: Annotated[list[dict], add]  # Tool name + args per call
    
    # Final output (new fields)
    final_answer: str | None
    
    # Cost tracking (new fields)
    accumulated_cost: float  # USD cost estimate
    accumulated_tokens: dict  # {input: int, output: int}
```

The existing fields (`market_data`, `financial_data`, `news_data`, `technical_analysis`, `fundamental_analysis`, `sentiment_analysis`, `risk_assessment`, `decision`, `report`, `agent_outputs`, `errors`, `agent_status`, `execution_metadata`) are all preserved.

### ReAct Graph

```
ENTRY -> agent_reason (LLM decides: use tool OR finish)
              | tool_call                | finish
         tool_execute              -> END (return answer)
              |
         observe (format result)
              |
         reflect (LLM evaluates quality, decides next step)
              | need_more      | satisfied
         agent_reason        -> END
```

Nodes:
- **agent_reason**: Sends conversation + system prompt to GLM. Returns tool call or final answer.
- **tool_execute**: Executes the chosen tool function (async), catches errors, returns result.
- **observe**: Formats tool result or error into a human-readable observation for the conversation.
- **reflect**: Evaluates whether analysis is complete and thorough. Returns continue/finish/error.

Conditional edges:
- `agent_reason` -> `"tool_call"` goes to `tool_execute`, `"finish"` goes to END.
- `reflect` -> `"continue"` goes back to `agent_reason`, `"finish"` goes to END, `"error"` goes to END.

### LLM Integration

GLM models are accessed via **ZhipuAI's OpenAI-compatible API** using `langchain-openai`'s `ChatOpenAI`:

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="glm-5.2",
    temperature=0.3,
    max_tokens=2000,
    openai_api_key=settings.zhipuai_api_key,
    openai_api_base="https://open.bigmodel.cn/api/paas/v4/",
)
```

ZhipuAI's API supports OpenAI-style function/tool calling natively. The agent uses LangGraph's `bind_tools()` to attach the tool registry, and GLM returns structured tool call JSON matching the OpenAI schema. No additional `langchain-zhipuai` package is needed.

**Model routing strategy** (cost control):
- `agent_reason` (complex reasoning): `glm-5.2`
- `reflect` (simple evaluation): `glm-5.2` (faster, cheaper)
- This is configurable via `settings` and can be overridden per-query.

### Tools

Each tool is an **async** LangChain `@tool` function with Pydantic-typed arguments:

```python
from langchain_core.tools import tool
from pydantic import BaseModel, Field

class FetchStockDataInput(BaseModel):
    symbols: list[str] = Field(description="Stock ticker symbols")
    source: str = Field(default="auto", description="Data source: yfinance, akshare, or auto")

@tool(args_schema=FetchStockDataInput)
async def fetch_stock_data(symbols: list[str], source: str = "auto") -> dict:
    """Fetch real-time and historical stock market data. ..."""
    # async implementation
```

| Tool | Source | Purpose | Async |
|---|---|---|---|
| `fetch_stock_data` | DataCollectionAgent + AkShareDataAgent | Market data, financials, news | Yes |
| `analyze_technical` | TechnicalAnalysisAgent | RSI, MACD, Bollinger, support/resistance | Yes |
| `analyze_fundamental` | FundamentalAnalysisAgent | PE/PB/ROE, profitability, valuation | Yes |
| `analyze_sentiment` | SentimentAnalysisAgent | News sentiment (keyword + optional LLM) | Yes |
| `assess_risk` | RiskAssessmentAgent | Volatility, VaR, max drawdown, risk score | Yes |
| `calculate_position_size` | DecisionMakingAgent | Risk-based position sizing | Yes |
| `generate_report` | ReportGenerationAgent | Structured analysis report | Yes |
| `get_historical_prices` | New | Price history for a time range | Yes |

Tools are fine-grained so the agent can selectively run only what's needed. Tool descriptions are detailed to help GLM decide when each tool is appropriate.

### Tool Error Handling

Tools are wrapped with existing resilience patterns:

```python
from app.resilience import with_retry, with_circuit_breaker, with_timeout

@with_circuit_breaker("fetch_stock_data")
@with_retry(max_retries=3)
@with_timeout(seconds=60)
@tool(args_schema=FetchStockDataInput)
async def fetch_stock_data(...) -> dict:
    ...
```

In the `tool_execute` node:
1. Try/catch around each tool invocation
2. On failure, format error as a structured error observation (not a crash)
3. Record error in `state.errors` using `add_error()`
4. The `observe` node distinguishes success observations from error observations
5. The `reflect` node decides whether to retry, skip, or abort based on the error

### Tool Input Validation

Each tool uses Pydantic schema validation via LangChain's `@tool(args_schema=...)`. Invalid arguments return a structured error message that the agent can reason about and retry with corrected inputs.

Additionally, tools validate:
- Symbol format (6-digit for CN, standard ticker for US)
- Date range validity for historical data queries
- Numeric bounds (e.g., `max_results` must be positive)

### Reasoning & Reflection

**System prompt** (versioned) gives GLM its identity, available tools, reasoning approach, and rules:
1. Understand the user's query — what do they need?
2. Fetch relevant data first
3. Apply appropriate analysis tools based on the data and query
4. Evaluate results — is the analysis thorough enough?
5. If gaps exist, gather more data or run additional analysis
6. When satisfied, generate a final report

**Reflection logic** prevents infinite loops and ensures quality:
- **Max iterations guard**: Hard stop at `max_iterations` (default: 15)
- **Completeness check**: Has the agent covered the user's question?
- **Repetition detection**: If the agent calls the same tool with same args twice, reflection forces it to move on
- **Minimum analysis**: If no analysis tool has been called yet, reflection says "continue"
- **Error count limit**: After 3 consecutive tool failures, reflection routes to END with error status
- **Cost guard**: If `accumulated_cost` exceeds a threshold (e.g., $0.50), reflection routes to END

**Prompt versioning**: System prompts have version identifiers (e.g., `v1.0.0`) stored in `execution_metadata`. This enables A/B testing and reproducibility.

### Cost Control

| Mechanism | Implementation |
|---|---|
| Token budget | Max 10k input + 2k output tokens per LLM call |
| Cost tracking | `accumulated_cost` and `accumulated_tokens` tracked in state |
| Model routing | `glm-5.2` for reasoning, `glm-5.2` for reflection |
| Hard limit | Query aborted if cost exceeds configurable threshold |
| Alert | Log warning when query exceeds 80% of budget |

### WebSocket Events

ReAct step events map to the existing WebSocket infrastructure:

| Event | When | Payload |
|---|---|---|
| `react_start` | Agent begins reasoning | `{ thread_id, query, max_iterations }` |
| `react_step` | After each iteration | `{ thread_id, iteration, step_type, tool_name? }` |
| `tool_call` | Tool is invoked | `{ thread_id, tool_name, args }` |
| `tool_result` | Tool returns | `{ thread_id, tool_name, success, duration_ms }` |
| `reflect_result` | Reflection completes | `{ thread_id, decision, guidance }` |
| `react_finish` | Agent completes | `{ thread_id, iterations_used, tools_used, status }` |
| `react_error` | Agent errors out | `{ thread_id, error, iteration }` |

These map to existing monitoring APIs: `update_agent_status()`, `add_log()`.

### API

New endpoints (no breaking changes to existing API):

```
POST /api/agent/analyze
  Body: { "query": "Should I buy AAPL?", "symbols": ["AAPL"], "max_iterations": 15 }
  Response: { "thread_id": "...", "status": "processing" }

GET /api/agent/result/{thread_id}
  Response: { "answer": "...", "report": {...}, "iterations": 8, "tools_used": [...], "cost": 0.12 }
```

Existing `/api/analysis/analyze` continues to work via legacy orchestrator.

### Preserved Infrastructure

| Component | Status |
|---|---|
| `app/monitoring/` | Kept — agent emits same events |
| `app/resilience/` | Kept — tools wrapped with circuit breaker, retry, timeout |
| `app/api/websocket/` | Kept — broadcasts ReAct step events |
| `app/storage/database.py` | Kept — saves analysis results |
| `app/config.py` | Kept — add `agent_max_iterations`, `agent_cost_limit` settings |
| `app/utils/` | Kept as-is |

### Deprecated (Not Deleted)

| Component | Status |
|---|---|
| `app/agents/base.py` | Deprecated — tools replace agent pattern |
| `app/agents/*.py` | Deprecated — logic extracted into `app/tools/` |
| `app/orchestration/orchestrator.py` | Deprecated — replaced by `app/react_agent/react_agent.py` |
| `app/orchestration/workflow.py` | Deprecated — replaced by new graph builder |

Old code stays but is no longer the active path.

### Migration Strategy

1. Build `app/react_agent/` and `app/tools/` alongside existing code
2. Add `/api/agent/` endpoints
3. Extract computation logic from old agents into tools (copy core logic, no rewrites)
4. Test new agent independently
5. Once validated, switch default and deprecate old pipeline

### Testing Strategy

| Test Type | Scope | Approach |
|---|---|---|
| **Unit tests** | Each tool | Mock data sources, test computation logic in isolation |
| **Graph structure** | Graph nodes/edges | Verify `StateGraph` has correct topology |
| **Mock LLM routing** | `agent_reason` node | Pre-programmed LLM responses that return specific tool calls or finish |
| **Integration tests** | End-to-end agent | Fixed seed/prompts, verify deterministic tool selection for known queries |
| **Iteration guard** | Max iterations | Mock LLM that always returns tool calls → verify hard stop at `max_iterations` |
| **Repetition detection** | `reflect` node | Mock LLM that repeats same tool call → verify reflection forces finish |
| **Error handling** | Tool failures | Mock tools that always fail → verify error observation + eventual END |
| **Cost tracking** | Budget enforcement | Set low cost limit → verify agent stops before exceeding |

### Future Expansion

- **Sub-agents**: `reflect` node can spawn specialized sub-agents for complex tasks
- **Human-in-the-loop**: Add `"pause"` route in reflection that waits for user input
- **Dynamic tool registration**: New tools registered at runtime
- **Multi-agent**: Tools can become their own ReAct agents for deeper analysis

## Constraints

- **LLM**: ZhipuAI GLM-4.7 via OpenAI-compatible API (`ChatOpenAI` with ZhipuAI base URL)
- **Framework**: LangGraph (keep existing framework)
- **Topology**: Single agent + tools (designed for future sub-agent expansion)
- **Backward compatible**: Existing API endpoints and database schema must continue working
