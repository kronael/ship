from __future__ import annotations

import asyncio
import logging
import random
import re
import uuid

from ship.claude_code import ClaudeCodeClient
from ship.display import display, log_entry, write_progress_md
from ship.prompts import JUDGE_TASK
from ship.prompts import VERIFIER
from ship.refiner import Refiner
from ship.replanner import Replanner
from ship.state import StateManager
from ship.types_ import Task, TaskStatus


MAX_RETRIES = 10
CASCADE_PREFIX = "cascade:"


def is_cascade_error(error: str) -> bool:
    return error.startswith(CASCADE_PREFIX)


class Judge:
    """narrow: judge tasks; medium: codex refine; wide: replan"""

    def __init__(
        self,
        state: StateManager,
        queue: asyncio.Queue[Task],
        project_context: str = "",
        max_refine_rounds: int = 10,
        max_replan_rounds: int = 1,
        verbosity: int = 1,
        use_codex: bool = False,
    ):
        self.state = state
        self.queue = queue
        self.project_context = project_context
        self.verbosity = verbosity
        self.max_refine_rounds = max_refine_rounds
        self.max_replan_rounds = max_replan_rounds
        self.use_codex = use_codex
        self.refine_count = 0
        self.replan_count = 0
        self.worker_tasks: dict[str, str] = {}
        self.claude = ClaudeCodeClient(
            model="sonnet",
            role="judge",
        )
        self.refiner = Refiner(
            state,
            project_context,
            verbosity=verbosity,
        )
        self.replanner = Replanner(
            state,
            project_context,
            verbosity=verbosity,
        )
        self._completed_queue: list[Task] = []
        self.adv_round = 0
        self.max_adv_rounds = 3
        self._adv_task_ids: set[str] = set()
        self._adv_attempts = 0
        self.max_adv_attempts = 3
        self._seen_challenges: set[str] = set()

    def set_worker_task(self, worker_id: str, desc: str) -> None:
        self.worker_tasks[worker_id] = desc

    def clear_worker_task(self, worker_id: str) -> None:
        self.worker_tasks.pop(worker_id, None)

    def notify_completed(self, task: Task) -> None:
        self._completed_queue.append(task)

    async def _judge_task(self, task: Task) -> None:
        prompt = JUDGE_TASK.format(
            description=task.description,
            result=(task.result or "")[:500],
        )

        display.event(f"  judging: {task.description[:50]}", min_level=2)

        try:
            await self.claude.execute(prompt, timeout=45)
        except RuntimeError as e:
            logging.warning(f"judge task failed: {e}")
            log_entry(f"judge skip: {task.description[:40]}")

    def _update_tui(self, tasks: list[Task]) -> None:
        def _entry(t: Task) -> tuple[str, TaskStatus, str]:
            worker = ""
            if t.status is TaskStatus.RUNNING:
                for wid, desc in self.worker_tasks.items():
                    if desc == t.description:
                        worker = wid
                        break
            return (t.description, t.status, worker)

        all_panel = [_entry(t) for t in tasks]

        # sliding window: running tasks + same count of next pending
        running = [e for e in all_panel if e[1] is TaskStatus.RUNNING]
        pending = [e for e in all_panel if e[1] is TaskStatus.PENDING]
        n = max(len(running), 1)
        display.set_tasks(running + pending[:n])
        completed_count = sum(
            1 for t in tasks if t.status is TaskStatus.COMPLETED
        )
        display.set_global(completed_count, len(tasks))

        if self.refine_count > 0:
            phase = f"refining ({self.refine_count}/{self.max_refine_rounds})"
        elif self.replan_count > 0:
            phase = f"replanning ({self.replan_count}/{self.max_replan_rounds})"
        else:
            phase = "executing"
        display.set_phase(phase)

        if not display._plan_shown:
            display.show_plan(all_panel)
        display.refresh()

        total = len(tasks)
        completed = sum(1 for t in tasks if t.status is TaskStatus.COMPLETED)
        running = sum(1 for t in tasks if t.status is TaskStatus.RUNNING)
        pending = sum(1 for t in tasks if t.status is TaskStatus.PENDING)
        failed = sum(1 for t in tasks if t.status is TaskStatus.FAILED)
        write_progress_md(
            total, completed, running, pending, failed,
            [f"{k}: {v}" for k, v in sorted(self.worker_tasks.items())],
        )

    def _parse_challenges(self, text: str) -> list[str]:
        return [
            c.strip()
            for c in re.findall(
                r"<challenge>(.*?)</challenge>",
                text,
                re.DOTALL,
            )
            if c.strip()
        ]

    async def _run_adversarial_round(self) -> bool:
        """returns True if max attempts exhausted"""
        self._adv_attempts += 1
        if self._adv_attempts > self.max_adv_attempts:
            display.event("  adversarial: max attempts exhausted")
            logging.warning("adversarial max attempts reached")
            return True

        work = self.state.get_work_state()
        if not work:
            return True

        verifier = ClaudeCodeClient(
            model="sonnet",
            role="verifier",
        )
        prompt = VERIFIER.format(
            goal_text=work.goal_text[:2000],
            project_context=self.project_context,
        )

        display.event(
            f"  adversarial round {self.adv_round + 1}"
            f"/{self.max_adv_rounds}..."
        )

        try:
            result, _ = await verifier.execute(prompt, timeout=90)
        except RuntimeError as e:
            logging.warning(f"verifier failed: {e}")
            display.event(f"  verifier failed: {e}")
            return False

        challenges = self._parse_challenges(result)
        if not challenges:
            logging.warning("verifier returned no challenges")
            display.event("  verifier: no challenges found")
            return False

        novel = [c for c in challenges if c not in self._seen_challenges]
        if not novel:
            logging.warning("all challenges already seen")
            display.event("  verifier: no novel challenges")
            return False

        picked = random.sample(novel, min(2, len(novel)))
        for c in picked:
            self._seen_challenges.add(c)

        self._adv_task_ids.clear()
        for desc in picked:
            task = Task(
                id=str(uuid.uuid4()),
                description=desc,
                files=[],
                status=TaskStatus.PENDING,
            )
            await self.state.add_task(task)
            await self.queue.put(task)
            self._adv_task_ids.add(task.id)
            log_entry(f"adv challenge: {desc[:50]}")

        display.event(f"  queued {len(picked)} adversarial challenges")
        return False

    async def _check_adv_batch(self) -> str:
        """returns "pending", "pass", or "fail" """
        all_tasks = await self.state.get_all_tasks()
        adv_tasks = [t for t in all_tasks if t.id in self._adv_task_ids]

        if len(adv_tasks) != len(self._adv_task_ids):
            return "pending"

        for t in adv_tasks:
            if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                return "pending"

        for t in adv_tasks:
            if t.status is TaskStatus.FAILED:
                return "fail"

        return "pass"

    async def run(self) -> None:
        logging.info("judge starting")
        display.event("  judge: monitoring...", min_level=2)

        try:
            while True:
                await asyncio.sleep(5)

                while self._completed_queue:
                    task = self._completed_queue.pop(0)
                    await self._judge_task(task)

                all_tasks = await self.state.get_all_tasks()
                self._update_tui(all_tasks)

                retryable = [
                    t
                    for t in all_tasks
                    if t.status is TaskStatus.FAILED
                    and t.id not in self._adv_task_ids
                    and not is_cascade_error(t.error)
                ]
                for task in retryable:
                    if task.retries >= MAX_RETRIES:
                        # exhausted retries -- cascade
                        cascaded = await self.state.cascade_failure(task.id)
                        if cascaded:
                            log_entry(
                                f"cascade: {task.id[:8]}"
                                f" -> {len(cascaded)} tasks"
                            )
                            display.event(
                                f"  cascade {task.id[:8]}"
                                f" -> {len(cascaded)} deps"
                            )
                        continue
                    await self.state.retry_task(task.id)
                    await self.queue.put(task)
                    log_entry(f"retry: {task.description[:50]}")
                    display.event(
                        f"  retry {task.id[:8]}"
                        f" ({task.retries + 1}/{MAX_RETRIES})"
                    )

                if self._adv_task_ids:
                    outcome = await self._check_adv_batch()
                    if outcome == "pending":
                        continue
                    if outcome == "fail":
                        display.event(
                            "  adversarial challenge failed"
                            " — re-entering refine cycle"
                        )
                        log_entry("adv fail: resetting")
                        self._adv_task_ids.clear()
                        self._seen_challenges.clear()
                        self.adv_round = 0
                        self.refine_count = 0
                        self.replan_count = 0
                        continue
                    # pass
                    self.adv_round += 1
                    self._adv_task_ids.clear()
                    display.event(
                        f"  adversarial round"
                        f" {self.adv_round}"
                        f"/{self.max_adv_rounds} passed"
                    )
                    if self.adv_round >= self.max_adv_rounds:
                        display.clear_status()
                        display.event(
                            "  all tasks complete"
                            " (adversarial verified)"
                        )
                        logging.info("goal satisfied")
                        await self.state.mark_complete()
                        return
                    continue

                if not await self.state.is_complete():
                    continue

                if self.use_codex and self.refine_count < self.max_refine_rounds:
                    self.refine_count += 1
                    display.event(
                        f"  refining ({self.refine_count}/{self.max_refine_rounds})...",
                        min_level=2,
                    )
                    display.set_phase(
                        f"refining ({self.refine_count}/{self.max_refine_rounds})"
                    )
                    display.refresh()
                    new_tasks = await self.refiner.refine()
                    if new_tasks:
                        log_entry(f"+{len(new_tasks)} from refiner")
                        display.event(f"  +{len(new_tasks)} follow-up tasks")
                        display._plan_shown = False
                        for task in new_tasks:
                            await self.queue.put(task)
                        continue

                if self.replan_count < self.max_replan_rounds:
                    self.replan_count += 1
                    display.event(
                        f"  replanning ({self.replan_count}/{self.max_replan_rounds})...",
                        min_level=2,
                    )
                    display.set_phase(
                        f"replanning ({self.replan_count}/{self.max_replan_rounds})"
                    )
                    display.refresh()
                    new_tasks = await self.replanner.replan()
                    if new_tasks:
                        log_entry(f"+{len(new_tasks)} from replanner")
                        display.event(f"  +{len(new_tasks)} replanned tasks")
                        display._plan_shown = False
                        for task in new_tasks:
                            await self.queue.put(task)
                        continue

                gave_up = await self._run_adversarial_round()
                if gave_up:
                    display.clear_status()
                    display.event(
                        "  all tasks complete"
                        " (adversarial exhausted)"
                    )
                    logging.info("goal satisfied (adv exhausted)")
                    await self.state.mark_complete()
                    return
                continue

        except asyncio.CancelledError:
            logging.info("judge stopping")
            raise
