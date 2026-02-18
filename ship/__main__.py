from __future__ import annotations

import asyncio
import logging
import signal
import sys
import uuid
from pathlib import Path

import click

from ship.config import Config
from ship.display import display
from ship.judge import Judge
from ship.planner import Planner
from ship.state import StateManager
from ship.types_ import Task, TaskStatus
from ship.validator import Validator
from ship.worker import Worker

SPEC_CANDIDATES = ["SPEC.md", "spec.md"]


VERSION = "0.5.0"


def discover_spec(context: tuple[str, ...]) -> list[Path]:
    if context:
        if len(context) == 1:
            p = Path(context[0])
            if p.is_file():
                return [p]
            if p.is_dir():
                return sorted(p.glob("*.md"))
        return []

    found: list[Path] = []
    for candidate in SPEC_CANDIDATES:
        p = Path(candidate)
        if p.exists():
            found.append(p)
    specs_dir = Path("specs")
    if specs_dir.is_dir():
        found.extend(sorted(specs_dir.glob("*.md")))
    return found


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("context", nargs=-1)
@click.option("-c", "--continue", "cont", is_flag=True, help="continue from last run")
@click.option("-w", "--workers", type=int, help="number of parallel workers")
@click.option("-t", "--timeout", type=int, help="task timeout in seconds")
@click.option("-m", "--max-turns", type=int, help="max agentic turns per task")
@click.option("-v", "--verbose", count=True, help="increase verbosity (-v, -vv)")
@click.option("-q", "--quiet", is_flag=True, help="errors only")
@click.option("-x", "--codex", is_flag=True, help="enable codex refiner (off by default)")
def run(
    context: tuple[str, ...],
    cont: bool,
    workers: int | None,
    timeout: int | None,
    max_turns: int | None,
    verbose: int,
    quiet: bool,
    codex: bool,
) -> None:
    """autonomous coding agent

    Discovers SPEC.md by default, or pass files/dirs as args.
    """

    def _sigterm(signum, frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, _sigterm)

    verbosity = 0 if quiet else min(1 + verbose, 3)

    try:
        asyncio.run(_main(context, cont, workers, timeout, max_turns, verbosity, codex))
    except KeyboardInterrupt:
        display.finish()
        display.error("\ninterrupted")
        sys.exit(130)


