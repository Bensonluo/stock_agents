"""简化的监控 API - 使用轮询方式"""

from fastapi import APIRouter, HTTPException
from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel
import asyncio

router = APIRouter()

# 全局状态存储
_workflow_states: Dict[str, Dict] = {}
_agent_logs: Dict[str, List[Dict]] = {}

class AgentStatus(BaseModel):
    name: str
    status: str  # pending, running, completed, failed
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None

class WorkflowStatusResponse(BaseModel):
    thread_id: str
    status: str  # pending, running, completed, failed
    agents: Dict[str, AgentStatus]
    current_agent: Optional[str] = None
    progress: float = 0.0
    created_at: str
    updated_at: str

class LogEntry(BaseModel):
    timestamp: str
    agent: str
    level: str
    message: str

# 初始化工作流状态
def init_workflow(thread_id: str):
    """初始化工作流状态"""
    agents = [
        "data_collection",
        "technical_analysis",
        "fundamental_analysis",
        "sentiment_analysis",
        "risk_assessment",
        "decision_making",
        "report_generation"
    ]

    _workflow_states[thread_id] = {
        "thread_id": thread_id,
        "status": "pending",
        "agents": {a: {"name": a, "status": "pending"} for a in agents},
        "current_agent": None,
        "progress": 0.0,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    _agent_logs[thread_id] = []

# 更新智能体状态
def update_agent_status(thread_id: str, agent: str, status: str, error: str = None):
    """更新智能体状态"""
    if thread_id not in _workflow_states:
        init_workflow(thread_id)

    state = _workflow_states[thread_id]
    state["agents"][agent] = {
        "name": agent,
        "status": status,
        "started_at": datetime.now().isoformat() if status == "running" else state["agents"][agent].get("started_at"),
        "completed_at": datetime.now().isoformat() if status in ["completed", "failed"] else None,
        "error": error
    }
    state["current_agent"] = agent if status == "running" else None
    state["updated_at"] = datetime.now().isoformat()

    # 计算进度
    completed = sum(1 for a in state["agents"].values() if a["status"] == "completed")
    state["progress"] = (completed / len(state["agents"])) * 100

    # 更新整体状态
    if status == "running":
        state["status"] = "running"
    elif all(a["status"] == "completed" for a in state["agents"].values()):
        state["status"] = "completed"
    elif any(a["status"] == "failed" for a in state["agents"].values()):
        state["status"] = "failed"

# 添加日志
def add_log(thread_id: str, agent: str, level: str, message: str):
    """添加日志条目"""
    if thread_id not in _agent_logs:
        _agent_logs[thread_id] = []

    _agent_logs[thread_id].append({
        "timestamp": datetime.now().isoformat(),
        "agent": agent,
        "level": level,
        "message": message
    })

    # 保留最近 200 条
    if len(_agent_logs[thread_id]) > 200:
        _agent_logs[thread_id] = _agent_logs[thread_id][-200:]

@router.get("/workflow/{thread_id}", response_model=WorkflowStatusResponse)
async def get_workflow_status(thread_id: str):
    """获取工作流状态"""
    if thread_id not in _workflow_states:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return _workflow_states[thread_id]

@router.get("/workflow/{thread_id}/logs")
async def get_workflow_logs(thread_id: str, limit: int = 50):
    """获取工作流日志"""
    if thread_id not in _agent_logs:
        return {"logs": [], "count": 0}

    logs = _agent_logs[thread_id][-limit:]
    return {"logs": logs, "count": len(logs)}

@router.get("/workflows")
async def list_workflows():
    """列出所有工作流"""
    return {
        "workflows": [
            {
                "thread_id": tid,
                "status": state["status"],
                "progress": state["progress"],
                "updated_at": state["updated_at"]
            }
            for tid, state in _workflow_states.items()
        ]
    }

# 导出辅助函数
__all__ = ["router", "init_workflow", "update_agent_status", "add_log"]
