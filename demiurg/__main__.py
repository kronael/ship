from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

import click

from demiurg.config import Config
from demiurg.judge import Judge
from demiurg.planner import Planner
from demiurg.state import StateManager
from demiurg.types_ import Task, TaskStatus
from demiurg.worker import Worker

DEFAULT_SPEC = "DESIGN.md"


@click.command()
@click.argument("design", required=False)
@click.option("-f", "--file", "file_", help="design file (like make -f)")
@click.option("-c", "--continue", "cont", is_flag=True, help="continue from last run")
@click.option("-w", "--workers", type=int, help="number of parallel workers")
@click.option("-t", "--timeout", type=int, help="task timeout in seconds")
@click.option("-m", "--max-turns", type=int, help="max agentic turns per task")
def run(
    design: str | None,
    file_: str | None,
    cont: bool,
    workers: int | None,
    timeout: int | None,
    max_turns: int | None,
) -> None:
    """autonomous coding agent

    Reads DESIGN.md by default, or specify a design file.
    """
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(KeyboardInterrupt()))

    try:
        asyncio.run(_main(design, file_, cont, workers, timeout, max_turns))
    except KeyboardInterrupt:
        click.echo("\ninterrupted")
        sys.exit(130)


async def _main(
    design: str | None,
    file_: str | None,
    cont: bool,
    workers: int | None,
    timeout: int | None,
    max_turns: int | None,
) -> None:
    # resolve design file: -f flag > positional arg > default DESIGN.md
    design_file = file_ or design or DEFAULT_SPEC

    if not cont and not Path(design_file).exists():
        if file_ or design:
            click.echo(f"error: {design_file} not found", err=True)
        else:
            click.echo(f"error: no {DEFAULT_SPEC} found (use -f to specify)", err=True)
        sys.exit(1)

    try:
        cfg = Config.load(
            workers=workers,
            timeout=timeout,
            max_turns=max_turns,
        )
    except RuntimeError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)

    Path(cfg.log_dir).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=f"{cfg.log_dir}/demiurg.log",
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%b %d %H:%M:%S",
    )

    logging.info("starting demiurg")

    try:
        state = StateManager(cfg.data_dir)
    except RuntimeError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)

    if cont:
        work = state.get_work_state()
        if not work:
            click.echo("error: no previous run found", err=True)
            sys.exit(1)
        if work.is_complete:
            click.echo("goal already satisfied")
            sys.exit(0)
        logging.info(f"continuing: {work.design_file}")
        await state.reset_interrupted_tasks()
    else:
        try:
            goal_text = Path(design_file).read_text().strip()
        except OSError as e:
            click.echo(f"error: cannot read {design_file}: {e}", err=True)
            sys.exit(1)

        if not goal_text:
            click.echo(f"error: {design_file} is empty", err=True)
            sys.exit(1)

        logging.info(f"new run: {design_file}")
        await state.init_work(design_file, goal_text)

        planner = Planner(cfg, state)
        tasks = await planner.plan_once()

        if not tasks:
            click.echo("error: no tasks generated from design")
            sys.exit(1)

        logging.info(f"generated {len(tasks)} tasks")
        click.echo(f"generated {len(tasks)} tasks")

    queue: asyncio.Queue[Task] = asyncio.Queue()

    pending = await state.get_pending_tasks()
    for task in pending:
        await queue.put(task)

    all_tasks = await state.get_all_tasks()
    total = len(all_tasks)
    completed = len([t for t in all_tasks if t.status is TaskStatus.COMPLETED])

    # adjust worker count to task count (no more workers than tasks)
    num_workers = min(cfg.num_workers, len(pending))
    if num_workers < cfg.num_workers:
        logging.info(f"reducing workers from {cfg.num_workers} to {num_workers} (only {len(pending)} tasks)")

    # get skills from work state
    work = state.get_work_state()
    skills = work.skills if work else []
    if skills:
        click.echo(f"skills: {', '.join(skills)}")

    click.echo(f"progress: {completed}/{total} tasks completed")
    click.echo(f"workers: {num_workers}\n")

    worker_list = [Worker(f"worker-{i}", cfg, state, skills=skills) for i in range(num_workers)]
    judge = Judge(state)

    worker_tasks = [asyncio.create_task(w.run(queue)) for w in worker_list]
    judge_task = asyncio.create_task(judge.run())

    logging.info("system running")

    await judge_task

    for task in worker_tasks:
        task.cancel()

    await asyncio.gather(*worker_tasks, return_exceptions=True)

    final_tasks = await state.get_all_tasks()
    completed = len([t for t in final_tasks if t.status is TaskStatus.COMPLETED])
    failed = len([t for t in final_tasks if t.status is TaskStatus.FAILED])

    logging.info("goal satisfied")
    click.echo(f"\ngoal satisfied: {completed}/{total} completed, {failed} failed")


if __name__ == "__main__":
    run()
