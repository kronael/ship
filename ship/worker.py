from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from ship.claude_code import ClaudeCodeClient, ClaudeError
from ship.config import Config
from ship.display import display, log_entry
from ship.prompts import WORKER
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
        override_prompt: str = "",
        judge: Judge | None = None,
        spec_files: str = "",
    ):
        self.worker_id = worker_id
        self.cfg = cfg
        self.state = state
        self.project_context = project_context
        self.override_prompt = override_prompt
        self.judge = judge
        self.spec_files = spec_files
        self.claude = ClaudeCodeClient(
            model="sonnet",
            max_turns=cfg.max_turns,
            role=f"worker-{worker_id}",
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
        display.event(f"  [{self.worker_id}] {short_desc}", min_level=2)

        if self.judge:
            self.judge.set_worker_task(self.worker_id, task.description)

        await self.state.update_task(task.id, TaskStatus.RUNNING)

        progress_log: list[str] = []

        try:
            override_section = (
                f"Override instructions: {self.override_prompt}\n\n"
                if self.override_prompt
                else ""
            )
            context = (
                f"Project: {self.project_context}\n\n" if self.project_context else ""
            )
            project_path = str(Path(self.cfg.data_dir) / "PROJECT.md")
            prompt = override_section + WORKER.format(
                context=context,
                timeout_min=self.cfg.task_timeout // 60,
                description=task.description,
                plan_path=str(Path(self.cfg.data_dir) / "PLAN.md"),
                project_path=project_path,
                spec_files=self.spec_files or "SPEC.md",
                log_path=str(Path(self.cfg.data_dir) / "LOG.md"),
            )
            if self.cfg.verbosity >= 3:
                display.event(f"\n{'=' * 60}", min_level=3)
                display.event("PROMPT TO CLAUDE:", min_level=3)
                display.event(f"{'=' * 60}", min_level=3)
                display.event(prompt, min_level=3)
                display.event(f"{'=' * 60}\n", min_level=3)

            head_before = await self._git_head()

            def on_progress(msg: str) -> None:
                display.event(
                    f"  [{self.worker_id}] {msg}",
                    min_level=1,
                )
                progress_log.append(msg)

            result, session_id = await self.claude.execute(
                prompt,
                timeout=self.cfg.task_timeout,
                on_progress=on_progress,
            )

            status, followups, summary = self._parse_output(result)

            # if XML tags are missing, resume session and ask for them
            if session_id and (not summary or "<status>" not in result):
                display.event(
                    f"  [{self.worker_id}] reformatting output...", min_level=1
                )
                reformatted = await self.claude.reformat(session_id)
                if reformatted:
                    status, followups, summary = self._parse_output(reformatted)

            if status == "partial":
                await self.state.update_task(
                    task.id,
                    TaskStatus.FAILED,
                    error="worker reported partial",
                    result=result,
                    followups=followups,
                )
                log_entry(f"partial: {task.description[:60]}")
                display.event(f"  [{self.worker_id}] partial", min_level=2)
                logging.warning(f"{self.worker_id} partial: {task.description}")
                return

            await self.state.update_task(
                task.id,
                TaskStatus.COMPLETED,
                result=result,
                summary=summary,
                session_id=session_id,
            )
            if self.judge:
                updated = Task(
                    id=task.id,
                    description=task.description,
                    files=task.files,
                    status=TaskStatus.COMPLETED,
                    result=result,
                )
                self.judge.notify_completed(updated)
            git_summary = await self._git_diff_stat(head_before)
            suffix = f" ({git_summary})" if git_summary else ""
            label = summary if summary else task.description[:60]
            log_entry(f"done: {label}{suffix}")
            done_msg = (
                f"  [{self.worker_id}] done: {summary}{suffix}"
                if summary
                else f"  [{self.worker_id}] done{suffix}"
            )
            display.event(done_msg, min_level=2)
            logging.info(f"{self.worker_id} completed: {task.description}")

        except ClaudeError as e:
            error_msg = str(e) if str(e) else type(e).__name__
            # attempt to resume and get a progress summary
            summary = ""
            if e.session_id:
                display.event(
                    f"  [{self.worker_id}] resuming for summary...",
                    min_level=1,
                )
                summary = await self.claude.summarize(e.session_id, e.partial)
            elif e.partial:
                summary = e.partial
            elif progress_log:
                summary = "progress before failure:\n" + "\n".join(
                    f"- {p}" for p in progress_log[-10:]
                )
            result_text = summary or error_msg
            status, followups, _ = self._parse_output(result_text)
            await self.state.update_task(
                task.id,
                TaskStatus.FAILED,
                error=error_msg,
                result=result_text,
                followups=followups,
            )
            if "timeout" in error_msg.lower():
                display.event(
                    f"  [{self.worker_id}] timeout after {self.cfg.task_timeout}s"
                )
                logging.warning(f"{self.worker_id} {error_msg}: {task.description}")
            else:
                display.event(f"  [{self.worker_id}] error: {error_msg}")
                logging.error(
                    f"{self.worker_id} failed: {task.description}: {error_msg}"
                )

        except Exception as e:
            error_msg = str(e) if str(e) else type(e).__name__
            await self.state.update_task(task.id, TaskStatus.FAILED, error=error_msg)
            display.event(f"  [{self.worker_id}] error: {error_msg}")
            logging.error(f"{self.worker_id} failed: {task.description}: {error_msg}")

        finally:
            if self.judge:
                self.judge.clear_worker_task(self.worker_id)

    def _parse_output(self, text: str) -> tuple[str, list[str], str]:
        m = re.search(r"<status>(done|partial)</status>", text)
        status = m.group(1) if m else "done"

        followups: list[str] = []
        block = re.search(r"<followups>(.*?)</followups>", text, re.DOTALL)
        if block:
            followups = [
                d.strip()
                for d in re.findall(r"<task>(.*?)</task>", block.group(1), re.DOTALL)
                if d.strip()
            ]

        sm = re.search(r"<summary>(.*?)</summary>", text, re.DOTALL)
        summary = sm.group(1).strip() if sm else ""

        return status, followups, summary

    async def _git_head(self) -> str:
        """snapshot current HEAD"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "rev-parse",
                "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await proc.communicate()
            return out.decode().strip()
        except Exception:
            return ""

    async def _git_diff_stat(self, old_head: str) -> str:
        """compact diff stat: '5 files, +120/-30'"""
        if not old_head:
            return ""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "diff",
                "--shortstat",
                old_head,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await proc.communicate()
            text = out.decode().strip()
            if not text:
                return ""
            files = re.search(r"(\d+) file", text)
            ins = re.search(r"(\d+) insertion", text)
            dels = re.search(r"(\d+) deletion", text)
            f = files.group(1) if files else "0"
            i = ins.group(1) if ins else "0"
            d = dels.group(1) if dels else "0"
            return f"{f} files, +{i}/-{d}"
        except Exception:
            return ""
