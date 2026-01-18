from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class Task:
    id: str
    description: str
    files: list[str]
    status: TaskStatus
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str = ""
    result: str = ""

    def to_dict(self):
        d = {
            "id": self.id,
            "description": self.description,
            "files": self.files,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "error": self.error,
            "result": self.result,
        }
        if self.started_at:
            d["started_at"] = self.started_at.isoformat()
        if self.completed_at:
            d["completed_at"] = self.completed_at.isoformat()
        return d


@dataclass(slots=True)
class WorkState:
    design_file: str
    goal_text: str
    is_complete: bool = False
    started_at: datetime = field(default_factory=datetime.now)
    last_updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self):
        return {
            "design_file": self.design_file,
            "goal_text": self.goal_text,
            "is_complete": self.is_complete,
            "started_at": self.started_at.isoformat(),
            "last_updated_at": self.last_updated_at.isoformat(),
        }
