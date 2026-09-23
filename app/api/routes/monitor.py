"""简化的监控 API - 使用轮询方式"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.monitoring import workflow_status

router = APIRouter()


class AgentStatus(BaseModel):
    name: str
    status: str  # pending, running, completed, failed
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None


class WorkflowStatusResponse(BaseModel):
    thread_id: str
    status: str  # pending, running, completed, partial (degraded), failed
    agents: dict[str, AgentStatus]
    current_agent: str | None = None
    running_agents: list[str] = []  # full fan-out set during parallel stages
    progress: float
    created_at: str
    updated_at: str


class LogEntry(BaseModel):
    timestamp: str
    agent: str
    level: str
    message: str


@router.get("/workflow/{thread_id}", response_model=WorkflowStatusResponse)
async def get_workflow_status(thread_id: str):
    """获取工作流状态"""
    state = workflow_status.get_workflow_state(thread_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return state


@router.get("/workflow/{thread_id}/logs")
async def get_workflow_logs(thread_id: str, limit: int = 50):
    """获取工作流日志"""
    logs = workflow_status.get_logs(thread_id, limit=limit)
    return {"logs": logs, "count": len(logs)}


@router.get("/workflows")
async def list_workflows():
    """列出所有工作流"""
    return {"workflows": workflow_status.list_workflows()}


# Re-export the mutators so existing importers keep working; the canonical
# home is app.monitoring.workflow_status.
init_workflow = workflow_status.init_workflow
update_agent_status = workflow_status.update_agent_status
add_log = workflow_status.add_log

__all__ = ["router", "init_workflow", "update_agent_status", "add_log"]
