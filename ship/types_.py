from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    """task execution states"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class Task:
    """represents a single executable task"""

    id: str
    description: str
    files: list[str]
    status: TaskStatus
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    retries: int = 0
    error: str = ""
    result: str = ""
    session_id: str = ""
    depends_on: list[str] = field(default_factory=list)
    followups: list[str] = field(default_factory=list)
    worker: str = "auto"  # "auto" or specific worker id like "w0"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "description": self.description,
            "files": self.files,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "retries": self.retries,
            "error": self.error,
            "result": self.result,
            "session_id": self.session_id,
            "depends_on": self.depends_on,
            "followups": self.followups,
            "worker": self.worker,
        }
        if self.started_at:
            d["started_at"] = self.started_at.isoformat()
        if self.completed_at:
            d["completed_at"] = self.completed_at.isoformat()
        return d


@dataclass(slots=True)
class WorkState:
    """tracks overall work progress and goal state"""

    design_file: str
    goal_text: str
    is_complete: bool = False
    project_context: str = ""  # brief description for workers
    execution_mode: str = "parallel"  # "parallel" or "sequential"
    started_at: datetime = field(default_factory=datetime.now)
    last_updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "design_file": self.design_file,
            "goal_text": self.goal_text,
            "is_complete": self.is_complete,
            "project_context": self.project_context,
            "execution_mode": self.execution_mode,
            "started_at": self.started_at.isoformat(),
            "last_updated_at": self.last_updated_at.isoformat(),
        }
