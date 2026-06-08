"""ReAct agent implementation using LangGraph.

Graph: agent_reason -> [tool_execute | END] -> observe -> reflect -> [agent_reason | END]
"""

import asyncio
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

_reasoning_llm: ChatOpenAI | None = None
_reflection_llm: ChatOpenAI | None = None

ZHIPU_API_BASE = "https://open.bigmodel.cn/api/coding/paas/v4/"


def _get_reasoning_llm() -> ChatOpenAI:
    global _reasoning_llm
    if _reasoning_llm is None:
        _reasoning_llm = ChatOpenAI(
            model=settings.agent_reasoning_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout,
            openai_api_key=settings.zhipuai_api_key,
            openai_api_base=ZHIPU_API_BASE,
        )
    return _reasoning_llm


def _get_reflection_llm() -> ChatOpenAI:
    global _reflection_llm
    if _reflection_llm is None:
        _reflection_llm = ChatOpenAI(
            model=settings.agent_reflection_model,
            temperature=0.1,
            max_tokens=500,
            timeout=settings.llm_timeout,
            openai_api_key=settings.zhipuai_api_key,
            openai_api_base=ZHIPU_API_BASE,
        )
    return _reflection_llm


def build_react_graph():
    register_all_tools()
    graph = StateGraph(ReActState)

    graph.add_node("agent_reason", agent_reason_node)
    graph.add_node("tool_execute", tool_execute_node)
    graph.add_node("observe", observe_node)
    graph.add_node("reflect", reflect_node)

    graph.set_entry_point("agent_reason")
    # Update the graph: agent_reason now always goes to tool_execute or reflect
    graph.add_conditional_edges("agent_reason", _agent_reason_decision)
    graph.add_edge("tool_execute", "observe")
    graph.add_edge("observe", "reflect")
    graph.add_conditional_edges("reflect", _reflect_decision)

    return graph.compile()


def agent_reason_node(state: ReActState) -> dict[str, Any]:
    iteration = state.get("iteration", 0)
    messages = list(state.get("messages", []))

    if iteration == 0:
        query = state.get("query", "")
        symbols = state.get("symbols", [])
        user_msg = HumanMessage(content=f"Query: {query}\nSymbols: {', '.join(symbols)}")
        messages = [SystemMessage(content=REASONING_SYSTEM_PROMPT), user_msg]

    llm = _get_reasoning_llm()
    tools = get_all_tools()
    llm_with_tools = llm.bind_tools(tools)
    compact_messages = _truncate_messages_for_reasoning(messages)
    response = llm_with_tools.invoke(compact_messages)

    return {"messages": [response], "iteration": iteration + 1}


def _agent_reason_decision(state: ReActState) -> Literal["tool_execute", "reflect"]:
    messages = state.get("messages", [])
    if not messages:
        return "reflect"
    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tool_execute"
    # No tool calls → go to reflect instead of END,
    # so reflect can decide whether to continue or finish.
    return "reflect"


async def tool_execute_node(state: ReActState) -> dict[str, Any]:
    messages = state.get("messages", [])
    last_message = messages[-1]

    if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
        return {}

    tool_result_messages: list[ToolMessage] = []
    tool_calls = last_message.tool_calls
    tools_used = list(state.get("tools_used", []))
    tool_call_history = list(state.get("tool_call_history", []))
    errors = list(state.get("errors", []))

    # Read-modify-write tool_results so we return the FULL dict and the
    # `merge_dicts` reducer doesn't lose prior tool results (and so the
    # manual-merge in `ReActAgent.analyze()` doesn't drop them either).
    accumulated_tool_results: dict[str, Any] = dict(state.get("tool_results") or {})

    for tool_call in tool_calls:
        tool_name = tool_call.get("name", "")
        tool_args = tool_call.get("args", {})
        tool_id = tool_call.get("id", "")

        tools_used.append(tool_name)
        tool_call_history.append({"tool": tool_name, "args": tool_args})

        # Special handling: generate_report requires state-aware data assembly.
        # The LLM has no way to know what's in state, so build args from state.
        if tool_name == "generate_report":
            tool_args = {"data": _build_report_data(state)}

        tool = get_tool(tool_name)
        if not tool:
            error_msg = f"Tool '{tool_name}' not found."
            tool_result_messages.append(
                ToolMessage(content=error_msg, tool_call_id=tool_id, name=tool_name)
            )
            errors.append({
                "agent": "react_agent", "error_type": "ToolNotFound", "message": error_msg,
            })
            continue

        try:
            result = await tool.ainvoke(tool_args)
        except Exception as e:
            error_msg = f"Error executing {tool_name}: {str(e)}"
            tool_result_messages.append(
                ToolMessage(content=error_msg, tool_call_id=tool_id, name=tool_name)
            )
            errors.append({
                "agent": "react_agent", "error_type": "ToolExecutionError", "message": error_msg,
            })
            continue

        tool_result_messages.append(
            ToolMessage(content=str(result), tool_call_id=tool_id, name=tool_name)
        )

        # Index result by symbol. Two shapes are possible:
        #   (a) `{"symbol": "AAPL", "indicators": ...}` — single-symbol tools
        #       (analyze_technical, analyze_fundamental, analyze_sentiment,
        #        assess_risk) — wrap as bucket["AAPL"] = result.
        #   (b) `{"AAPL": {...}, "MSFT": {...}}` — multi-symbol tools
        #       (fetch_stock_data_tool, calculate_position_size) — merge into
        #       bucket directly so each symbol is addressable.
        if isinstance(result, dict):
            bucket = accumulated_tool_results.setdefault(tool_name, {})
            sym = result.get("symbol") if isinstance(result.get("symbol"), str) else None
            if sym:
                bucket[sym] = result
            else:
                bucket.update(result)

    return {
        "messages": tool_result_messages,
        "tools_used": tools_used,
        "tool_call_history": tool_call_history,
        "errors": errors,
        "tool_results": accumulated_tool_results,
    }


