from __future__ import annotations

import asyncio
import json
import logging
from copy import copy
from datetime import datetime
from pathlib import Path

from ship.types_ import Task, TaskStatus, WorkState


class StateManager:
    """manages task and work state with async locks for safe concurrent access"""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.tasks_file = self.data_dir / "tasks.json"
        self.work_file = self.data_dir / "work.json"

        self.tasks: dict[str, Task] = {}
        self.work: WorkState | None = None
        self.lock = asyncio.Lock()

        self._load()

    def _load(self) -> None:
        try:
            if self.tasks_file.exists() and self.tasks_file.stat().st_size > 0:
                with open(self.tasks_file) as f:
                    data = json.load(f)
                    for task_data in data:
                        if "created_at" in task_data:
                            task_data["created_at"] = datetime.fromisoformat(
                                task_data["created_at"]
                            )
                        if "started_at" in task_data and task_data["started_at"]:
                            task_data["started_at"] = datetime.fromisoformat(
                                task_data["started_at"]
                            )
                        if "completed_at" in task_data and task_data["completed_at"]:
                            task_data["completed_at"] = datetime.fromisoformat(
                                task_data["completed_at"]
                            )
                        if "retries" not in task_data:
                            task_data["retries"] = 0
                        if "session_id" not in task_data:
                            task_data["session_id"] = ""
                        if "depends_on" not in task_data:
                            task_data["depends_on"] = []
                        if "followups" not in task_data:
                            task_data["followups"] = []
                        if "summary" not in task_data:
                            task_data["summary"] = ""
                        task = Task(**task_data)
                        task.status = TaskStatus(task_data["status"])
                        self.tasks[task.id] = task
        except (OSError, json.JSONDecodeError, ValueError) as e:
            raise RuntimeError(f"failed to load tasks: {e}") from e

        try:
            if self.work_file.exists() and self.work_file.stat().st_size > 0:
                with open(self.work_file) as f:
                    data = json.load(f)
                    if "started_at" in data:
                        data["started_at"] = datetime.fromisoformat(data["started_at"])
                    if "last_updated_at" in data:
                        data["last_updated_at"] = datetime.fromisoformat(
                            data["last_updated_at"]
                        )
                    # backwards compat
                    if "project_context" not in data:
                        data["project_context"] = ""
                    # remove old skills field if present
                    data.pop("skills", None)
                    self.work = WorkState(**data)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            raise RuntimeError(f"failed to load work state: {e}") from e

    def _save_tasks(self) -> None:
        try:
            with open(self.tasks_file, "w") as f:
                json.dump([t.to_dict() for t in self.tasks.values()], f, indent=2)
        except OSError as e:
            raise RuntimeError(f"failed to save tasks: {e}") from e

    def _save_work(self) -> None:
        if self.work:
            try:
                with open(self.work_file, "w") as f:
                    json.dump(self.work.to_dict(), f, indent=2)
            except OSError as e:
                raise RuntimeError(f"failed to save work state: {e}") from e

    async def init_work(self, design_file: str, goal_text: str) -> None:
        async with self.lock:
            self.work = WorkState(
                design_file=design_file,
                goal_text=goal_text,
            )
            self._save_work()

    async def set_project_context(self, context: str) -> None:
        async with self.lock:
            if self.work:
                self.work.project_context = context
                self._save_work()

    async def set_execution_mode(self, mode: str) -> None:
        async with self.lock:
            if self.work:
                self.work.execution_mode = mode
                self._save_work()

    async def add_task(self, task: Task) -> bool:
        async with self.lock:
            if task.id in self.tasks:
                return False
            self.tasks[task.id] = task
            self._save_tasks()
            return True

    async def update_task(
        self,
        task_id: str,
        status: TaskStatus,
        error: str = "",
        result: str = "",
        summary: str = "",
        session_id: str = "",
        followups: list[str] | None = None,
    ) -> None:
        async with self.lock:
            if task_id not in self.tasks:
                logging.warning(
                    f"attempted to update non-existent"
                    f" task: {task_id}"
                )
                return

            task = self.tasks[task_id]
            old_status = task.status
            task.status = status

            if error:
                task.error = error
            if result:
                task.result = result
            if summary:
                task.summary = summary
            if session_id:
                task.session_id = session_id
            if followups:
                task.followups = followups

            if (
                old_status is not TaskStatus.RUNNING
                and status is TaskStatus.RUNNING
            ):
                task.started_at = datetime.now()

            if status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                task.completed_at = datetime.now()

            self._save_tasks()

    async def mark_complete(self) -> None:
        async with self.lock:
            if self.work:
                self.work.is_complete = True
                self.work.last_updated_at = datetime.now()
                self._save_work()

    async def get_pending_tasks(self) -> list[Task]:
        async with self.lock:
            return [
                copy(t) for t in self.tasks.values() if t.status is TaskStatus.PENDING
            ]

    async def get_all_tasks(self) -> list[Task]:
        async with self.lock:
            return [copy(t) for t in self.tasks.values()]

    async def is_complete(self) -> bool:
        async with self.lock:
            if not self.work:
                return False
            if self.work.is_complete:
                return True
            pending = [
                t
                for t in self.tasks.values()
                if t.status is TaskStatus.PENDING or t.status is TaskStatus.RUNNING
            ]
            return len(pending) == 0 and len(self.tasks) > 0

    async def retry_task(self, task_id: str) -> None:
        """reset a failed task to pending and bump retry count"""
        async with self.lock:
            if task_id not in self.tasks:
                return
            task = self.tasks[task_id]
            task.retries += 1
            task.status = TaskStatus.PENDING
            task.error = ""
            task.started_at = None
            task.completed_at = None
            self._save_tasks()

    async def cascade_failure(
        self, task_id: str
    ) -> list[str]:
        """recursively mark tasks depending on task_id as FAILED

        if A->B->C, failing A cascades to B and C.
        """
        cascaded: list[str] = []
        async with self.lock:
            queue = [task_id]
            while queue:
                failed_id = queue.pop(0)
                for task in self.tasks.values():
                    if (
                        failed_id in task.depends_on
                        and task.status in (
                            TaskStatus.PENDING,
                            TaskStatus.RUNNING,
                        )
                    ):
                        task.status = TaskStatus.FAILED
                        task.error = (
                            f"cascade: dependency"
                            f" {failed_id[:8]} failed"
                        )
                        task.completed_at = datetime.now()
                        cascaded.append(task.id)
                        queue.append(task.id)
            if cascaded:
                self._save_tasks()
        return cascaded

    async def reset_interrupted_tasks(self) -> None:
        """reset running + failed tasks to pending on continuation"""
        async with self.lock:
            for task in self.tasks.values():
                if task.status in (TaskStatus.RUNNING, TaskStatus.FAILED):
                    task.status = TaskStatus.PENDING
                    task.retries = 0
                    task.error = ""
                    task.started_at = None
                    task.completed_at = None
            self._save_tasks()

    def get_work_state(self) -> WorkState | None:
        """get work state (synchronous, used during init)"""
        return self.work
