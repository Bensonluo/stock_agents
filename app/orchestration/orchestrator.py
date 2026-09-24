"""Multi-agent orchestrator using LangGraph."""

import json
from typing import Any

import numpy as np
from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, StateGraph

from app.agents import (
    AkShareDataAgent,
    DataCollectionAgent,
    DecisionMakingAgent,
    FundamentalAnalysisAgent,
    ReportGenerationAgent,
    ResearchSynthesisAgent,
    RiskAssessmentAgent,
    SentimentAnalysisAgent,
    TechnicalAnalysisAgent,
)
from app.monitoring import get_connection_manager, get_monitor
from app.monitoring.workflow_status import (
    add_log,
    get_workflow_state,
    init_workflow,
    update_agent_status,
)
from app.orchestration.checkpoint import PostgresCheckpointManager
from app.orchestration.state import (
    AgentState,
    create_initial_state,
    should_retry,
)
from app.storage.database import AnalysisRecord, get_database
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
    elif isinstance(obj, np.integer | np.int64 | np.int32):
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
    elif isinstance(obj, np.bool_ | bool):
        return bool(obj)
    else:
        return obj


# Keys owned by the orchestration layer itself — never merged from agent results.
_RESERVED_STATE_KEYS = (
    "agent_outputs",
    "errors",
    "agent_status",
    "current_agent",
    "current_step",
)


