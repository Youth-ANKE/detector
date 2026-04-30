"""
任务管理模块
使用 SQLite 持久化任务状态，支持任务暂停/取消/断点续传
"""
import os
import sqlite3
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """任务状态枚举"""
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


class TaskType(str, Enum):
    """任务类型枚举"""
    IMAGE_DOWNLOAD = "image_download"
    VIDEO_DOWNLOAD = "video_download"
    AUDIO_DOWNLOAD = "audio_download"
    BATCH_DOWNLOAD = "batch_download"


class TaskManager:
    """任务管理器"""

    def __init__(self, db_path: str = "tasks.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化数据库"""
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 创建任务表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER DEFAULT 0,
                    message TEXT DEFAULT '',
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                )
            """)
            
            # 创建任务进度详情表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_details (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    filename TEXT DEFAULT '',
                    error TEXT DEFAULT '',
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                )
            """)
            
            # 创建索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_details_task_id ON task_details(task_id)")
            
            conn.commit()

    def _dict_factory(self, cursor, row):
        """将查询结果转换为字典"""
        fields = [column[0] for column in cursor.description]
        return {key: value for key, value in zip(fields, row)}

    def create_task(
        self,
        task_id: str,
        task_type: TaskType,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """创建新任务"""
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tasks (id, type, status, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (task_id, task_type.value, TaskStatus.QUEUED.value, json.dumps(metadata or {}), now, now))
            conn.commit()
        logger.info(f"任务已创建: {task_id}")

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务信息"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = self._dict_factory
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            result = cursor.fetchone()
            if result:
                result["metadata"] = json.loads(result["metadata"])
            return result

    def update_task(
        self,
        task_id: str,
        **kwargs,
    ) -> None:
        """更新任务信息"""
        now = datetime.now().isoformat()
        updates = []
        params = []
        
        if "status" in kwargs:
            updates.append("status = ?")
            params.append(kwargs["status"])
        
        if "progress" in kwargs:
            updates.append("progress = ?")
            params.append(kwargs["progress"])
        
        if "message" in kwargs:
            updates.append("message = ?")
            params.append(kwargs["message"])
        
        if "metadata" in kwargs:
            updates.append("metadata = ?")
            params.append(json.dumps(kwargs["metadata"]))
        
        if "started_at" in kwargs:
            updates.append("started_at = ?")
            params.append(kwargs["started_at"])
        
        if "completed_at" in kwargs:
            updates.append("completed_at = ?")
            params.append(kwargs["completed_at"])
        
        updates.append("updated_at = ?")
        params.append(now)
        params.append(task_id)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                UPDATE tasks SET {', '.join(updates)}
                WHERE id = ?
            """, params)
            conn.commit()
        logger.debug(f"任务已更新: {task_id}")

    def delete_task(self, task_id: str) -> None:
        """删除任务"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
        logger.info(f"任务已删除: {task_id}")

    def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        task_type: Optional[TaskType] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """列出任务"""
        query = "SELECT * FROM tasks WHERE 1=1"
        params = []
        
        if status:
            query += " AND status = ?"
            params.append(status.value)
        
        if task_type:
            query += " AND type = ?"
            params.append(task_type.value)
        
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = self._dict_factory
            cursor = conn.cursor()
            cursor.execute(query, params)
            results = cursor.fetchall()
            for r in results:
                r["metadata"] = json.loads(r["metadata"])
            return results

    def add_task_details(self, task_id: str, urls: List[str]) -> None:
        """添加任务详情（URL 列表）"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for url in urls:
                cursor.execute("""
                    INSERT INTO task_details (task_id, url, status)
                    VALUES (?, ?, ?)
                """, (task_id, url, "pending"))
            conn.commit()

    def update_task_detail(self, task_id: str, url: str, **kwargs) -> None:
        """更新单个任务详情"""
        updates = []
        params = []
        
        if "status" in kwargs:
            updates.append("status = ?")
            params.append(kwargs["status"])
        
        if "filename" in kwargs:
            updates.append("filename = ?")
            params.append(kwargs["filename"])
        
        if "error" in kwargs:
            updates.append("error = ?")
            params.append(kwargs["error"])
        
        params.extend([task_id, url])
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                UPDATE task_details SET {', '.join(updates)}
                WHERE task_id = ? AND url = ?
            """, params)
            conn.commit()

    def get_task_details(self, task_id: str) -> List[Dict[str, Any]]:
        """获取任务详情列表"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = self._dict_factory
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM task_details WHERE task_id = ?", (task_id,))
            return cursor.fetchall()

    def get_pending_urls(self, task_id: str) -> List[str]:
        """获取待处理的 URL 列表（用于断点续传）"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT url FROM task_details WHERE task_id = ? AND status = 'pending'", (task_id,))
            return [row[0] for row in cursor.fetchall()]

    def get_completed_count(self, task_id: str) -> int:
        """获取已完成的数量"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM task_details WHERE task_id = ? AND status = 'completed'", (task_id,))
            return cursor.fetchone()[0]

    def pause_task(self, task_id: str) -> bool:
        """暂停任务"""
        task = self.get_task(task_id)
        if task and task["status"] == TaskStatus.RUNNING.value:
            self.update_task(task_id, status=TaskStatus.PAUSED.value)
            return True
        return False

    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        task = self.get_task(task_id)
        if task and task["status"] in (TaskStatus.QUEUED.value, TaskStatus.RUNNING.value, TaskStatus.PAUSED.value):
            self.update_task(task_id, status=TaskStatus.CANCELLED.value)
            return True
        return False

    def resume_task(self, task_id: str) -> bool:
        """恢复任务"""
        task = self.get_task(task_id)
        if task and task["status"] == TaskStatus.PAUSED.value:
            self.update_task(task_id, status=TaskStatus.RUNNING.value)
            return True
        return False


# 全局任务管理器实例
task_manager = TaskManager()
