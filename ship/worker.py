from __future__ import annotations

import asyncio
import logging
import re

from typing import TYPE_CHECKING

from ship.claude_code import ClaudeCodeClient, ClaudeError
from ship.config import Config
from ship.display import display, log_entry
from ship.prompts import WORKER
from ship.skills import format_skills_for_prompt, load_skills
from ship.state import StateManager
from ship.types_ import Task, TaskStatus

if TYPE_CHECKING:
    from ship.judge import Judge


class Worker:
    """executes tasks from queue using claude code CLI"""
    def __init__(
        self,
        worker_id: str,
        cfg: Config,
        state: StateManager,
        project_context: str = "",
        judge: Judge | None = None,
        session_id: str | None = None,
    ):
        self.worker_id = worker_id
        self.cfg = cfg
        self.state = state
        self.project_context = project_context
        self.judge = judge
        self.skills = load_skills()
        self.claude = ClaudeCodeClient(
            model="sonnet",
            max_turns=cfg.max_turns,
            role=f"worker-{worker_id}",
            session_id=session_id,
        )

    async def run(self, queue: asyncio.Queue[Task]) -> None:
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
        short_desc = task.description[:60]
        display.event(f"  [{self.worker_id}] {short_desc}")

        if self.judge:
            self.judge.set_worker_task(
                self.worker_id, task.description
            )

        await self.state.update_task(task.id, TaskStatus.RUNNING)

        try:
            result, sid = await self._do_work(task)

            if "reached max turns" in result.lower():
                await self.state.update_task(
                    task.id, TaskStatus.FAILED,
                    error="reached max turns",
                    session_id=sid,
                )
                log_entry(
                    f"fail (max turns):"
                    f" {task.description[:60]}"
                )
                display.event(
                    f"  [{self.worker_id}]"
                    f" max turns - incomplete"
                )
                return

            # parse structured output
            status, followups = self._parse_output(result)

            if status == "partial":
                await self.state.update_task(
                    task.id, TaskStatus.FAILED,
                    error="worker reported partial",
                    result=result,
                    session_id=sid,
                    followups=followups,
                )
                log_entry(
                    f"partial: {task.description[:60]}"
                )
                display.event(
                    f"  [{self.worker_id}] partial"
                )
                return

            await self.state.update_task(
                task.id, TaskStatus.COMPLETED,
                result=result,
                session_id=sid,
            )
            if self.judge:
                updated = Task(
                    id=task.id,
                    description=task.description,
                    files=task.files,
                    status=TaskStatus.COMPLETED,
                    result=result,
                    session_id=sid,
                )
                self.judge.notify_completed(updated)
            log_entry(f"done: {task.description[:60]}")
            display.event(f"  [{self.worker_id}] done")
            logging.info(
                f"{self.worker_id} completed:"
                f" {task.description}"
            )

        except ClaudeError as e:
            error_msg = str(e) if str(e) else type(e).__name__
            await self.state.update_task(
                task.id, TaskStatus.FAILED,
                error=error_msg,
                session_id=e.session_id,
            )
            if "timeout" in error_msg.lower():
                display.event(
                    f"  [{self.worker_id}] timeout "
                    f"after {self.cfg.task_timeout}s"
                )
                logging.warning(
                    f"{self.worker_id} {error_msg}: "
                    f"{task.description}"
                )
            else:
                display.event(
                    f"  [{self.worker_id}]"
                    f" error: {error_msg}"
                )
                logging.error(
                    f"{self.worker_id} failed: "
                    f"{task.description}: {error_msg}"
                )

        except Exception as e:
            error_msg = str(e) if str(e) else type(e).__name__
            await self.state.update_task(
                task.id, TaskStatus.FAILED, error=error_msg
            )
            display.event(
                f"  [{self.worker_id}] error: {error_msg}"
            )
            logging.error(
                f"{self.worker_id} failed: "
                f"{task.description}: {error_msg}"
            )

        finally:
            if self.judge:
                self.judge.clear_worker_task(self.worker_id)

    async def _do_work(
        self, task: Task
    ) -> tuple[str, str]:
        """execute task via claude code CLI

        returns: (output, session_id) tuple
        """
        context = ""
        if self.project_context:
            context = f"Project: {self.project_context}\n\n"

        skills = ""
        if self.skills:
            skills_text = format_skills_for_prompt(self.skills)
            if skills_text:
                skills = (
                    f"{skills_text}\n\n"
                    f"Use the relevant skills above"
                    f" for this task.\n\n"
                )

        # resume from previous session if available
        if task.session_id and not self.claude.session_id:
            self.claude.session_id = task.session_id
            self.claude._session_started = True

        prompt = WORKER.format(
            context=context,
            skills=skills,
            timeout_min=self.cfg.task_timeout // 60,
            description=task.description,
        )

        if self.cfg.verbose:
            display.event(f"\n{'='*60}")
            display.event("PROMPT TO CLAUDE:")
            display.event(f"{'='*60}")
            display.event(prompt)
            display.event(f"{'='*60}\n")

        output, sid = await self.claude.execute(
            prompt, timeout=self.cfg.task_timeout
        )

        if self.cfg.verbose:
            display.event(f"  output: {len(output)} chars")

        return output, sid

    def _parse_output(
        self, text: str
    ) -> tuple[str, list[str]]:
        """parse structured worker output

        returns: (status, followup_descriptions)
        """
        status = "done"
        m = re.search(
            r"<status>(done|partial)</status>", text
        )
        if m:
            status = m.group(1)

        followups: list[str] = []
        block = re.search(
            r"<followups>(.*?)</followups>",
            text,
            re.DOTALL,
        )
        if block:
            for desc in re.findall(
                r"<task>(.*?)</task>",
                block.group(1),
                re.DOTALL,
            ):
                desc = desc.strip()
                if desc:
                    followups.append(desc)

        return status, followups
