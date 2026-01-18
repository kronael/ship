from __future__ import annotations

import asyncio
import logging

from demiurg.claude_code import ClaudeCodeClient
from demiurg.config import Config
from demiurg.state import StateManager
from demiurg.types import Task, TaskStatus


class Worker:
    def __init__(self, worker_id: str, cfg: Config, state: StateManager):
        self.worker_id = worker_id
        self.cfg = cfg
        self.state = state
        self.claude = ClaudeCodeClient(model="sonnet", cwd=cfg.target_dir)

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
        logging.info(f"{self.worker_id} executing: {task.description}")

        await self.state.update_task(task.id, TaskStatus.RUNNING)

        try:
            async with asyncio.timeout(30):
                result = await self._do_work(task)

            await self.state.update_task(
                task.id, TaskStatus.COMPLETED, result=result
            )
            logging.info(f"{self.worker_id} completed: {task.description}")

        except TimeoutError:
            error_msg = "task timeout after 30s"
            await self.state.update_task(
                task.id, TaskStatus.FAILED, error=error_msg
            )
            logging.warning(f"{self.worker_id} {error_msg}: {task.description}")

        except Exception as e:
            error_msg = str(e) if str(e) else type(e).__name__
            await self.state.update_task(
                task.id, TaskStatus.FAILED, error=error_msg
            )
            logging.error(
                f"{self.worker_id} failed: {task.description}: {error_msg}"
            )

    async def _do_work(self, task: Task) -> str:
        """execute task by calling claude code CLI"""
        return await self.claude.execute(task.description, timeout=30)
