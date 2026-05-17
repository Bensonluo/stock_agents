"""
SQLite 数据库存储模块
用于持久化存储股票分析历史记录

架构：
- 使用 SQLite 本地文件数据库
- 自动初始化表结构
- 提供完整的 CRUD 操作
- 包含详细日志记录
"""

import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from dataclasses import dataclass, asdict
import threading

logger = logging.getLogger(__name__)

# 数据库文件路径
DB_PATH = Path(__file__).parent.parent.parent / "data" / "analysis_history.db"


@dataclass
class AnalysisRecord:
    """分析记录数据类"""
    id: Optional[int] = None
    thread_id: str = ""
    symbols: str = ""  # JSON 格式的股票代码列表
    query: str = ""
    status: str = "pending"  # pending, running, completed, failed
    result: str = ""  # JSON 格式的分析结果
    created_at: str = ""
    updated_at: str = ""
    execution_time: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


class Database:
    """SQLite database manager with thread-safe connections."""

    _VALID_COLUMNS = {
        "thread_id", "symbols", "query", "status", "result",
        "created_at", "updated_at", "execution_time",
    }

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化数据库"""
        if self._initialized:
            return

        self._local = threading.local()
        self._ensure_db_exists()
        self._initialized = True
        logger.info(f"[DB] 数据库初始化完成: {DB_PATH}")

    def _ensure_db_exists(self):
        """确保数据库文件和表存在"""
        # 创建数据目录
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)

        # 创建表
        with self._get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS analysis_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT UNIQUE NOT NULL,
                    symbols TEXT NOT NULL,
                    query TEXT,
                    status TEXT DEFAULT 'pending',
                    result TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    execution_time REAL DEFAULT 0.0
                )
            ''')

            # 创建索引
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_thread_id
                ON analysis_history(thread_id)
            ''')
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_created_at
                ON analysis_history(created_at DESC)
            ''')
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_status
                ON analysis_history(status)
            ''')

            conn.commit()
            logger.debug("[DB] 表结构初始化完成")

    @contextmanager
    def _get_connection(self):
        """获取线程安全的数据库连接"""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        yield self._local.conn

    def create_record(self, record: AnalysisRecord) -> int:
        """创建新的分析记录

        Args:
            record: 分析记录对象

        Returns:
            新记录的 ID
        """
        now = datetime.now().isoformat()

        with self._get_connection() as conn:
            cursor = conn.execute('''
                INSERT INTO analysis_history
                (thread_id, symbols, query, status, result, created_at, updated_at, execution_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                record.thread_id,
                record.symbols,
                record.query,
                record.status,
                record.result,
                now,
                now,
                record.execution_time
            ))
            conn.commit()

            record_id = cursor.lastrowid
            logger.info(f"[DB] 创建记录: id={record_id}, thread_id={record.thread_id}")
            return record_id

    def get_record(self, thread_id: str) -> Optional[AnalysisRecord]:
        """根据 thread_id 获取记录

        Args:
            thread_id: 工作流线程 ID

        Returns:
            分析记录，不存在返回 None
        """
        with self._get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM analysis_history WHERE thread_id = ?',
                (thread_id,)
            ).fetchone()

            if row:
                logger.debug(f"[DB] 查询记录: thread_id={thread_id}")
                return self._row_to_record(row)

            logger.debug(f"[DB] 记录不存在: thread_id={thread_id}")
            return None

    def get_record_by_id(self, record_id: int) -> Optional[AnalysisRecord]:
        """根据 ID 获取记录"""
        with self._get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM analysis_history WHERE id = ?',
                (record_id,)
            ).fetchone()

            if row:
                return self._row_to_record(row)
            return None

    def update_record(self, thread_id: str, **kwargs) -> bool:
        """Update a record by thread_id.

        Args:
            thread_id: Workflow thread ID
            **kwargs: Fields to update

        Returns:
            True if update succeeded

        Raises:
            ValueError: If any column name is invalid
        """
        if not kwargs:
            return False

        # Validate column names against whitelist
        invalid = set(kwargs.keys()) - self._VALID_COLUMNS
        if invalid:
            raise ValueError(f"Invalid columns: {invalid}")

        kwargs["updated_at"] = datetime.now().isoformat()

        set_clause = ", ".join(f"{k} = ?" for k in kwargs.keys())

        with self._get_connection() as conn:
            cursor = conn.execute(
                f"UPDATE analysis_history SET {set_clause} WHERE thread_id = ?",
                (*kwargs.values(), thread_id)
            )
            conn.commit()

            success = cursor.rowcount > 0
            if success:
                logger.info(f"[DB] Updated record: thread_id={thread_id}, fields={list(kwargs.keys())}")
            return success

    def update_status(self, thread_id: str, status: str, result: str = None, execution_time: float = 0.0) -> bool:
        """更新分析状态和结果

        Args:
            thread_id: 工作流线程 ID
            status: 新状态
            result: 分析结果 (JSON)
            execution_time: 执行时间

        Returns:
            是否更新成功
        """
        now = datetime.now().isoformat()

        with self._get_connection() as conn:
            if result:
                cursor = conn.execute('''
                    UPDATE analysis_history
                    SET status = ?, result = ?, execution_time = ?, updated_at = ?
                    WHERE thread_id = ?
                ''', (status, result, execution_time, now, thread_id))
            else:
                cursor = conn.execute('''
                    UPDATE analysis_history
                    SET status = ?, execution_time = ?, updated_at = ?
                    WHERE thread_id = ?
                ''', (status, execution_time, now, thread_id))

            conn.commit()

            success = cursor.rowcount > 0
            logger.info(f"[DB] 更新状态: thread_id={thread_id}, status={status}")
            return success

    def list_records(
        self,
        limit: int = 20,
        offset: int = 0,
        status: Optional[str] = None
    ) -> List[AnalysisRecord]:
        """获取记录列表

        Args:
            limit: 返回数量限制
            offset: 偏移量
            status: 状态过滤

        Returns:
            记录列表
        """
        with self._get_connection() as conn:
            if status:
                rows = conn.execute('''
                    SELECT * FROM analysis_history
                    WHERE status = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                ''', (status, limit, offset)).fetchall()
            else:
                rows = conn.execute('''
                    SELECT * FROM analysis_history
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                ''', (limit, offset)).fetchall()

            records = [self._row_to_record(row) for row in rows]
            logger.debug(f"[DB] 查询列表: 返回 {len(records)} 条记录")
            return records

    def count_records(self, status: Optional[str] = None) -> int:
        """统计记录数量

        Args:
            status: 状态过滤

        Returns:
            记录数量
        """
        with self._get_connection() as conn:
            if status:
                count = conn.execute(
                    'SELECT COUNT(*) FROM analysis_history WHERE status = ?',
                    (status,)
                ).fetchone()[0]
            else:
                count = conn.execute(
                    'SELECT COUNT(*) FROM analysis_history'
                ).fetchone()[0]

            return count

    def delete_record(self, thread_id: str) -> bool:
        """删除记录

        Args:
            thread_id: 工作流线程 ID

        Returns:
            是否删除成功
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                'DELETE FROM analysis_history WHERE thread_id = ?',
                (thread_id,)
            )
            conn.commit()

            success = cursor.rowcount > 0
            if success:
                logger.info(f"[DB] 删除记录: thread_id={thread_id}")
            return success

    def search_records(self, keyword: str, limit: int = 20) -> List[AnalysisRecord]:
        """搜索记录

        Args:
            keyword: 搜索关键词（匹配股票代码或查询内容）
            limit: 返回数量限制

        Returns:
            匹配的记录列表
        """
        with self._get_connection() as conn:
            rows = conn.execute('''
                SELECT * FROM analysis_history
                WHERE symbols LIKE ? OR query LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
            ''', (f'%{keyword}%', f'%{keyword}%', limit)).fetchall()

            records = [self._row_to_record(row) for row in rows]
            logger.debug(f"[DB] 搜索: keyword={keyword}, 找到 {len(records)} 条")
            return records

    def _row_to_record(self, row: sqlite3.Row) -> AnalysisRecord:
        """将数据库行转换为记录对象"""
        return AnalysisRecord(
            id=row['id'],
            thread_id=row['thread_id'],
            symbols=row['symbols'],
            query=row['query'],
            status=row['status'],
            result=row['result'],
            created_at=row['created_at'],
            updated_at=row['updated_at'],
            execution_time=row['execution_time']
        )


# 全局数据库实例
_db_instance: Optional[Database] = None


def get_database() -> Database:
    """获取全局数据库实例"""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance
