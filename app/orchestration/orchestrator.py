"""Multi-agent orchestrator using LangGraph."""

import json
from typing import Any, Dict, List, Optional

import numpy as np

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END

from app.storage.database import get_database, AnalysisRecord
from app.agents import (
    AkShareDataAgent,
    DataCollectionAgent,
    DecisionMakingAgent,
    FundamentalAnalysisAgent,
    ReportGenerationAgent,
    RiskAssessmentAgent,
    SentimentAnalysisAgent,
    TechnicalAnalysisAgent,
)
from app.api.routes.monitor import init_workflow, update_agent_status, add_log
from app.monitoring import get_connection_manager, get_monitor
from app.orchestration.checkpoint import PostgresCheckpointManager
from app.orchestration.state import (
    AgentState,
    add_agent_output,
    add_error,
    create_initial_state,
    get_agent_errors,
    get_retry_count,
    set_agent_status,
    should_retry,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)


def _convert_to_serializable(obj: Any) -> Any:
    """Convert numpy types and other non-serializable objects to native Python types.

    Args:
        obj: Object to convert

    Returns:
        Serializable version of the object
    """
    if isinstance(obj, dict):
        return {k: _convert_to_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_to_serializable(v) for v in obj]
    elif isinstance(obj, tuple):
        return tuple(_convert_to_serializable(v) for v in obj)
    elif isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, np.floating):
        value = float(obj)
        # Convert NaN and Infinity to None
        if not np.isfinite(value):
            return None
        return value
    elif isinstance(obj, float):
        # Also handle Python floats for NaN/Infinity
        if not np.isfinite(obj):
            return None
        return obj
    elif isinstance(obj, np.ndarray):
        return _convert_to_serializable(obj.tolist())
    elif isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    else:
        return obj