def _merge_symbol_maps(existing: dict, incoming: dict) -> dict:
    """Merge agent output maps keyed by symbol (e.g. ``market_data``).

    Incoming values win per symbol, but a symbol dict from the earlier pass
    keeps keys the incoming pass did not set — the benchmark block the
    yfinance agent attached survives AkShare replacing a CN symbol's data
    wholesale, so beta keeps working on the merged A-share path.
    """
    merged = dict(existing)
    for key, value in incoming.items():
        old = merged.get(key)
        merged[key] = (
            {**old, **value} if isinstance(old, dict) and isinstance(value, dict) else value
        )
    return merged


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
        llm: BaseChatModel | None = None,
        checkpoint_manager: PostgresCheckpointManager | None = None,
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
        self.synthesis_agent = ResearchSynthesisAgent(
            name="research_synthesis",
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

        Topology (LangGraph's map-reduce fan-out pattern):

            data_collection
              -> [technical, sentiment, fundamental]   # parallel analysis stage
              -> risk_assessment -> research_synthesis
              -> decision_making -> report_generation

        Nodes return partial state updates; shared channels accumulate through
        reducers (errors/agent_outputs append, agent_status/retry_count merge,
        current_step adds), which is what makes the parallel stage safe.

        Retry semantics: routing keys off the agent's LAST attempt outcome
        (agent_status) with retry_count as the budget, so a transient failure
        that succeeds on retry continues the pipeline instead of looping
        forever. Analysis agents that exhaust their budget degrade gracefully
        (risk still runs with the remaining inputs); pipeline-critical nodes
        route to the error handler.

        Set ``parallel_execution=False`` in the initial state to force the
        sequential technical -> sentiment -> fundamental order.

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
        graph.add_node("research_synthesis_agent", self._research_synthesis_node)
        graph.add_node("decision_making_agent", self._decision_making_node)
        graph.add_node("report_generation_agent", self._report_generation_node)
        graph.add_node("error_handler", self._error_handler_node)

        # Set entry point
        graph.set_entry_point("data_collection_agent")

        # Fan-out: the router returns several path keys at once, so the three
        # independent analysis agents run in the same superstep.
        graph.add_conditional_edges(
            "data_collection_agent",
            self._route_after_data,
            {
                "fan_out_technical": "technical_analysis_agent",
                "fan_out_sentiment": "sentiment_analysis_agent",
                "fan_out_fundamental": "fundamental_analysis_agent",
                "sequential": "technical_analysis_agent",
                "retry": "data_collection_agent",
                "error": "error_handler",
            },
        )

        # Each parallel branch converges on risk_assessment (fan-in barrier:
        # risk waits until every branch has routed), with a self-loop retry
        # and a degraded path that keeps the pipeline alive when an analysis
        # exhausts its retry budget.
        graph.add_conditional_edges(
            "technical_analysis_agent",
            self._route_after_technical,
            {
                "join_risk": "risk_assessment_agent",
                "sequential_sentiment": "sentiment_analysis_agent",
                "retry": "technical_analysis_agent",
                "degraded": "risk_assessment_agent",
            },
        )

        graph.add_conditional_edges(
            "sentiment_analysis_agent",
            self._route_after_sentiment,
            {
                "join_risk": "risk_assessment_agent",
                "sequential_fundamental": "fundamental_analysis_agent",
                "retry": "sentiment_analysis_agent",
                "degraded": "risk_assessment_agent",
            },
        )

        graph.add_conditional_edges(
            "fundamental_analysis_agent",
            self._route_after_fundamental,
            {
                "join_risk": "risk_assessment_agent",
                "retry": "fundamental_analysis_agent",
                "degraded": "risk_assessment_agent",
            },
        )

        graph.add_conditional_edges(
            "risk_assessment_agent",
            self._route_after_risk,
            {
                "synthesis": "research_synthesis_agent",  # Debate/audit/committee before deciding
                "retry": "risk_assessment_agent",
                "error": "error_handler",
            },
        )

        graph.add_conditional_edges(
            "research_synthesis_agent",
            self._route_after_synthesis,
            {
                "decision": "decision_making_agent",  # Decision with audited research
                "retry": "research_synthesis_agent",
                "error": "error_handler",
            },
        )

        graph.add_conditional_edges(
            "decision_making_agent",
            self._route_after_decision,
            {
                "report": "report_generation_agent",
                "retry": "decision_making_agent",
                "error": "error_handler",
            },
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
        symbols: list[str],
        thread_id: str | None = None,
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
            db.create_record(
                AnalysisRecord(
                    thread_id=thread_id, symbols=json.dumps(symbols), query=query, status="running"
                )
            )
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

                final_status = (
                    "completed" if all_completed else ("failed" if any_failed else "partial")
                )

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
                    "execution_metadata": result.get("execution_metadata"),
                }

                db.update_status(
                    thread_id=thread_id,
                    status=final_status,
                    result=json.dumps(result_data, default=str),
                    execution_time=result.get("execution_metadata", {}).get("execution_time", 0),
                )
                logger.info(
                    f"[Orchestrator] 更新历史记录: thread_id={thread_id}, status={final_status}"
                )
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
                    "execution_metadata": initial_state.get("execution_metadata"),
                }
                db.update_status(
                    thread_id=thread_id,
                    status="failed",
                    result=json.dumps(result_data, default=str),
                    execution_time=execution_time,
                )
                logger.info(f"[Orchestrator] 更新历史记录（失败）: thread_id={thread_id}")
            except Exception as db_error:
                logger.error(f"[Orchestrator] 更新历史记录失败: {db_error}")

            raise RuntimeError(f"Workflow execution failed: {e}") from e

    async def _run_agent_node(
        self,
        state: AgentState,
        agent_name: str,
        agent,
        mode: str = "run",
        state_key: str | None = None,
        post_process=None,
    ) -> dict[str, Any]:
        """Shared agent node runner with monitoring, broadcasting, and error handling.

        Returns a PARTIAL state update (LangGraph best practice: nodes return
        only the keys they changed). Shared channels accumulate through their
        reducers, which keeps concurrent analysis nodes conflict-free.

        Args:
            state: Current agent state (full channel state, read-only)
            agent_name: Name for status tracking and monitoring
            agent: Agent instance to execute
            mode: "run" for BaseAgent.run(), "process" for StatelessAgent.process()
            state_key: If set, assign process() result to this state key
            post_process: Optional async callback(state, agent_result) -> dict
                of extra state updates (e.g., the AkShare merge for data_collection)

        Returns:
            Partial state update for LangGraph to merge into the channels
        """
        import time
        from datetime import datetime

        thread_id = state.get("thread_id", "unknown")

        step = state.get("current_step", 0) + 1
        update: dict[str, Any] = {
            "current_agent": agent_name,
            "current_step": 1,  # `add` reducer: +1 per node execution
            "agent_status": {agent_name: "running"},
        }

        # Record status BEFORE broadcasting so the event carries the full set
        # of agents running in this superstep (parallel fan-out display).
        update_agent_status(thread_id, agent_name, "running")
        add_log(thread_id, agent_name, "info", f"Starting {agent_name}")
        running_snapshot = (get_workflow_state(thread_id) or {}).get("running_agents", [])

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
                metadata={"running_agents": running_snapshot},
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

        start_time = time.time()

        try:
            # Execute agent
            if mode == "run":
                agent_result = await agent.run(state)
            else:
                agent_result = await agent.process(state)

            agent_result = _convert_to_serializable(agent_result)

            # Collect result keys into the partial update
            if mode == "run":
                if isinstance(agent_result, dict):
                    for key, value in agent_result.items():
                        if key not in _RESERVED_STATE_KEYS:
                            update[key] = value
            elif state_key:
                update[state_key] = agent_result

            # Post-process hook (e.g., AkShare merge for data_collection).
            # It sees a merged view of the input state plus this node's
            # pending updates, and returns extra updates to apply.
            if post_process:
                view = {**state, **update}
                extra = await post_process(view, agent_result)
                if isinstance(extra, dict):
                    update.update(extra)

            # Mark completed
            update["agent_status"] = {agent_name: "completed"}
            execution_time = time.time() - start_time

            update_agent_status(thread_id, agent_name, "completed")
            add_log(
                thread_id, agent_name, "info", f"Completed successfully in {execution_time:.2f}s"
            )

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
                    metadata={
                        "running_agents": (get_workflow_state(thread_id) or {}).get(
                            "running_agents", []
                        )
                    },
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

            # Error delta: exactly one entry, appended by the `add` reducer.
            # (Returning the accumulated list here used to double it.)
            update["errors"] = [
                {
                    "agent": agent_name,
                    "type": type(e).__name__,
                    "message": str(e),
                    "timestamp": datetime.now(),
                    "retryable": True,
                }
            ]
            update["retry_count"] = {
                agent_name: state.get("retry_count", {}).get(agent_name, 0) + 1
            }
            update["agent_status"] = {agent_name: "failed"}

            if monitor.broadcast_manager:
                await monitor.broadcast_manager.broadcast_agent_event(
                    event_type="agent_failure",
                    agent_name=agent_name,
                    thread_id=thread_id,
                    status="failed",
                    step=step,
                    execution_time=execution_time,
                    error=str(e),
                    metadata={
                        "running_agents": (get_workflow_state(thread_id) or {}).get(
                            "running_agents", []
                        )
                    },
                )
            monitor.on_agent_failure(
                agent_name, str(e), execution_time, type(e).__name__, thread_id=thread_id
            )

        return update

    async def _data_collection_node(self, state: AgentState) -> dict[str, Any]:
        """Data collection node with AkShare merge for Chinese stocks."""

        async def merge_akshare(view, _agent_result):
            symbols = view.get("symbols", [])
            cn_symbols = [s for s in symbols if s.isdigit() and len(s) == 6]
            if not cn_symbols:
                return None
            akshare_result = await self.akshare_agent.run(view)
            akshare_result = _convert_to_serializable(akshare_result)
            merged = {}
            for key, value in akshare_result.items():
                if key in _RESERVED_STATE_KEYS:
                    continue
                existing = view.get(key)
                if isinstance(existing, dict) and isinstance(value, dict):
                    merged[key] = _merge_symbol_maps(existing, value)
                else:
                    merged[key] = value
            return merged

        return await self._run_agent_node(
            state,
            agent_name="data_collection",
            agent=self.data_agent,
            mode="run",
            post_process=merge_akshare,
        )

    async def _technical_analysis_node(self, state: AgentState) -> dict[str, Any]:
        return await self._run_agent_node(
            state,
            agent_name="technical_analysis",
            agent=self.technical_agent,
            mode="run",
        )

    async def _fundamental_analysis_node(self, state: AgentState) -> dict[str, Any]:
        return await self._run_agent_node(
            state,
            agent_name="fundamental_analysis",
            agent=self.fundamental_agent,
            mode="run",
        )

    async def _sentiment_analysis_node(self, state: AgentState) -> dict[str, Any]:
        return await self._run_agent_node(
            state,
            agent_name="sentiment_analysis",
            agent=self.sentiment_agent,
            mode="process",
            state_key="sentiment_analysis",
        )

    async def _risk_assessment_node(self, state: AgentState) -> dict[str, Any]:
        return await self._run_agent_node(
            state,
            agent_name="risk_assessment",
            agent=self.risk_agent,
            mode="process",
            state_key="risk_assessment",
        )

    async def _research_synthesis_node(self, state: AgentState) -> dict[str, Any]:
        return await self._run_agent_node(
            state,
            agent_name="research_synthesis",
            agent=self.synthesis_agent,
            mode="process",
            state_key="research_synthesis",
        )

    async def _decision_making_node(self, state: AgentState) -> dict[str, Any]:
        return await self._run_agent_node(
            state,
            agent_name="decision_making",
            agent=self.decision_agent,
            mode="process",
            state_key="decision",
        )

    async def _report_generation_node(self, state: AgentState) -> dict[str, Any]:
        return await self._run_agent_node(
            state,
            agent_name="report_generation",
            agent=self.report_agent,
            mode="process",
            state_key="report",
        )

    async def _error_handler_node(self, state: AgentState) -> dict[str, Any]:
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

        execution_metadata = dict(state.get("execution_metadata", {}))
        execution_metadata["had_errors"] = True

        return {
            "error_summary": error_summary,
            "execution_metadata": execution_metadata,
        }

    @staticmethod
    def _last_attempt_failed(state: AgentState, agent_name: str) -> bool:
        """True only if the agent's most recent attempt failed.

        Routing on the cumulative errors list (the old behaviour) made a
        transient failure loop forever: a later successful attempt appended
        no error, so the retry budget never drained and the router kept
        re-running a healthy agent.
        """
        return state.get("agent_status", {}).get(agent_name) == "failed"

    def _route_after_data(self, state: AgentState) -> Any:
        """Route after data collection: fan out to the analysis stage.

        Returns a list of path keys in parallel mode (LangGraph then runs all
        three destinations in the same superstep) or a single key when
        ``parallel_execution`` is disabled.
        """
        if self._last_attempt_failed(state, "data_collection"):
            return self._retry_or_error("data_collection", state)
        if state.get("parallel_execution", True):
            return ["fan_out_technical", "fan_out_sentiment", "fan_out_fundamental"]
        return "sequential"

    def _route_after_technical(self, state: AgentState) -> str:
        """join_risk / sequential_sentiment / retry / degraded."""
        if self._last_attempt_failed(state, "technical_analysis"):
            return "retry" if should_retry(state, "technical_analysis") else "degraded"
        return "sequential_sentiment" if not state.get("parallel_execution", True) else "join_risk"

    def _route_after_sentiment(self, state: AgentState) -> str:
        """join_risk / sequential_fundamental / retry / degraded."""
        if self._last_attempt_failed(state, "sentiment_analysis"):
            return "retry" if should_retry(state, "sentiment_analysis") else "degraded"
        return (
            "sequential_fundamental" if not state.get("parallel_execution", True) else "join_risk"
        )

    def _route_after_fundamental(self, state: AgentState) -> str:
        """join_risk / retry / degraded."""
        if self._last_attempt_failed(state, "fundamental_analysis"):
            return "retry" if should_retry(state, "fundamental_analysis") else "degraded"
        return "join_risk"

    def _route_after_risk(self, state: AgentState) -> str:
        """synthesis / retry / error."""
        if self._last_attempt_failed(state, "risk_assessment"):
            return "retry" if should_retry(state, "risk_assessment") else "error"
        return "synthesis"  # All analysis done, run debate/audit/committee

    def _route_after_synthesis(self, state: AgentState) -> str:
        """decision / retry / error."""
        if self._last_attempt_failed(state, "research_synthesis"):
            return "retry" if should_retry(state, "research_synthesis") else "error"
        return "decision"

    def _route_after_decision(self, state: AgentState) -> str:
        """report / retry / error."""
        if self._last_attempt_failed(state, "decision_making"):
            return "retry" if should_retry(state, "decision_making") else "error"
        return "report"

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

    async def get_workflow_status(self, thread_id: str) -> dict[str, Any]:
        """Get the status of a workflow.

        Args:
            thread_id: Thread ID to check

        Returns:
            Status dictionary
        """
        if self.checkpoint_manager:
            state = await self.checkpoint_manager.aload_state(thread_id)
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
