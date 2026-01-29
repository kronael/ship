from __future__ import annotations

import logging
import re
import uuid

from demiurg.claude_code import ClaudeCodeClient
from demiurg.config import Config
from demiurg.state import StateManager
from demiurg.types_ import Task, TaskStatus


class Planner:
    """breaks down design files into executable tasks using claude code CLI"""

    def __init__(self, cfg: Config, state: StateManager):
        self.cfg = cfg
        self.state = state
        self.claude = ClaudeCodeClient(model="sonnet")

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
        """parse goal text into tasks using Claude"""
        prompt = f"""Extract executable tasks from this design document.

<design>
{goal}
</design>

Rules:
- Each task must be a concrete, completable coding action
- Task description starts with a verb (Create, Add, Implement, Write)
- Skip explanations, examples, documentation sections
- If there's a "Tasks" section, prioritize items from there
- Consolidate related items into single tasks when sensible

Output format - return ONLY this XML, nothing else:

<tasks>
<task>Create go.mod with module name and dependencies</task>
<task>Implement HTTP server with health endpoint</task>
</tasks>"""

        try:
            result = await self.claude.execute(prompt, timeout=60)
            return self._parse_xml(result)
        except RuntimeError as e:
            logging.warning(f"claude parsing failed: {e}")
            return []

    def _parse_xml(self, text: str) -> list[Task]:
        """extract tasks from XML response"""
        tasks = []

        # find all <task>...</task> elements
        pattern = r"<task>(.*?)</task>"
        matches = re.findall(pattern, text, re.DOTALL)

        for desc in matches:
            desc = desc.strip()
            if desc and len(desc) > 5:
                task = Task(
                    id=str(uuid.uuid4()),
                    description=desc,
                    files=[],
                    status=TaskStatus.PENDING,
                )
                tasks.append(task)

        return tasks
