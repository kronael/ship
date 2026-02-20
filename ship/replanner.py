from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from ship.claude_code import ClaudeCodeClient
from ship.display import display
from ship.prompts import REPLANNER
from ship.state import StateManager
from ship.types_ import Task, TaskStatus


class Replanner:
    def __init__(
        self,
        state: StateManager,
        project_context: str = "",
        verbosity: int = 1,
        progress_path: str = "PROGRESS.md",
    ):
        self.state = state
        self.project_context = project_context
        self.verbosity = verbosity
        self.progress_path = progress_path
        self.claude = ClaudeCodeClient(
            model="sonnet",
            role="replanner",
        )

    async def replan(self) -> list[Task]:
        work = self.state.get_work_state()
        if not work:
            return []

        all_tasks = await self.state.get_all_tasks()
        completed = [t for t in all_tasks if t.status is TaskStatus.COMPLETED]
        failed = [t for t in all_tasks if t.status is TaskStatus.FAILED]

        completed_summary = (
            "\n".join(f"- {t.description}" for t in completed[-15:]) or "None"
        )
        failed_summary = (
            "\n".join(f"- {t.description}: {t.error}" for t in failed[-5:]) or "None"
        )

        try:
            progress = Path(self.progress_path).read_text()
        except OSError:
            progress = ""
        try:
            plan = Path(self.progress_path).parent.joinpath("PLAN.md").read_text()
        except OSError:
            plan = ""

        progress_section = (
            f"PROGRESS.md (includes per-task judgments):\n{progress[:1500]}"
            if progress
            else ""
        )
        plan_section = f"PLAN.md:\n{plan[:1000]}" if plan else ""

        prompt = REPLANNER.format(
            project_context=self.project_context,
            goal_text=work.goal_text[:2000],
            plan_section=plan_section,
            progress_section=progress_section,
            completed_summary=completed_summary,
            failed_summary=failed_summary,
            progress_path=self.progress_path,
        )

        if self.verbosity >= 3:
            display.event(f"  replanner prompt: {len(prompt)} chars", min_level=3)
        else:
            display.event("  replanner: full assessment...", min_level=2)

        try:
            result, _ = await self.claude.execute(prompt, timeout=90)
            if self.verbosity >= 3:
                display.event(f"  replanner response: {len(result)} chars", min_level=3)
            new_tasks = self._parse_tasks(result)
            for task in new_tasks:
                await self.state.add_task(task)
                logging.info(f"replanner created task: {task.description}")
            if not new_tasks:
                display.event("  replanner: goal met")
            return new_tasks
        except RuntimeError as e:
            logging.warning(f"replanner timed out or errored: {e}")
            display.event(f"  replanner failed: {e}")
            raise

    def _parse_tasks(self, text: str) -> list[Task]:
        tasks = []
        for desc in re.findall(r"<task>(.*?)</task>", text, re.DOTALL):
            desc = desc.strip()
            if desc and len(desc) > 5:
                tasks.append(
                    Task(
                        id=str(uuid.uuid4()),
                        description=desc,
                        files=[],
                        status=TaskStatus.PENDING,
                    )
                )
        return tasks
