"""Base agent class for all agents in the system."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from langchain_core.language_models import BaseChatModel

from app.monitoring import AgentMonitor, get_monitor
from app.orchestration.state import AgentState
from app.resilience import (
    CircuitBreakerRegistry,
    TimeLimiter,
    get_circuit_breaker_registry,
    get_time_limiter,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)


class BaseAgent(ABC):
    """Base class for all agents.

    This class provides:
    - Common initialization for all agents
    - Monitoring integration
    - Resilience patterns (timeout, circuit breaker)
    - State management helpers

    Core learning: Understanding agent design patterns.
    """

    def __init__(
        self,
        name: str,
        llm: Optional[BaseChatModel] = None,
        monitor: Optional[AgentMonitor] = None,
        circuit_breaker_registry: Optional[CircuitBreakerRegistry] = None,
        time_limiter: Optional[TimeLimiter] = None,
        timeout: Optional[int] = None,
    ):
        """Initialize the base agent.

        Args:
            name: Unique name for this agent
            llm: Optional language model for AI operations
            monitor: Optional monitor for tracking metrics
            circuit_breaker_registry: Optional circuit breaker registry
            time_limiter: Optional time limiter for timeout control
            timeout: Optional default timeout in seconds
        """
        self.name = name
        self.llm = llm

        # Get global instances if not provided
        self.monitor = monitor or get_monitor()
        self.circuit_breaker_registry = circuit_breaker_registry or get_circuit_breaker_registry()
        self.time_limiter = time_limiter or get_time_limiter()

        # Configuration
        from app.config import settings
        self.timeout = timeout or settings.timeout_per_agent
        self.max_retries = settings.max_retries

        logger.info(f"Initialized agent: {self.name}")

    @abstractmethod
    async def execute(self, state: AgentState) -> AgentState:
        """Execute the agent's primary logic.

        This method must be implemented by all subclasses.

        Args:
            state: Current agent state

        Returns:
            Updated agent state
        """
        pass

    async def run(self, state: AgentState) -> AgentState:
        """Run the agent with monitoring and resilience.

        This method wraps the execute method with:
        - Monitoring hooks (on_start, on_success, on_failure)
        - Circuit breaker protection
        - Timeout control
        - Error handling

        Args:
            state: Current agent state

        Returns:
            Updated agent state
        """
        import time
        from datetime import datetime

        # Check circuit breaker
        if not self.circuit_breaker_registry.allow_request(self.name):
            logger.warning(f"Circuit breaker is open for agent: {self.name}")

            self.monitor.on_agent_failure(
                agent_name=self.name,
                error="Circuit breaker is open",
                execution_time=0.0,
                error_type="CircuitBreakerOpenError",
            )

            # Add error to state
            from app.orchestration.state import add_error
            state = add_error(
                state,
                self.name,
                "CircuitBreakerOpenError",
                "Circuit breaker is open for this agent",
                retryable=False,
            )

            return state

        # Record start
        start_time = time.time()
        self.monitor.on_agent_start(self.name, state)

        try:
            # Execute with timeout
            result_state = await self.time_limiter.execute_with_timeout(
                self.execute,
                state,
                timeout=self.timeout,
                name=self.name,
            )

            # Record success
            execution_time = time.time() - start_time
            self.monitor.on_agent_success(
                agent_name=self.name,
                execution_time=execution_time,
                result=self._extract_result_summary(state),
            )

            # Record circuit breaker success
            self.circuit_breaker_registry.record_success(self.name)

            return result_state

        except Exception as e:
            execution_time = time.time() - start_time
            error_type = type(e).__name__
            error_message = str(e)

            # Check if it's a timeout
            if "TimeoutError" in error_type or "timeout" in error_message.lower():
                self.monitor.on_agent_timeout(
                    agent_name=self.name,
                    timeout_limit=self.timeout,
                )
                self.circuit_breaker_registry.record_failure(self.name, "Timeout")
            else:
                # Record failure
                is_retryable = self._is_retryable_error(error_type)
                self.monitor.on_agent_failure(
                    agent_name=self.name,
                    error=error_message,
                    execution_time=execution_time,
                    error_type=error_type,
                )

                if is_retryable:
                    self.circuit_breaker_registry.record_failure(self.name, error_type)
                else:
                    # Non-retryable errors shouldn't trigger circuit breaker
                    pass

                # Add error to state
                from app.orchestration.state import add_error
                state = add_error(
                    state,
                    self.name,
                    error_type,
                    error_message,
                    retryable=is_retryable,
                )

            return state

    def _is_retryable_error(self, error_type: str) -> bool:
        """Check if an error type is retryable.

        Args:
            error_type: Type name of the error

        Returns:
            True if the error should be retried
        """
        retryable_errors = [
            "TimeoutError",
            "ConnectionError",
            "RateLimitError",
            "TemporaryFailure",
            "HTTPError",
            "RequestException",
            "APIError",
        ]
        return error_type in retryable_errors

    def _extract_result_summary(self, state: AgentState) -> Dict[str, Any]:
        """Extract a summary of results from the state.

        Args:
            state: Current agent state

        Returns:
            Summary dictionary
        """
        summary = {"agent": self.name}

        # Add relevant data based on agent type
        if self.name == "data_collection":
            if state.get("market_data"):
                summary["symbols_collected"] = len(state.get("market_data", {}))
        elif self.name == "technical_analysis":
            if state.get("technical_analysis"):
                summary["has_technical_analysis"] = True
        elif self.name == "fundamental_analysis":
            if state.get("fundamental_analysis"):
                summary["has_fundamental_analysis"] = True
        elif self.name == "sentiment_analysis":
            if state.get("sentiment_analysis"):
                summary["has_sentiment_analysis"] = True
        elif self.name == "risk_assessment":
            if state.get("risk_assessment"):
                summary["has_risk_assessment"] = True
        elif self.name == "decision_making":
            if state.get("decision"):
                summary["has_decision"] = True
        elif self.name == "report_generation":
            if state.get("report"):
                summary["has_report"] = True

        return summary

    async def invoke_llm(self, prompt: str, **kwargs) -> str:
        """Invoke the LLM with a prompt.

        Args:
            prompt: Prompt to send to the LLM
            **kwargs: Additional arguments for the LLM

        Returns:
            LLM response as a string

        Raises:
            ValueError: If LLM is not configured
        """
        if not self.llm:
            raise ValueError(f"LLM not configured for agent: {self.name}")

        from langchain_core.messages import HumanMessage

        response = await self.llm.ainvoke(
            [HumanMessage(content=prompt)],
            **kwargs,
        )

        return response.content

    def get_status(self) -> Dict[str, Any]:
        """Get the current status of this agent.

        Returns:
            Dictionary containing agent status
        """
        return {
            "name": self.name,
            "health": self.monitor.get_agent_health(self.name),
            "circuit_breaker_state": self.circuit_breaker_registry.get(
                self.name
            ).get_state().value,
        }


class StatelessAgent(BaseAgent):
    """Base class for stateless agents that don't modify the state.

    Some agents only read data and don't modify the state.
    This base class simplifies such agents.
    """

    @abstractmethod
    async def process(self, state: AgentState) -> Dict[str, Any]:
        """Process the state and return results.

        Args:
            state: Current agent state

        Returns:
            Dictionary containing results
        """
        pass

    async def execute(self, state: AgentState) -> AgentState:
        """Execute the agent.

        For stateless agents, this just calls process and
        adds the results to the agent_outputs.

        Args:
            state: Current agent state

        Returns:
            Updated agent state
        """
        from app.orchestration.state import add_agent_output

        result = await self.process(state)

        # Add result to agent outputs
        state = add_agent_output(state, self.name, result)

        return state
