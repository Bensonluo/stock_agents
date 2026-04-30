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
            openai_api_base="https://open.bigmodel.cn/api/coding/paas/v4/",
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
            openai_api_base="https://open.bigmodel.cn/api/coding/paas/v4/",
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


def _agent_reason_decision(state: ReActState) -> Literal["tool_execute", "__end__"]:
    """Decide whether to execute a tool or finish."""
    messages = state.get("messages", [])
    if not messages:
        return "__end__"

    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tool_execute"

    return "__end__"


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
                # Use ainvoke for async tools, invoke for sync tools
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


def _reflect_decision(state: ReActState) -> Literal["agent_reason", "__end__"]:
    """Route based on reflection result."""
    final_answer = state.get("final_answer")
    if final_answer is not None:
        return "__end__"

    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 15)
    if iteration >= max_iterations:
        return "__end__"

    return "agent_reason"


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
