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
            errors.append({"agent": "react_agent", "error_type": "ToolNotFound", "message": error_msg})
        else:
            try:
                result = await tool.ainvoke(tool_args)
                tool_results.append(ToolMessage(content=str(result), tool_call_id=tool_id, name=tool_name))
            except Exception as e:
                error_msg = f"Error executing {tool_name}: {str(e)}"
                tool_results.append(ToolMessage(content=error_msg, tool_call_id=tool_id, name=tool_name))
                errors.append({"agent": "react_agent", "error_type": "ToolExecutionError", "message": error_msg})

    return {
        "messages": tool_results,
        "tools_used": tools_used,
        "tool_call_history": tool_call_history,
        "errors": errors,
    }


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

    # Minimum tools check: ensure at least 3 distinct analysis tools are used
    analysis_tools = {"analyze_technical", "analyze_fundamental", "analyze_sentiment",
                      "assess_risk", "calculate_position_size", "generate_report"}
    used_analysis = set(tools_used) & analysis_tools
    unique_tools_used = len(set(tools_used))

    if unique_tools_used < 3 and iteration < max_iterations:
        logger.info(f"Only {unique_tools_used} tools used so far, forcing continuation")
        missing = analysis_tools - set(tools_used)
        missing_hint = ", ".join(sorted(missing)) if missing else "more analysis tools"
        return {
            "messages": [
                HumanMessage(
                    content=f"You have only used {unique_tools_used} tools. A thorough analysis requires at least 3-4 tools. "
                    f"Available tools you haven't used yet: {missing_hint}. "
                    "Call these tools now to complete the analysis. Do NOT write a final answer yet."
                )
            ]
        }

    # Heuristic: if only data-fetching tools used, always continue to actual analysis
    has_analysis = bool(used_analysis)
    if not has_analysis and iteration < max_iterations:
        logger.info(f"No analysis tools used yet (only {tools_used}), continuing")
        return {
            "messages": [
                HumanMessage(
                    content="Data has been collected. Now use analysis tools (analyze_technical, "
                    "analyze_fundamental, analyze_sentiment, assess_risk) to analyze the data, "
                    "then generate a report."
                )
            ]
        }

    # Heuristic: if very few iterations, keep going unless we already have a report
    if iteration < 3 and "generate_report" not in tools_used:
        logger.info(f"Too early to finish (iteration {iteration}), continuing")
        return {
            "messages": [
                HumanMessage(
                    content="Continue the analysis. Use remaining analysis tools to cover "
                    "different perspectives, then write the final report."
                )
            ]
        }

    # LLM reflection
    reflection_prompt = format_reflection_prompt(
        iteration=iteration, max_iterations=max_iterations, tools_used=tools_used, query=query,
    )
    reflect_llm = _get_reflection_llm()
    compact_messages = _truncate_messages_for_reflection(messages)
    reflection_messages = compact_messages + [HumanMessage(content=reflection_prompt)]

    try:
        response = reflect_llm.invoke(reflection_messages)
        content = response.content
        if "{" in content and "}" in content:
            start = content.find("{")
            end = content.rfind("}") + 1
            decision = json.loads(content[start:end])
            if decision.get("decision") == "finish":
                return {
                    "messages": [
                        HumanMessage(
                            content="Reflection indicates analysis is complete. Based on all data collected, "
                            "write your final comprehensive analysis report in markdown format now. "
                            "Do NOT call any more tools."
                        )
                    ]
                }
            elif decision.get("decision") == "error":
                return {
                    "messages": [
                        HumanMessage(
                            content="You indicated an error. Instead of giving up, write a comprehensive analysis "
                            "report in markdown format based on whatever data you have collected. If data is incomplete, "
                            "state what is missing and provide your best assessment with available information. "
                            "Do NOT call any more tools."
                        )
                    ]
                }
            guidance = decision.get("guidance", "")
            if guidance:
                return {"messages": [HumanMessage(content=f"Guidance: {guidance}")]}
    except Exception as e:
        logger.warning(f"Reflection failed: {e}, continuing")

    return {
        "messages": [
            HumanMessage(
                content="Continue the analysis. Apply more tools or write the final report if sufficient data has been gathered."
            )
        ]
    }


def _reflect_decision(state: ReActState) -> Literal["agent_reason", "__end__"]:
    if state.get("final_answer") is not None:
        return END
    if state.get("iteration", 0) >= state.get("max_iterations", 15):
        return END

    # Check if the last AI message contains a substantial final answer (no tool calls)
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            # If the last AI message has tool calls, we should continue
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                return "agent_reason"
            # If the AI gave a substantial text response (>200 chars), treat as final
            if msg.content and len(msg.content) > 200:
                return END
            break

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
