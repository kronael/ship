from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

import click

from ship.config import Config
from ship.display import display
from ship.judge import Judge
from ship.planner import Planner
from ship.refiner import Refiner
from ship.state import StateManager
from ship.types_ import Task, TaskStatus
from ship.validator import Validator
from ship.worker import Worker

DEFAULT_SPEC = "DESIGN.md"


@click.command()
@click.argument("design", required=False)
@click.option("-f", "--file", "file_", help="design file (like make -f)")
@click.option("-c", "--continue", "cont", is_flag=True, help="continue from last run")
@click.option("-w", "--workers", type=int, help="number of parallel workers")
@click.option("-t", "--timeout", type=int, help="task timeout in seconds")
@click.option("-m", "--max-turns", type=int, help="max agentic turns per task")
@click.option("-v", "--verbose", is_flag=True, help="show prompts and raw responses")
def run(
    design: str | None,
    file_: str | None,
    cont: bool,
    workers: int | None,
    timeout: int | None,
    max_turns: int | None,
    verbose: bool,
) -> None:
    """autonomous coding agent

    Reads DESIGN.md by default, or specify a design file.
    """
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(KeyboardInterrupt()))

    try:
        asyncio.run(_main(design, file_, cont, workers, timeout, max_turns, verbose))
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
    verbose: bool,
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
            verbose=verbose,
        )
    except RuntimeError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)

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

        validator = Validator(verbose=verbose)
        validation = await validator.validate(goal_text)
        if not validation.accept:
            rejection_path = Path("REJECTION.md")
            gaps_text = "\n".join(f"- {g}" for g in validation.gaps) or "- (no details provided)"
            rejection = (
                "# REJECTION\n\n"
                "The design is not specific enough to execute. Please address these gaps:\n\n"
                f"{gaps_text}\n"
            )
            try:
                rejection_path.write_text(rejection)
            except OSError as e:
                click.echo(f"error: cannot write {rejection_path}: {e}", err=True)
                sys.exit(1)
            click.echo("error: design rejected (see REJECTION.md)")
            sys.exit(1)

        project_text = validation.project_md.strip()
        if project_text:
            try:
                Path("PROJECT.md").write_text(project_text + "\n")
            except OSError as e:
                click.echo(f"error: cannot write PROJECT.md: {e}", err=True)
                sys.exit(1)

        logging.info(f"new run: {design_file}")
        combined_goal = goal_text
        if project_text:
            combined_goal = (
                f"{goal_text}\n\n---\n\n# PROJECT\n\n{project_text}\n"
            )
        await state.init_work(design_file, combined_goal)

        planner = Planner(cfg, state)
        tasks = await planner.plan_once()

        if not tasks:
            click.echo("error: no tasks generated from design")
            sys.exit(1)

        logging.info(f"generated {len(tasks)} tasks")
        click.echo(f"\n📝 generated {len(tasks)} tasks")

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

    # get project context for workers
    work = state.get_work_state()
    project_context = work.project_context if work else ""
    if project_context:
        click.echo(f"\n🎯 project: {project_context[:80]}...")

    click.echo(f"\n📊 progress: {completed}/{total} tasks completed")
    click.echo(f"👥 workers: {num_workers}")
    click.echo(f"🔄 max turns per task: {cfg.max_turns}")
    click.echo(f"⏱️  timeout: {cfg.task_timeout}s\n")
    click.echo("─" * 60)

    judge = Judge(state, queue, project_context=project_context, verbose=cfg.verbose)
    worker_list = [
        Worker(f"w{i}", cfg, state, project_context=project_context, judge=judge)
        for i in range(num_workers)
    ]

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
    display.clear_status()
    click.echo("\n" + "─" * 60)
    click.echo(f"\ndone. {completed}/{total} completed", nl=False)
    if failed > 0:
        click.echo(f", {failed} failed", nl=False)
    click.echo()


if __name__ == "__main__":
    run()
