from __future__ import annotations

import logging
import re
import uuid

from ship.claude_code import ClaudeCodeClient
from ship.config import Config
from ship.prompts import PLANNER
from ship.state import StateManager
from ship.types_ import Task, TaskStatus


class Planner:
    """breaks down design files into executable tasks"""

    def __init__(self, cfg: Config, state: StateManager):
        self.cfg = cfg
        self.state = state
        self.claude = ClaudeCodeClient(model="sonnet")
        self.verbose = cfg.verbose

    async def plan_once(self) -> list[Task]:
        """break down goal into tasks (runs once)"""
        work = self.state.get_work_state()
        if not work:
            return []

        logging.info("breaking down goal into tasks")

        context, tasks = await self._parse_design(work.goal_text)

        if context:
            await self.state.set_project_context(context)
            logging.info(f"project context: {context[:100]}...")

        for task in tasks:
            await self.state.add_task(task)
            logging.info(f"created task: {task.description}")

        return tasks

    async def _parse_design(
        self, goal: str
    ) -> tuple[str, list[Task]]:
        prompt = PLANNER.format(goal=goal)

        if self.verbose:
            print(f"\n{'='*60}")
            print("PLANNER PROMPT:")
            print(f"{'='*60}")
            print(prompt)
            print(f"{'='*60}\n")

        try:
            result = await self.claude.execute(prompt, timeout=60)

            if self.verbose:
                print(f"\n{'='*60}")
                print("PLANNER RESPONSE:")
                print(f"{'='*60}")
                print(result)
                print(f"{'='*60}\n")

            return self._parse_xml(result)
        except RuntimeError as e:
            logging.warning(f"claude parsing failed: {e}")
            return "", []

    def _parse_xml(self, text: str) -> tuple[str, list[Task]]:
        context_match = re.search(
            r"<context>(.*?)</context>", text, re.DOTALL
        )
        context = (
            context_match.group(1).strip()
            if context_match else ""
        )

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

        return context, tasks
