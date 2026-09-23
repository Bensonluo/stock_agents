"""In-memory workflow status store shared by the orchestrator and the monitor API.

Extracted from the API layer so the orchestration layer can record progress
without depending on FastAPI routes.
"""

from datetime import datetime

# Agents pre-registered for progress display, in pipeline order.
PIPELINE_AGENTS = [
    "data_collection",
    "technical_analysis",
    "fundamental_analysis",
    "sentiment_analysis",
    "risk_assessment",
    "research_synthesis",
    "decision_making",
    "report_generation",
]

MAX_LOG_ENTRIES = 200
# Cap on tracked workflows; the oldest finished ones are evicted first so a
# long-running process does not grow the store without bound.
MAX_TRACKED_WORKFLOWS = 100

# Global state stores (thread_id keyed)
_workflow_states: dict[str, dict] = {}
_agent_logs: dict[str, list[dict]] = {}


def _evict_oldest_if_full() -> None:
    """Evict one workflow when the store is at capacity.

    Terminal (completed/failed) workflows are evicted by oldest updated_at;
    only when none are terminal does the oldest running one get evicted.
    """
    if len(_workflow_states) < MAX_TRACKED_WORKFLOWS:
        return

    terminal = [
        tid
        for tid, s in _workflow_states.items()
        if s.get("status") in ("completed", "failed", "partial")
    ]
    pool = terminal or list(_workflow_states)
    victim = min(pool, key=lambda tid: _workflow_states[tid].get("updated_at", ""))

    del _workflow_states[victim]
    _agent_logs.pop(victim, None)


def init_workflow(thread_id: str):
    """初始化工作流状态"""
    _evict_oldest_if_full()
    _workflow_states[thread_id] = {
        "thread_id": thread_id,
        "status": "pending",
        "agents": {a: {"name": a, "status": "pending"} for a in PIPELINE_AGENTS},
        "current_agent": None,
        "running_agents": [],
        "progress": 0.0,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    _agent_logs[thread_id] = []


def update_agent_status(thread_id: str, agent: str, status: str, error: str | None = None):
    """更新智能体状态"""
    if thread_id not in _workflow_states:
        init_workflow(thread_id)

    state = _workflow_states[thread_id]
    previous = state["agents"].get(agent, {})
    state["agents"][agent] = {
        "name": agent,
        "status": status,
        "started_at": (
            datetime.now().isoformat() if status == "running" else previous.get("started_at")
        ),
        "completed_at": datetime.now().isoformat() if status in ("completed", "failed") else None,
        "error": error,
    }
    # 并行阶段会有多个 agent 同时 running：current_agent 取流水线顺序里第一个
    # 还在跑的（标量语义不变：None = 空闲），running_agents 给出完整在跑集合。
    running = [name for name, info in state["agents"].items() if info["status"] == "running"]
    state["current_agent"] = running[0] if running else None
    state["running_agents"] = running
    state["updated_at"] = datetime.now().isoformat()

    # 计算进度：终态（completed/failed）都计入，降级跑完的进度也能到 100%
    terminal = sum(1 for a in state["agents"].values() if a["status"] in ("completed", "failed"))
    state["progress"] = (terminal / len(state["agents"])) * 100

    # 更新整体状态。全部 agent 到终态时按有无失败分流：有失败但流水线走完 =
    # 优雅降级（与 DB 侧 "partial" 语义对齐，而不是误报 failed）；失败且还有
    # agent 未到终态 = 关键节点中止（error handler 路径，之后不会再有更新）。
    failed = any(a["status"] == "failed" for a in state["agents"].values())
    if status == "running":
        state["status"] = "running"
    elif terminal == len(state["agents"]):
        state["status"] = "partial" if failed else "completed"
    elif failed:
        state["status"] = "failed"


def add_log(thread_id: str, agent: str, level: str, message: str):
    """添加日志条目"""
    if thread_id not in _agent_logs:
        _agent_logs[thread_id] = []

    _agent_logs[thread_id].append(
        {
            "timestamp": datetime.now().isoformat(),
            "agent": agent,
            "level": level,
            "message": message,
        }
    )

    # 保留最近 MAX_LOG_ENTRIES 条
    if len(_agent_logs[thread_id]) > MAX_LOG_ENTRIES:
        _agent_logs[thread_id] = _agent_logs[thread_id][-MAX_LOG_ENTRIES:]


def get_workflow_state(thread_id: str) -> dict | None:
    """获取工作流状态(不存在返回 None)"""
    return _workflow_states.get(thread_id)


def get_logs(thread_id: str, limit: int = 50) -> list[dict]:
    """获取日志条目(最新在前取尾部 limit 条)"""
    return _agent_logs.get(thread_id, [])[-limit:]


def list_workflows() -> list[dict]:
    """列出所有工作流摘要"""
    return [
        {
            "thread_id": tid,
            "status": state["status"],
            "progress": state["progress"],
            "updated_at": state["updated_at"],
        }
        for tid, state in _workflow_states.items()
    ]


def reset() -> None:
    """清空全部状态(测试用)"""
    _workflow_states.clear()
    _agent_logs.clear()
