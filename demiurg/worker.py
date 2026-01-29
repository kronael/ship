from __future__ import annotations

import asyncio
import logging

from demiurg.claude_code import ClaudeCodeClient
from demiurg.config import Config
from demiurg.skills import format_skills_for_prompt, load_skills
from demiurg.state import StateManager
from demiurg.types_ import Task, TaskStatus


class Worker:
    """executes tasks from queue using claude code CLI"""
    def __init__(self, worker_id: str, cfg: Config, state: StateManager, project_context: str = ""):
        self.worker_id = worker_id
        self.cfg = cfg
        self.state = state
        self.project_context = project_context
        self.skills = load_skills()
        self.claude = ClaudeCodeClient(
            model="sonnet",
            max_turns=cfg.max_turns,
        )

    async def run(self, queue: asyncio.Queue[Task]) -> None:
        """process tasks from queue until cancelled"""
        logging.info(f"{self.worker_id} starting")

        try:
            while True:
                task = await queue.get()
                try:
                    await self._execute(task)
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            logging.info(f"{self.worker_id} stopping")
            raise

    async def _execute(self, task: Task) -> None:
        print(f"\n[{self.worker_id}] {task.description}")

        await self.state.update_task(task.id, TaskStatus.RUNNING)

        try:
            result = await self._do_work(task)

            await self.state.update_task(
                task.id, TaskStatus.COMPLETED, result=result
            )
            print(f"[{self.worker_id}] ✓ completed")
            logging.info(f"{self.worker_id} completed: {task.description}")

        except RuntimeError as e:
            # claude CLI errors (including timeout) come as RuntimeError
            error_msg = str(e) if str(e) else type(e).__name__
            await self.state.update_task(
                task.id, TaskStatus.FAILED, error=error_msg
            )
            if "timeout" in error_msg.lower():
                print(f"[{self.worker_id}] ✗ timeout")
                logging.warning(f"{self.worker_id} {error_msg}: {task.description}")
            else:
                print(f"[{self.worker_id}] ✗ {error_msg}")
                logging.error(f"{self.worker_id} failed: {task.description}: {error_msg}")

        except Exception as e:
            error_msg = str(e) if str(e) else type(e).__name__
            await self.state.update_task(
                task.id, TaskStatus.FAILED, error=error_msg
            )
            print(f"[{self.worker_id}] ✗ {error_msg}")
            logging.error(
                f"{self.worker_id} failed: {task.description}: {error_msg}"
            )

    async def _do_work(self, task: Task) -> str:
        """execute task by calling claude code CLI with streaming output"""
        # build prompt with context, skills, and task
        parts = []

        if self.project_context:
            parts.append(f"Project: {self.project_context}")

        if self.skills:
            skills_text = format_skills_for_prompt(self.skills)
            if skills_text:
                parts.append(skills_text)
                parts.append("Use the relevant skills above for this task.")

        parts.append(f"Task: {task.description}")

        prompt = "\n\n".join(parts)

        output_lines = []
        async for line in self.claude.execute_stream(prompt, timeout=self.cfg.task_timeout):
            if line.strip():
                print(f"  {line}")
            output_lines.append(line)
        return "\n".join(output_lines)
