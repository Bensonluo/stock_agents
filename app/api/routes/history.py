"""
分析历史记录 API 路由

提供以下接口：
- GET /api/history - 获取历史记录列表
- GET /api/history/{thread_id} - 获取单条记录详情
- DELETE /api/history/{thread_id} - 删除记录
- GET /api/history/search - 搜索记录
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import json
import logging

from app.storage.database import get_database, AnalysisRecord

logger = logging.getLogger(__name__)
router = APIRouter()


# ============ 响应模型 ============

class HistoryListItem(BaseModel):
    """历史记录列表项"""
    id: int
    thread_id: str
    symbols: List[str]
    query: str
    status: str
    created_at: str
    updated_at: str
    execution_time: float
    
    class Config:
        from_attributes = True


class HistoryDetail(BaseModel):
    """历史记录详情"""
    id: int
    thread_id: str
    symbols: List[str]
    query: str
    status: str
    result: dict
    created_at: str
    updated_at: str
    execution_time: float


class HistoryListResponse(BaseModel):
    """历史记录列表响应"""
    items: List[HistoryListItem]
    total: int
    page: int
    page_size: int
    has_more: bool


class HistoryStatsResponse(BaseModel):
    """历史统计响应"""
    total_analyses: int
    completed: int
    failed: int
    pending: int
    running: int


# ============ 辅助函数 ============

def record_to_list_item(record: AnalysisRecord) -> HistoryListItem:
    """将数据库记录转换为列表项"""
    try:
        symbols = json.loads(record.symbols) if record.symbols else []
    except json.JSONDecodeError:
        symbols = []
    
    return HistoryListItem(
        id=record.id,
        thread_id=record.thread_id,
        symbols=symbols,
        query=record.query or "",
        status=record.status,
        created_at=record.created_at,
        updated_at=record.updated_at,
        execution_time=record.execution_time or 0.0
    )


def record_to_detail(record: AnalysisRecord) -> HistoryDetail:
    """将数据库记录转换为详情"""
    try:
        symbols = json.loads(record.symbols) if record.symbols else []
    except json.JSONDecodeError:
        symbols = []
    
    try:
        result = json.loads(record.result) if record.result else {}
    except json.JSONDecodeError:
        result = {}
    
    return HistoryDetail(
        id=record.id,
        thread_id=record.thread_id,
        symbols=symbols,
        query=record.query or "",
        status=record.status,
        result=result,
        created_at=record.created_at,
        updated_at=record.updated_at,
        execution_time=record.execution_time or 0.0
    )


# ============ API 端点 ============

@router.get("", response_model=HistoryListResponse)
async def list_history(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    status: Optional[str] = Query(None, description="状态过滤"),
):
    """
    获取分析历史记录列表
    
    Args:
        page: 页码（从1开始）
        page_size: 每页数量
        status: 可选的状态过滤
        
    Returns:
        分页的历史记录列表
    """
    logger.info(f"[History API] 获取列表: page={page}, page_size={page_size}, status={status}")
    
    db = get_database()
    
    # 计算偏移量
    offset = (page - 1) * page_size
    
    # 获取记录
    records = db.list_records(limit=page_size, offset=offset, status=status)
    total = db.count_records(status=status)
    
    # 转换为响应格式
    items = [record_to_list_item(r) for r in records]
    
    logger.info(f"[History API] 返回 {len(items)} 条记录，总计 {total} 条")
    
    return HistoryListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_more=(offset + len(items)) < total
    )


@router.get("/stats", response_model=HistoryStatsResponse)
async def get_history_stats():
    """
    获取历史统计信息
    
    Returns:
        各状态的记录数量统计
    """
    logger.info("[History API] 获取统计信息")
    
    db = get_database()
    
    return HistoryStatsResponse(
        total_analyses=db.count_records(),
        completed=db.count_records(status="completed"),
        failed=db.count_records(status="failed"),
        pending=db.count_records(status="pending"),
        running=db.count_records(status="running")
    )


@router.get("/search")
async def search_history(
    keyword: str = Query(..., min_length=1, description="搜索关键词"),
    limit: int = Query(20, ge=1, le=50, description="返回数量"),
):
    """
    搜索历史记录
    
    Args:
        keyword: 搜索关键词（匹配股票代码或查询内容）
        limit: 返回数量
        
    Returns:
        匹配的记录列表
    """
    logger.info(f"[History API] 搜索: keyword={keyword}, limit={limit}")
    
    db = get_database()
    records = db.search_records(keyword=keyword, limit=limit)
    items = [record_to_list_item(r) for r in records]
    
    logger.info(f"[History API] 搜索到 {len(items)} 条记录")
    
    return {
        "items": items,
        "keyword": keyword,
        "count": len(items)
    }


@router.get("/{thread_id}")
async def get_history_detail(thread_id: str):
    """
    获取单条历史记录详情
    
    Args:
        thread_id: 工作流线程 ID
        
    Returns:
        完整的分析记录详情
    """
    logger.info(f"[History API] 获取详情: thread_id={thread_id}")
    
    db = get_database()
    record = db.get_record(thread_id)
    
    if not record:
        logger.warning(f"[History API] 记录不存在: thread_id={thread_id}")
        raise HTTPException(status_code=404, detail="记录不存在")
    
    logger.info(f"[History API] 返回详情: thread_id={thread_id}")
    return record_to_detail(record)


@router.delete("/{thread_id}")
async def delete_history(thread_id: str):
    """
    删除历史记录
    
    Args:
        thread_id: 工作流线程 ID
        
    Returns:
        删除结果
    """
    logger.info(f"[History API] 删除记录: thread_id={thread_id}")
    
    db = get_database()
    success = db.delete_record(thread_id)
    
    if not success:
        logger.warning(f"[History API] 删除失败: thread_id={thread_id}")
        raise HTTPException(status_code=404, detail="记录不存在")
    
    logger.info(f"[History API] 删除成功: thread_id={thread_id}")
    
    return {
        "success": True,
        "message": "记录已删除",
        "thread_id": thread_id
    }
