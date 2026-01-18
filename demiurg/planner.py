from __future__ import annotations

import json
import logging
import uuid

from demiurg.claude_code import ClaudeCodeClient
from demiurg.config import Config
from demiurg.state import StateManager
from demiurg.types_ import Task, TaskStatus


class Planner:
    def __init__(self, cfg: Config, state: StateManager):
        self.cfg = cfg
        self.state = state
        self.claude = ClaudeCodeClient(model="sonnet", cwd=cfg.target_dir)

    async def plan_once(self) -> list[Task]:
        """break down goal into tasks (runs once)"""
        work = self.state.get_work_state()
        if not work:
            return []

        logging.info("breaking down goal into tasks")

        tasks = await self._parse_tasks(work.goal_text)

        for task in tasks:
            await self.state.add_task(task)
            logging.info(f"created task: {task.description}")

        return tasks

    async def _parse_tasks(self, goal: str) -> list[Task]:
        """parse goal text into tasks using Claude Code CLI"""
        prompt = f"""Parse this design document into a list of concrete, actionable tasks.

Design document:
{goal}

Return a JSON array of tasks. Each task should have:
- description: clear, actionable task description (imperative, starts with verb)
- priority: low/medium/high
- estimated_complexity: simple/moderate/complex

Example output format:
[
  {{"description": "Create pyproject.toml with dependencies", "priority": "high", "estimated_complexity": "simple"}},
  {{"description": "Implement streaming client class", "priority": "high", "estimated_complexity": "moderate"}}
]

Return ONLY the JSON array, no other text."""

        try:
            result = await self.claude.execute(prompt, timeout=60)
            task_data = json.loads(result)

            if not isinstance(task_data, list):
                raise ValueError("expected JSON array")

            tasks = []
            for item in task_data:
                if not isinstance(item, dict) or "description" not in item:
                    continue

                task = Task(
                    id=str(uuid.uuid4()),
                    description=item["description"],
                    files=[],
                    status=TaskStatus.PENDING,
                )
                tasks.append(task)

            if not tasks:
                raise ValueError("no valid tasks parsed")

            return tasks

        except (json.JSONDecodeError, ValueError, RuntimeError) as e:
            logging.warning(f"claude parsing failed: {e}, falling back to simple parsing")
            return self._simple_parse(goal)

    def _simple_parse(self, goal: str) -> list[Task]:
        """fallback: simple line-based parsing"""
        tasks = []
        lines = goal.split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # skip full-line comments (start with #)
            if line.startswith("# "):
                continue

            # parse task lines (bullets, asterisks, or headings)
            if line.startswith(("-", "*", "###", "##")):
                desc = line.lstrip("-*#").strip()
                if desc and len(desc) > 5:
                    task = Task(
                        id=str(uuid.uuid4()),
                        description=desc,
                        files=[],
                        status=TaskStatus.PENDING,
                    )
                    tasks.append(task)

        if not tasks:
            task = Task(
                id=str(uuid.uuid4()),
                description=goal[:200] if len(goal) > 200 else goal,
                files=[],
                status=TaskStatus.PENDING,
            )
            tasks.append(task)

        return tasks