def _build_report_data(state: dict[str, Any]) -> dict[str, Any]:
    """Assemble the `data` argument for `generate_report` from accumulated state.

    The LLM cannot know the report's expected schema (and its `data: dict` arg
    has no internal structure description), so the orchestrator injects the
    state-derived values here. Handles structural mismatches between tool
    outputs and the report's expected shape.
    """
    symbols = list(state.get("symbols") or [])
    tr = state.get("tool_results") or {}

    data: dict[str, Any] = {
        "query": state.get("query", ""),
        "symbols": symbols,
    }

    # D3: fetch_stock_data returns nested {symbol: {market_data, financial_data, news_data}}
    # Report expects flat data["market_data"][symbol] = {company_name, ...}, etc.
    fetch = tr.get("fetch_stock_data", {})
    if isinstance(fetch, dict) and fetch:
        market_data = {
            sym: (r.get("market_data") or {})
            for sym, r in fetch.items() if isinstance(r, dict)
        }
        financial_data = {
            sym: (r.get("financial_data") or {})
            for sym, r in fetch.items() if isinstance(r, dict)
        }
        if market_data:
            data["market_data"] = market_data
        if financial_data:
            data["financial_data"] = financial_data
        all_news: list[dict] = []
        for r in fetch.values():
            if isinstance(r, dict):
                all_news.extend(r.get("news_data") or [])
        if all_news:
            data["news_data"] = all_news

    # analyze_technical / fundamental / assess_risk: result has "symbol" key, already indexed
    for tool_name, key in (
        ("analyze_technical", "technical_analysis"),
        ("analyze_fundamental", "fundamental_analysis"),
        ("assess_risk", "risk_assessment"),
    ):
        bucket = tr.get(tool_name, {})
        if isinstance(bucket, dict) and bucket:
            data[key] = dict(bucket)

    # D2: analyze_sentiment returns flat {symbol: {sentiment, overall_sentiment, ...}}
    # Report expects {"sentiment_by_symbol": {symbol}, "overall_sentiment": ...}
    sent_bucket = tr.get("analyze_sentiment", {})
    if isinstance(sent_bucket, dict) and sent_bucket:
        data["sentiment_analysis"] = {
            "sentiment_by_symbol": {
                sym: r.get("sentiment", {})
                for sym, r in sent_bucket.items() if isinstance(r, dict)
            },
            "overall_sentiment": next(
                (r.get("overall_sentiment", {}) for r in sent_bucket.values() if isinstance(r, dict)),
                {},
            ),
        }

    # calculate_position_size: synthesize "action" from position_size since the
    # tool doesn't return one (otherwise the report's recommendations would
    # always fall back to "hold"). If the LLM called it with empty risk_data,
    # the result will be {} — derive a fallback decision per symbol from the
    # available risk_assessment so the recommendations section isn't empty.
    pos_bucket = tr.get("calculate_position_size", {})
    risk_bucket = tr.get("assess_risk", {})
    decisions: dict[str, dict] = {}

    if isinstance(pos_bucket, dict) and pos_bucket:
        for sym, r in pos_bucket.items():
            if not isinstance(r, dict):
                continue
            ps = r.get("position_size", 0) or 0
            action = "buy" if ps > 10 else "add" if ps > 5 else "hold" if ps > 2 else "reduce"
            decisions[sym] = {
                **r,
                "action": action,
                "confidence": round(min(1.0, ps / 20.0), 2),
            }

    # Fallback: derive a recommendation per symbol from risk_assessment
    if not decisions and isinstance(risk_bucket, dict):
        for sym, r in risk_bucket.items():
            if not isinstance(r, dict):
                continue
            risk_score = r.get("risk_score", 50) or 50
            risk_level = r.get("risk_level", "medium")
            if risk_score >= 70:
                action, ps, conf = "reduce", 2.0, 0.8
            elif risk_score >= 50:
                action, ps, conf = "hold", 5.0, 0.5
            elif risk_score >= 30:
                action, ps, conf = "add", 10.0, 0.6
            else:
                action, ps, conf = "buy", 15.0, 0.7
            decisions[sym] = {
                "symbol": sym,
                "action": action,
                "position_size": ps,
                "risk_level": risk_level,
                "risk_score": risk_score,
                "confidence": conf,
                "rationale": (
                    f"Derived from assess_risk result (risk_score={risk_score}, "
                    f"risk_level={risk_level}); calculate_position_size did not "
                    f"return data for this symbol."
                ),
            }

    if decisions:
        data["decision"] = {"decisions": decisions}

    return data