async def _main(
    context: tuple[str, ...],
    cont: bool,
    workers: int | None,
    timeout: int | None,
    max_turns: int | None,
    verbosity: int,
    use_codex: bool = False,
) -> None:
    try:
        cfg = Config.load(
            workers=workers,
            timeout=timeout,
            max_turns=max_turns,
            verbosity=verbosity,
            use_codex=use_codex,
        )
    except RuntimeError as e:
        display.error(f"error: {e}")
        sys.exit(1)

    display.verbosity = cfg.verbosity

    Path(cfg.log_dir).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=f"{cfg.log_dir}/ship.log",
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%b %d %H:%M:%S",
    )

    logging.info("starting ship")

    try:
        state = StateManager(cfg.data_dir)
    except RuntimeError as e:
        display.error(f"error: {e}")
        sys.exit(1)

    if cont:
        work = state.get_work_state()
        if not work:
            display.error("error: no previous run found")
            sys.exit(1)
        if work.is_complete:
            display.event("goal already satisfied")
            sys.exit(0)
        logging.info(f"continuing: {work.design_file}")
        await state.reset_interrupted_tasks()
    else:
        # resolve spec
        spec_files = discover_spec(context)
        spec_label = ""
        inline_context: list[str] = []

        if spec_files:
            try:
                goal_text = "\n\n".join(f.read_text() for f in spec_files).strip()
            except OSError as e:
                display.error(f"error: cannot read specs: {e}")
                sys.exit(1)
            if not goal_text:
                display.error("error: spec files are empty")
                sys.exit(1)
            spec_label = ", ".join(str(f) for f in spec_files)
            if context and len(context) > 1:
                inline_context = list(context[1:])
        elif context:
            goal_text = " ".join(context)
            inline_context = list(context)
        else:
            display.error(
                "error: no spec found (try SPEC.md, specs/*.md, or /planship)",
            )
            sys.exit(1)

        display.event("\033[36m⟳\033[0m validating spec...")
        validator = Validator(
            verbosity=cfg.verbosity,
            session_id=str(uuid.uuid4()),
        )
        validation = await validator.validate(goal_text, context=inline_context)
        display.event("\033[32m✓\033[0m spec ok")
        if not validation.accept:
            rejection_path = Path("REJECTION.md")
            gaps_text = (
                "\n".join(f"- {g}" for g in validation.gaps)
                or "- (no details provided)"
            )
            rejection = (
                "# REJECTION\n\n"
                "The design is not specific enough to execute."
                " Please address these gaps:\n\n"
                f"{gaps_text}\n"
            )
            try:
                rejection_path.write_text(rejection)
            except OSError as e:
                display.error(
                    f"error: cannot write {rejection_path}: {e}",
                )
                sys.exit(1)
            display.error("error: design rejected (see REJECTION.md)")
            sys.exit(1)

        project_text = validation.project_md.strip()
        if project_text:
            try:
                Path("PROJECT.md").write_text(project_text + "\n")
            except OSError as e:
                display.error(f"error: cannot write PROJECT.md: {e}")
                sys.exit(1)

        design_file = spec_label if spec_files else "<inline>"
        logging.info(f"new run: {design_file}")
        combined_goal = goal_text
        if project_text:
            combined_goal = f"{goal_text}\n\n---\n\n# PROJECT\n\n{project_text}\n"
        await state.init_work(design_file, combined_goal)

        display.event("\033[36m⟳\033[0m planning tasks...")
        planner = Planner(
            cfg,
            state,
            session_id=str(uuid.uuid4()),
        )
        tasks = await planner.plan_once()

        if not tasks:
            display.error("error: no tasks generated from design")
            sys.exit(1)

        logging.info(f"generated {len(tasks)} tasks")
        display.event(f"\033[32m✓\033[0m generated {len(tasks)} tasks")

    queue: asyncio.Queue[Task] = asyncio.Queue()

    pending = await state.get_pending_tasks()
    for task in pending:
        await queue.put(task)

    all_tasks = await state.get_all_tasks()
    total = len(all_tasks)
    completed = len([t for t in all_tasks if t.status is TaskStatus.COMPLETED])

    num_workers = min(cfg.num_workers, len(pending))
    if num_workers < cfg.num_workers:
        logging.info(
            f"reducing workers from {cfg.num_workers} "
            f"to {num_workers} (only {len(pending)} tasks)"
        )

    work = state.get_work_state()
    project_context = work.project_context if work else ""
    exec_mode = work.execution_mode if work else "parallel"

    if exec_mode == "sequential" and workers is None:
        num_workers = 1
        logging.info("sequential mode: using 1 worker")

    display.banner(
        f"ship v{VERSION} | {num_workers} workers"
        f" | {exec_mode} | timeout {cfg.task_timeout}s"
    )
    if completed > 0:
        display.event(f"progress: {completed}/{total} tasks completed")
    display.event(f"\033[36m⟳\033[0m starting {num_workers} workers...")

    judge = Judge(
        state,
        queue,
        project_context=project_context,
        verbosity=cfg.verbosity,
        session_id=str(uuid.uuid4()),
        use_codex=cfg.use_codex,
    )
    worker_list = [
        Worker(
            f"w{i}",
            cfg,
            state,
            project_context=project_context,
            judge=judge,
            session_id=str(uuid.uuid4()),
        )
        for i in range(num_workers)
    ]

    worker_tasks = [asyncio.create_task(w.run(queue)) for w in worker_list]
    judge_task = asyncio.create_task(judge.run())

    all_async = [judge_task, *worker_tasks]

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, lambda: [t.cancel() for t in all_async])
    loop.add_signal_handler(signal.SIGTERM, lambda: [t.cancel() for t in all_async])

    try:
        await judge_task
    except asyncio.CancelledError:
        for t in worker_tasks:
            t.cancel()
        await asyncio.gather(*worker_tasks, return_exceptions=True)
        display.finish()
        display.error("\ninterrupted")
        sys.exit(130)

    for task in worker_tasks:
        task.cancel()

    await asyncio.gather(*worker_tasks, return_exceptions=True)

    final_tasks = await state.get_all_tasks()
    completed = len([t for t in final_tasks if t.status is TaskStatus.COMPLETED])
    failed = len([t for t in final_tasks if t.status is TaskStatus.FAILED])

    logging.info("goal satisfied")
    display.finish()
    display.event(
        f"done. {completed}/{total} completed"
        + (f", {failed} failed" if failed > 0 else "")
    )


if __name__ == "__main__":
    run()
