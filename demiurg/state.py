from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from demiurg.types_ import Task, TaskStatus, WorkState


class StateManager:
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
                        data["started_at"] = datetime.fromisoformat(
                            data["started_at"]
                        )
                    if "last_updated_at" in data:
                        data["last_updated_at"] = datetime.fromisoformat(
                            data["last_updated_at"]
                        )
                    self.work = WorkState(**data)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            raise RuntimeError(f"failed to load work state: {e}") from e

    def _save_tasks(self) -> None:
        try:
            with open(self.tasks_file, "w") as f:
                json.dump(
                    [t.to_dict() for t in self.tasks.values()], f, indent=2
                )
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
            self.work = WorkState(design_file=design_file, goal_text=goal_text)
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
    ) -> None:
        async with self.lock:
            if task_id not in self.tasks:
                return

            task = self.tasks[task_id]
            old_status = task.status
            task.status = status

            if error:
                task.error = error
            if result:
                task.result = result

            if old_status is not TaskStatus.RUNNING and status is TaskStatus.RUNNING:
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
            return list(t for t in self.tasks.values() if t.status is TaskStatus.PENDING)

    async def get_all_tasks(self) -> list[Task]:
        async with self.lock:
            return list(self.tasks.values())

    async def is_complete(self) -> bool:
        async with self.lock:
            if not self.work:
                return False
            if self.work.is_complete:
                return True
            pending = [
                t for t in self.tasks.values()
                if t.status is TaskStatus.PENDING or t.status is TaskStatus.RUNNING
            ]
            return len(pending) == 0 and len(self.tasks) > 0

    async def reset_interrupted_tasks(self) -> None:
        """reset running tasks to pending on startup (continuation)"""
        async with self.lock:
            for task in self.tasks.values():
                if task.status is TaskStatus.RUNNING:
                    task.status = TaskStatus.PENDING
                    task.started_at = None
            self._save_tasks()

    def get_work_state(self) -> WorkState | None:
        """get work state (synchronous, used during init)"""
        return self.work
