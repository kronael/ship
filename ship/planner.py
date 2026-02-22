from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from ship.claude_code import ClaudeCodeClient
from ship.config import Config
from ship.prompts import PLANNER
from ship.state import StateManager
from ship.types_ import Task, TaskStatus


class Planner:
    """breaks down design files into executable tasks"""

    def __init__(
        self,
        cfg: Config,
        state: StateManager,
    ):
        self.cfg = cfg
        self.state = state
        self.claude = ClaudeCodeClient(
            model="sonnet",
            role="planner",
        )

    async def plan_once(self) -> list[Task]:
        work = self.state.get_work_state()
        if not work:
            return []

        logging.info("breaking down goal into tasks")

        context, tasks, mode = await self._parse_design(
            work.goal_text, override_prompt=work.override_prompt
        )

        if context:
            await self.state.set_project_context(context)
            logging.info(f"project context: {context[:100]}...")

        await self.state.set_execution_mode(mode)
        logging.info(f"execution mode: {mode}")

        for task in tasks:
            await self.state.add_task(task)
            logging.info(f"created task: {task.description}")

        return tasks

    async def _parse_design(
        self, goal: str, override_prompt: str = ""
    ) -> tuple[str, list[Task], str]:
        plan_path = str(Path(self.cfg.data_dir) / "PLAN.md")
        override_section = (
            f"Override instructions: {override_prompt}\n\n" if override_prompt else ""
        )
        prompt = override_section + PLANNER.format(goal=goal, plan_path=plan_path)
        if self.cfg.verbosity >= 3:
            print(f"\n{'=' * 60}\nPLANNER PROMPT:\n{'=' * 60}\n{prompt}\n{'=' * 60}\n")
        try:
            result, _ = await self.claude.execute(prompt, timeout=180)
            if self.cfg.verbosity >= 3:
                print(
                    f"\n{'=' * 60}\nPLANNER RESPONSE:\n{'=' * 60}\n{result}\n{'=' * 60}\n"
                )
            return self._parse_xml(result)
        except RuntimeError as e:
            logging.warning(f"claude parsing failed: {e}")
            return "", [], "parallel"

    def _parse_xml(self, text: str) -> tuple[str, list[Task], str]:
        context_match = re.search(r"<context>(.*?)</context>", text, re.DOTALL)
        context = context_match.group(1).strip() if context_match else ""

        mode_match = re.search(r"<mode>(.*?)</mode>", text, re.DOTALL)
        mode = mode_match.group(1).strip().lower() if mode_match else "parallel"
        if mode not in ("parallel", "sequential"):
            mode = "parallel"

        tasks: list[Task] = []
        dep_map: list[list[int]] = []

        for m in re.finditer(r"<task(?=[\s>])([^>]*?)>(.*?)</task>", text, re.DOTALL):
            attrs = m.group(1)
            desc = m.group(2).strip()
            if not desc or len(desc) <= 5:
                continue

            worker_m = re.search(r'worker="([^"]*)"', attrs)
            worker = worker_m.group(1) if worker_m else "auto"

            depends_m = re.search(r'depends="([^"]*)"', attrs)
            depends_str = depends_m.group(1) if depends_m else ""

            indices = [
                int(p.strip()) for p in depends_str.split(",") if p.strip().isdigit()
            ]

            tasks.append(
                Task(
                    id=str(uuid.uuid4()),
                    description=desc,
                    files=[],
                    status=TaskStatus.PENDING,
                    worker=worker,
                )
            )
            dep_map.append(indices)

        # resolve 1-indexed task indices to UUIDs
        for i, indices in enumerate(dep_map):
            for idx in indices:
                if 1 <= idx <= len(tasks) and idx - 1 != i:
                    tasks[i].depends_on.append(tasks[idx - 1].id)

        return context, tasks, mode