def observe_node(state: ReActState) -> dict[str, Any]:
    messages = state.get("messages", [])
    tools_used = list(state.get("tools_used", []))

    # If generate_report was just called, extract the final answer from the report
    if "generate_report" in tools_used:
        for msg in reversed(messages):
            if isinstance(msg, ToolMessage) and msg.name == "generate_report":
                try:
                    report = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                    summary = report.get("executive_summary", "")
                    title = report.get("title", "Analysis Report")
                    sections = report.get("sections", {})

                    # Build a markdown report
                    parts = [f"# {title}\n"]
                    if summary:
                        parts.append(f"## Executive Summary\n\n{summary}\n")
                    for section_name, section_data in sections.items():
                        label = section_name.replace("_", " ").title()
                        parts.append(f"## {label}\n")
                        parts.append(f"```json\n{json.dumps(section_data, indent=2, ensure_ascii=False)}\n```\n")

                    return {"final_answer": "\n".join(parts)}
                except Exception:
                    return {"final_answer": msg.content[:2000]}
    return {}


def reflect_node(state: ReActState) -> dict[str, Any]:
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 15)
    tools_used = list(state.get("tools_used", []))
    query = state.get("query", "")
    messages = list(state.get("messages", []))

    # Hard limit
    if iteration >= max_iterations:
        logger.info(f"Max iterations ({max_iterations}) reached, finishing")
        return {
            "messages": [
                HumanMessage(
                    content="You have reached the maximum number of iterations. Based on all data collected so far, "
                    "write a comprehensive analysis report in markdown format. Do NOT call any more tools. "
                    "Provide your best analysis with the information you have."
                )
            ]
        }

    # Repetition detection
    tool_calls = []
    for msg in messages:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append((tc.get("name"), json.dumps(tc.get("args", {}), sort_keys=True)))
    if len(tool_calls) >= 2 and tool_calls[-1] == tool_calls[-2]:
        logger.info("Repeated tool call detected, forcing finish")
        return {
            "messages": [
                HumanMessage(
                    content="You are repeating the same tool call. Stop calling tools and write a comprehensive "
                    "analysis report in markdown format based on the data you have already collected. "
                    "If some data is missing, acknowledge it and provide analysis with available information."
                )
            ]
        }

    # Cost check
    cost = state.get("accumulated_cost", 0)
    if cost >= settings.agent_cost_limit:
        logger.info(f"Cost limit (${cost}) reached, finishing")
        return {"final_answer": f"Analysis stopped due to cost limit (${cost}). Partial results available."}

    # State-aware progression: drive the LLM through analysis → report → finish.
    # We never need to re-run the same tool. The previous "iteration < 3" and
    # "unique_tools_used < 3" heuristics caused each tool to be called multiple
    # times — see commit 1850c81.
    analysis_tools = {
        "analyze_technical", "analyze_fundamental", "analyze_sentiment",
        "assess_risk", "calculate_position_size",
    }
    tools_set = set(tools_used)
    report_called = "generate_report" in tools_set
    all_analysis_done = analysis_tools.issubset(tools_set)

    if report_called:
        # observe_node has already extracted final_answer from the report. Reflect
        # should not inject further messages; the next decision will END.
        return {}

    if not all_analysis_done:
        missing = sorted(analysis_tools - tools_set)
        logger.info(f"Reflect: {len(missing)} analysis tools still needed: {missing}")
        return {
            "messages": [
                HumanMessage(
                    content=(
                        f"You still need to call: {', '.join(missing)}. "
                        "Call them now (one tool call per message is fine), "
                        "then call generate_report to compile the final report."
                    )
                )
            ]
        }

    logger.info("Reflect: all analysis tools done, prompting for generate_report")
    return {
        "messages": [
            HumanMessage(
                content=(
                    "All analysis tools have been called. Now call generate_report "
                    "to compile the structured final report. Do NOT write a free-form "
                    "markdown summary — the report tool will produce the final output."
                )
            )
        ]
    }


