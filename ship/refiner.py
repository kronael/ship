from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from ship.codex_cli import CodexClient
from ship.display import display
from ship.prompts import REFINER
from ship.state import StateManager
from ship.types_ import Task, TaskStatus


class Refiner:
    """codex critiques the batch using PROGRESS.md + task state"""

    def __init__(
        self,
        state: StateManager,
        project_context: str = "",
        verbose: bool = False,
    ):
        self.state = state
        self.project_context = project_context
        self.verbose = verbose
        self.codex = CodexClient()

    async def refine(self) -> list[Task]:
        all_tasks = await self.state.get_all_tasks()

        completed = [
            t for t in all_tasks
            if t.status is TaskStatus.COMPLETED
        ]
        failed = [
            t for t in all_tasks
            if t.status is TaskStatus.FAILED
        ]

        if not completed and not failed:
            return []

        progress = ""
        try:
            progress = Path("PROGRESS.md").read_text()
        except OSError:
            pass

        completed_summary = "\n".join(
            f"- [DONE] {t.description}" for t in completed[-10:]
        ) or "None"
        failed_summary = "\n".join(
            f"- [FAIL] {t.description}: {t.error}"
            for t in failed[-5:]
        ) or "None"

        progress_section = (
            f"PROGRESS.md (includes judge verdicts):\n{progress}"
            if progress else ""
        )

        prompt = REFINER.format(
            project_context=self.project_context,
            progress_section=progress_section,
            completed_summary=completed_summary,
            failed_summary=failed_summary,
        )

        if self.verbose:
            display.event(f"  refiner prompt: {len(prompt)} chars")
        else:
            display.event("  refiner: codex critiquing...")

        try:
            result = await self.codex.execute(prompt, timeout=60)

            if self.verbose:
                display.event(
                    f"  refiner response: {len(result)} chars"
                )

            new_tasks = self._parse_tasks(result)
            for task in new_tasks:
                await self.state.add_task(task)
                logging.info(
                    f"refiner created task: {task.description}"
                )

            if not new_tasks:
                display.event("  refiner: no follow-up tasks")
            return new_tasks

        except RuntimeError as e:
            logging.warning(f"refiner failed: {e}")
            display.event(f"  refiner failed: {e}")
            return []

    def _parse_tasks(self, text: str) -> list[Task]:
        tasks = []
        for desc in re.findall(
            r"<task>(.*?)</task>", text, re.DOTALL
        ):
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