class MultiAgentOrchestrator:
    """Multi-agent orchestrator for stock analysis workflow.

    This class is the core component that:
    - Manages the workflow graph using LangGraph
    - Coordinates agent execution
    - Handles state persistence
    - Implements retry logic
    - Provides workflow monitoring
    - Broadcasts WebSocket events for real-time updates

    Core learning: Understanding multi-agent orchestration patterns.
    """

    def __init__(
        self,
        llm: Optional[BaseChatModel] = None,
        checkpoint_manager: Optional[PostgresCheckpointManager] = None,
    ):
        """Initialize the multi-agent orchestrator.

        Args:
            llm: Optional language model for AI operations
            checkpoint_manager: Optional checkpoint manager for state persistence
        """
        self.llm = llm
        self.checkpoint_manager = checkpoint_manager
        self.graph = None

        # Initialize agents
        self.data_agent = DataCollectionAgent(
            name="data_collection",
            llm=llm,
        )
        self.akshare_agent = AkShareDataAgent(
            name="akshare_data_collection",
            llm=llm,
        )
        self.technical_agent = TechnicalAnalysisAgent(
            name="technical_analysis",
            llm=llm,
        )
        self.fundamental_agent = FundamentalAnalysisAgent(
            name="fundamental_analysis",
            llm=llm,
        )
        self.sentiment_agent = SentimentAnalysisAgent(
            name="sentiment_analysis",
            llm=llm,
        )
        self.risk_agent = RiskAssessmentAgent(
            name="risk_assessment",
            llm=llm,
        )
        self.decision_agent = DecisionMakingAgent(
            name="decision_making",
            llm=llm,
        )
        self.report_agent = ReportGenerationAgent(
            name="report_generation",
            llm=llm,
        )

        # Build the workflow graph
        self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow.

        The workflow runs ALL analysis agents sequentially to ensure all data is available:
        data_collection -> technical -> sentiment -> fundamental -> risk -> decision -> report

        Returns:
            Compiled StateGraph
        """
        # Create the state graph
        graph = StateGraph(AgentState)

        # Add nodes (each agent is a node)
        # Node names cannot match state keys in AgentState, so we use suffixes
        graph.add_node("data_collection_agent", self._data_collection_node)
        graph.add_node("technical_analysis_agent", self._technical_analysis_node)
        graph.add_node("fundamental_analysis_agent", self._fundamental_analysis_node)
        graph.add_node("sentiment_analysis_agent", self._sentiment_analysis_node)
        graph.add_node("risk_assessment_agent", self._risk_assessment_node)
        graph.add_node("decision_making_agent", self._decision_making_node)
        graph.add_node("report_generation_agent", self._report_generation_node)
        graph.add_node("error_handler", self._error_handler_node)

        # Set entry point
        graph.set_entry_point("data_collection_agent")

        # Linear workflow: all analysis agents run sequentially
        # This ensures all data is available for the decision agent
        graph.add_conditional_edges(
            "data_collection_agent",
            self._should_retry_or_continue_data,
            {
                "continue": "technical_analysis_agent",  # Always go to technical first
                "retry": "data_collection_agent",
                "error": "error_handler",
            }
        )

        graph.add_conditional_edges(
            "technical_analysis_agent",
            self._should_retry_or_continue_technical,
            {
                "continue": "sentiment_analysis_agent",  # Then sentiment
                "retry": "technical_analysis_agent",
                "error": "error_handler",
            }
        )

        graph.add_conditional_edges(
            "sentiment_analysis_agent",
            self._should_retry_or_continue_sentiment,
            {
                "continue": "fundamental_analysis_agent",  # Then fundamental
                "retry": "sentiment_analysis_agent",
                "error": "error_handler",
            }
        )

        graph.add_conditional_edges(
            "fundamental_analysis_agent",
            self._should_retry_or_continue_fundamental,
            {
                "continue": "risk_assessment_agent",  # Then risk
                "retry": "fundamental_analysis_agent",
                "error": "error_handler",
            }
        )

        graph.add_conditional_edges(
            "risk_assessment_agent",
            self._should_retry_or_continue_risk,
            {
                "decision": "decision_making_agent",  # Finally decision with all data
                "retry": "risk_assessment_agent",
                "error": "error_handler",
            }
        )

        graph.add_conditional_edges(
            "decision_making_agent",
            self._should_retry_or_continue_decision,
            {
                "report": "report_generation_agent",
                "retry": "decision_making_agent",
                "error": "error_handler",
            }
        )

        # Final edges
        graph.add_edge("report_generation_agent", END)
        graph.add_edge("error_handler", END)

        # Compile graph with checkpoint support
        checkpointer = None
        if self.checkpoint_manager:
            checkpointer = self.checkpoint_manager.get_checkpoint_saver()

        self.graph = graph.compile(checkpointer=checkpointer)

        logger.info("Multi-agent workflow graph built and compiled")

        return self.graph

    async def execute_workflow(
        self,
        query: str,
        symbols: List[str],
        thread_id: Optional[str] = None,
        **kwargs,
    ) -> AgentState:
        """Execute the complete analysis workflow.

        Args:
            query: User's query
            symbols: List of stock symbols to analyze
            thread_id: Optional thread ID for state persistence
            **kwargs: Additional state parameters

        Returns:
            Final agent state
        """
        import time
        from datetime import datetime

        # Get broadcast manager and set it on the monitor
        broadcast_manager = get_connection_manager()
        monitor = get_monitor()
        monitor.broadcast_manager = broadcast_manager

        # Generate thread ID if not provided
        if not thread_id:
            thread_id = f"workflow-{datetime.now().timestamp()}"

        # Create initial state
        initial_state = create_initial_state(
            query=query,
            symbols=symbols,
            thread_id=thread_id,
            **kwargs,
        )

        # Initialize monitoring state
        init_workflow(thread_id)
        add_log(thread_id, "system", "info", f"Workflow started for symbols: {symbols}")

        # 保存初始记录到数据库
        try:
            db = get_database()
            db.create_record(AnalysisRecord(
                thread_id=thread_id,
                symbols=json.dumps(symbols),
                query=query,
                status="running"
            ))
            logger.info(f"[Orchestrator] 创建历史记录: thread_id={thread_id}")
        except Exception as e:
            logger.error(f"[Orchestrator] 创建历史记录失败: {e}")

        logger.info(
            f"Starting workflow execution: thread_id={thread_id}, "
            f"symbols={symbols}, query={query}"
        )

        start_time = time.time()

        # Build graph if needed
        if self.graph is None:
            self._build_graph()

        # Create config
        config = {"configurable": {"thread_id": thread_id}}

        try:
            # Execute workflow
            result = await self.graph.ainvoke(initial_state, config)

            execution_time = time.time() - start_time

            logger.info(
                f"Workflow execution completed: thread_id={thread_id}, "
                f"time={execution_time:.2f}s"
            )

            # Update execution metadata
            result["execution_metadata"]["completed_at"] = datetime.now()
            result["execution_metadata"]["execution_time"] = execution_time

            # Convert numpy types to Python native types for serialization
            result = _convert_to_serializable(result)

            # Broadcast workflow completion
            total_steps = result.get("current_step", 0)
            await broadcast_manager.broadcast_workflow_complete(
                thread_id=thread_id,
                execution_time=execution_time,
                success=True,
                total_steps=total_steps,
            )

            # 更新数据库中的记录状态
            try:
                db = get_database()
                final_state = result.get("agent_status", {})
                all_completed = all(s == "completed" for s in final_state.values())
                any_failed = any(s == "failed" for s in final_state.values())

                final_status = "completed" if all_completed else ("failed" if any_failed else "partial")

                # 序列化结果
                result_data = {
                    "symbols": symbols,
                    "query": query,
                    "decision": result.get("decision"),
                    "report": result.get("report"),
                    "agent_status": result.get("agent_status"),
                    "technical_analysis": result.get("technical_analysis"),
                    "fundamental_analysis": result.get("fundamental_analysis"),
                    "sentiment_analysis": result.get("sentiment_analysis"),
                    "risk_assessment": result.get("risk_assessment"),
                    "execution_metadata": result.get("execution_metadata")
                }

                db.update_status(
                    thread_id=thread_id,
                    status=final_status,
                    result=json.dumps(result_data, default=str),
                    execution_time=result.get("execution_metadata", {}).get("execution_time", 0)
                )
                logger.info(f"[Orchestrator] 更新历史记录: thread_id={thread_id}, status={final_status}")
            except Exception as e:
                logger.error(f"[Orchestrator] 更新历史记录失败: {e}")

            return result

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Workflow execution failed after {execution_time:.2f}s: {e}")

            # Broadcast workflow failure
            await broadcast_manager.broadcast_workflow_complete(
                thread_id=thread_id,
                execution_time=execution_time,
                success=False,
                total_steps=0,
                error=str(e),
            )

            # Return state with error
            initial_state["execution_metadata"]["failed_at"] = datetime.now()
            initial_state["execution_metadata"]["execution_time"] = execution_time
            initial_state["execution_metadata"]["error"] = str(e)

            # 更新数据库中的记录状态（失败）
            try:
                db = get_database()
                result_data = {
                    "symbols": symbols,
                    "query": query,
                    "error": str(e),
                    "execution_metadata": initial_state.get("execution_metadata")
                }
                db.update_status(
                    thread_id=thread_id,
                    status="failed",
                    result=json.dumps(result_data, default=str),
                    execution_time=execution_time
                )
                logger.info(f"[Orchestrator] 更新历史记录（失败）: thread_id={thread_id}")
            except Exception as db_error:
                logger.error(f"[Orchestrator] 更新历史记录失败: {db_error}")

            return _convert_to_serializable(initial_state)

    async def _run_agent_node(
        self,
        state: AgentState,
        agent_name: str,
        agent,
        mode: str = "run",
        state_key: Optional[str] = None,
        post_process=None,
    ) -> AgentState:
        """Shared agent node runner with monitoring, broadcasting, and error handling.

        Args:
            state: Current agent state
            agent_name: Name for status tracking and monitoring
            agent: Agent instance to execute
            mode: "run" for BaseAgent.run(), "process" for StatelessAgent.process()
            state_key: If set, assign process() result to this state key
            post_process: Optional async callback(state, agent_result) for extra logic

        Returns:
            Updated agent state
        """
        import time

        thread_id = state.get("thread_id", "unknown")

        # Set tracking
        state = dict(state)
        state["current_agent"] = agent_name
        state["current_step"] = state.get("current_step", 0) + 1
        step = state["current_step"]
        agent_status = state.get("agent_status", {})
        agent_status[agent_name] = "running"
        state["agent_status"] = agent_status

        # Broadcast and monitor start
        monitor = get_monitor()
        symbols = state.get("symbols", [])

        if monitor.broadcast_manager:
            await monitor.broadcast_manager.broadcast_agent_event(
                event_type="agent_start",
                agent_name=agent_name,
                thread_id=thread_id,
                status="running",
                step=step,
            )
        monitor.on_agent_start(agent_name, state)

        monitor.log_agent_step(
            thread_id=thread_id,
            agent_name=agent_name,
            step=step,
            level="info",
            message=f"Starting {agent_name} for symbols: {symbols}",
            data={"symbols": symbols},
        )

        update_agent_status(thread_id, agent_name, "running")
        add_log(thread_id, agent_name, "info", f"Starting {agent_name}")

        start_time = time.time()

        try:
            # Execute agent
            if mode == "run":
                agent_result = await agent.run(state)
            else:
                agent_result = await agent.process(state)

            agent_result = _convert_to_serializable(agent_result)

            # Merge results into state
            if mode == "run":
                if isinstance(agent_result, dict):
                    for key, value in agent_result.items():
                        if key not in ("agent_outputs", "errors", "agent_status", "current_agent", "current_step"):
                            state[key] = value
            elif state_key:
                state[state_key] = agent_result

            # Post-process hook (e.g., AkShare merge for data_collection)
            if post_process:
                await post_process(state, agent_result)

            # Mark completed
            agent_status[agent_name] = "completed"
            state["agent_status"] = agent_status
            execution_time = time.time() - start_time

            update_agent_status(thread_id, agent_name, "completed")
            add_log(thread_id, agent_name, "info", f"Completed successfully in {execution_time:.2f}s")

            monitor.log_agent_step(
                thread_id=thread_id,
                agent_name=agent_name,
                step=step,
                level="info",
                message=f"{agent_name} completed successfully",
                duration_ms=int(execution_time * 1000),
            )

            if monitor.broadcast_manager:
                await monitor.broadcast_manager.broadcast_agent_event(
                    event_type="agent_success",
                    agent_name=agent_name,
                    thread_id=thread_id,
                    status="completed",
                    step=step,
                    execution_time=execution_time,
                )
            monitor.on_agent_success(agent_name, execution_time, thread_id=thread_id)

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"{agent_name} node error: {e}")

            update_agent_status(thread_id, agent_name, "failed", str(e))
            add_log(thread_id, agent_name, "error", f"Failed: {str(e)}")

            monitor.log_agent_step(
                thread_id=thread_id,
                agent_name=agent_name,
                step=step,
                level="error",
                message=f"{agent_name} failed: {str(e)}",
                data={"error_type": type(e).__name__},
                duration_ms=int(execution_time * 1000),
            )

            state = add_error(state, agent_name, type(e).__name__, str(e), retryable=True)
            agent_status[agent_name] = "failed"
            state["agent_status"] = agent_status

            if monitor.broadcast_manager:
                await monitor.broadcast_manager.broadcast_agent_event(
                    event_type="agent_failure",
                    agent_name=agent_name,
                    thread_id=thread_id,
                    status="failed",
                    step=step,
                    execution_time=execution_time,
                    error=str(e),
                )
            monitor.on_agent_failure(
                agent_name, str(e), execution_time, type(e).__name__, thread_id=thread_id
            )

        return AgentState(**state)

    async def _data_collection_node(self, state: AgentState) -> AgentState:
        """Data collection node with AkShare merge for Chinese stocks."""

        async def merge_akshare(state, _agent_result):
            symbols = state.get("symbols", [])
            cn_symbols = [s for s in symbols if s.isdigit() and len(s) == 6]
            if cn_symbols:
                akshare_result = await self.akshare_agent.run(state)
                akshare_result = _convert_to_serializable(akshare_result)
                for key, value in akshare_result.items():
                    if key not in ("agent_outputs", "errors", "agent_status", "current_agent", "current_step"):
                        if key in state and isinstance(state.get(key), dict) and isinstance(value, dict):
                            state[key] = {**state[key], **value}
                        else:
                            state[key] = value

        return await self._run_agent_node(
            state,
            agent_name="data_collection",
            agent=self.data_agent,
            mode="run",
            post_process=merge_akshare,
        )

    async def _technical_analysis_node(self, state: AgentState) -> AgentState:
        return await self._run_agent_node(
            state, agent_name="technical_analysis", agent=self.technical_agent, mode="run",
        )

    async def _fundamental_analysis_node(self, state: AgentState) -> AgentState:
        return await self._run_agent_node(
            state, agent_name="fundamental_analysis", agent=self.fundamental_agent, mode="run",
        )

    async def _sentiment_analysis_node(self, state: AgentState) -> AgentState:
        return await self._run_agent_node(
            state, agent_name="sentiment_analysis", agent=self.sentiment_agent,
            mode="process", state_key="sentiment_analysis",
        )

    async def _risk_assessment_node(self, state: AgentState) -> AgentState:
        return await self._run_agent_node(
            state, agent_name="risk_assessment", agent=self.risk_agent,
            mode="process", state_key="risk_assessment",
        )

    async def _decision_making_node(self, state: AgentState) -> AgentState:
        return await self._run_agent_node(
            state, agent_name="decision_making", agent=self.decision_agent,
            mode="process", state_key="decision",
        )

    async def _report_generation_node(self, state: AgentState) -> AgentState:
        return await self._run_agent_node(
            state, agent_name="report_generation", agent=self.report_agent,
            mode="process", state_key="report",
        )

    async def _error_handler_node(self, state: AgentState) -> AgentState:
        """Error handler node."""
        errors = state.get("errors", [])

        error_summary = {
            "total_errors": len(errors),
            "errors_by_agent": {},
            "last_error": errors[-1] if errors else None,
        }

        for error in errors:
            agent = error.get("agent", "unknown")
            if agent not in error_summary["errors_by_agent"]:
                error_summary["errors_by_agent"][agent] = []
            error_summary["errors_by_agent"][agent].append(error)

        logger.error(f"Error handler processed {len(errors)} errors")

        state = dict(state)
        state["error_summary"] = error_summary
        execution_metadata = state.get("execution_metadata", {})
        execution_metadata["had_errors"] = True
        state["execution_metadata"] = execution_metadata

        return AgentState(**state)

    def _should_retry_or_continue_data(self, state: AgentState) -> str:
        """Decision function for data collection node.

        Args:
            state: Current agent state

        Returns:
            Next node name ("continue", "retry", or "error")
        """
        if not get_agent_errors(state, "data_collection"):
            return "continue"  # Always continue to technical analysis
        return self._retry_or_error("data_collection", state)

    def _should_retry_or_continue_technical(self, state: AgentState) -> str:
        """Decision function for technical analysis node.

        Args:
            state: Current agent state

        Returns:
            Next node name ("continue", "retry", or "error")
        """
        if not get_agent_errors(state, "technical_analysis"):
            return "continue"  # Continue to sentiment analysis
        return self._retry_or_error("technical_analysis", state)

    def _should_retry_or_continue_fundamental(self, state: AgentState) -> str:
        """Decision function for fundamental analysis node.

        Args:
            state: Current agent state

        Returns:
            Next node name ("continue", "retry", or "error")
        """
        if not get_agent_errors(state, "fundamental_analysis"):
            return "continue"  # Continue to risk assessment
        return self._retry_or_error("fundamental_analysis", state)

    def _should_retry_or_continue_sentiment(self, state: AgentState) -> str:
        """Decision function for sentiment analysis node.

        Args:
            state: Current agent state

        Returns:
            Next node name ("continue", "retry", or "error")
        """
        if not get_agent_errors(state, "sentiment_analysis"):
            return "continue"  # Continue to fundamental analysis
        return self._retry_or_error("sentiment_analysis", state)

    def _should_retry_or_continue_risk(self, state: AgentState) -> str:
        """Decision function for risk assessment node.

        Args:
            state: Current agent state

        Returns:
            Next node name ("decision", "retry", or "error")
        """
        if not get_agent_errors(state, "risk_assessment"):
            return "decision"  # All analysis done, go to decision
        return self._retry_or_error("risk_assessment", state)

    def _should_retry_or_continue_decision(self, state: AgentState) -> str:
        """Decision function for decision making node.

        Args:
            state: Current agent state

        Returns:
            Next node name
        """
        if not get_agent_errors(state, "decision_making"):
            return "report"
        return self._retry_or_error("decision_making", state)

    def _retry_or_error(self, agent_name: str, state: AgentState) -> str:
        """Determine whether to retry or go to error handler.

        Args:
            agent_name: Name of the agent
            state: Current agent state

        Returns:
            "retry" or "error"
        """
        if should_retry(state, agent_name):
            logger.info(f"Retrying {agent_name}")
            return "retry"
        else:
            logger.error(f"Max retries exceeded for {agent_name}, going to error handler")
            return "error"

    def get_workflow_status(self, thread_id: str) -> Dict[str, Any]:
        """Get the status of a workflow.

        Args:
            thread_id: Thread ID to check

        Returns:
            Status dictionary
        """
        if self.checkpoint_manager:
            state = self.checkpoint_manager.load_state(thread_id)
            if state:
                return {
                    "thread_id": thread_id,
                    "current_step": state.get("current_step", 0),
                    "current_agent": state.get("current_agent"),
                    "agent_status": state.get("agent_status", {}),
                    "has_errors": len(state.get("errors", [])) > 0,
                }

        return {
            "thread_id": thread_id,
            "status": "not_found",
        }