def _reflect_decision(state: ReActState) -> Literal["agent_reason", "__end__"]:
    """Decide whether to continue the loop or END.

    END conditions:
    - `final_answer` was set (by `observe_node` after `generate_report` ran)
    - max iterations reached (safety net)

    The previous `len(msg.content) > 200` heuristic was removed: LLM thinking
    text easily exceeds 200 chars, causing premature END that bypassed the
    analysis-tools progression in `reflect_node`.
    """
    if state.get("final_answer") is not None:
        return END
    if state.get("iteration", 0) >= state.get("max_iterations", 15):
        return END
    return "agent_reason"


def _truncate_messages_for_reflection(messages: list) -> list:
    """Create a compact copy of messages for the reflection LLM.

    Replaces large ToolMessage content with short summaries to keep
    the reflection prompt small and fast.
    """
    truncated = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            summary = content[:300] + "..." if len(content) > 300 else content
            truncated.append(ToolMessage(content=summary, tool_call_id=msg.tool_call_id, name=msg.name))
        else:
            truncated.append(msg)
    return truncated


def _truncate_messages_for_reasoning(messages: list, max_chars: int = 20000) -> list:
    """Truncate oldest tool results to prevent unbounded context growth.

    Keeps the most recent tool results in full (the LLM needs them),
    only truncates older ones starting from the beginning.
    """
    result = list(messages)
    total = sum(len(m.content) if hasattr(m, "content") and isinstance(m.content, str) else 0 for m in result)
    if total <= max_chars:
        return result
    # Truncate oldest tool results first, keep the latest ones intact
    for i in range(len(result)):
        if total <= max_chars:
            break
        m = result[i]
        if isinstance(m, ToolMessage) and len(m.content) > 500:
            old_len = len(m.content)
            result[i] = ToolMessage(content=m.content[:500] + "...[truncated]", tool_call_id=m.tool_call_id, name=m.name)
            total -= old_len - 500
    return result


def _extract_findings(messages: list) -> str:
    findings = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            findings.append(f"{msg.name}: {msg.content[:200]}")
    return "; ".join(findings[:3]) if findings else "No findings available."


class ReActAgent:
    """ReAct autonomous agent for stock analysis."""

    def __init__(self):
        self.graph = build_react_graph()

    async def analyze(
        self,
        query: str,
        symbols: list[str],
        thread_id: str,
        progress_callback: Any | None = None,
    ) -> dict[str, Any]:
        initial_state = create_initial_react_state(
            query=query, symbols=symbols, thread_id=thread_id,
        )

        final_state: dict[str, Any] = dict(initial_state)
        async for event in self.graph.astream(initial_state):
            for node_name, node_state in event.items():
                if node_state is not None:
                    # Merge state, but append messages instead of replacing
                    for key, value in node_state.items():
                        if key == "messages" and isinstance(value, list):
                            existing = final_state.get("messages", [])
                            final_state["messages"] = existing + value
                        else:
                            final_state[key] = value
                if progress_callback:
                    await progress_callback(node_name, node_state or {})

        # Extract answer from final_answer or last AI message
        answer = final_state.get("final_answer")
        if not answer:
            messages = final_state.get("messages", [])
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content:
                    answer = msg.content
                    break
        if not answer:
            answer = "Analysis completed but no conclusion was generated."

        return {
            "answer": answer,
            "report": final_state.get("report"),
            "iterations": final_state.get("iteration", 0),
            "tools_used": final_state.get("tools_used", []),
            "cost": final_state.get("accumulated_cost", 0),
        }
