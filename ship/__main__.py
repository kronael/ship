from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import uuid
from pathlib import Path

import click

from ship.config import Config
from ship.display import display
from ship.judge import Judge
from ship.planner import Planner
from ship.plan import run_plan
from ship.refiner import Refiner
from ship.state import StateManager
from ship.types_ import Task, TaskStatus
from ship.validator import Validator
from ship.worker import Worker

SPEC_CANDIDATES = ["SPEC.md", "spec.md"]


def discover_spec(context: tuple[str, ...]) -> str:
    """resolve spec from context args or auto-discovery

    priority:
    1. explicit path(s) from context args
    2. SPEC.md / spec.md in cwd
    3. first file in specs/*.md
    4. error
    """
    if context:
        # single path arg: file or dir
        if len(context) == 1:
            p = Path(context[0])
            if p.exists():
                return str(p)
        # multiple args or non-existent single arg treated as
        # inline context (caller handles this)
        return ""

    for candidate in SPEC_CANDIDATES:
        if Path(candidate).exists():
            return candidate

    specs_dir = Path("specs")
    if specs_dir.is_dir():
        md_files = sorted(specs_dir.glob("*.md"))
        if md_files:
            return str(md_files[0])

    return ""


def plan_mode(context: tuple[str, ...]) -> None:
    """run interactive planning loop"""
    asyncio.run(run_plan(context))


@click.command()
@click.argument("context", nargs=-1)
@click.option("-p", "--plan", "plan_", is_flag=True,
              help="[experimental] plan mode (see kronael/rsx for example)")
@click.option("-c", "--continue", "cont", is_flag=True,
              help="continue from last run")
@click.option("-w", "--workers", type=int,
              help="number of parallel workers")
@click.option("-t", "--timeout", type=int,
              help="task timeout in seconds")
@click.option("-m", "--max-turns", type=int,
              help="max agentic turns per task")
@click.option("-v", "--verbose", is_flag=True,
              help="show prompts and raw responses")
def run(
    context: tuple[str, ...],
    plan_: bool,
    cont: bool,
    workers: int | None,
    timeout: int | None,
    max_turns: int | None,
    verbose: bool,
) -> None:
    """autonomous coding agent

    Discovers SPEC.md by default, or pass files/dirs as args.
    """
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(
            sig,
            lambda s, f: (_ for _ in ()).throw(KeyboardInterrupt()),
        )

    if plan_:
        plan_mode(context)
        return

    try:
        asyncio.run(
            _main(context, cont, workers, timeout, max_turns, verbose)
        )
    except KeyboardInterrupt:
        click.echo("\ninterrupted")
        sys.exit(130)


async def _main(
    context: tuple[str, ...],
    cont: bool,
    workers: int | None,
    timeout: int | None,
    max_turns: int | None,
    verbose: bool,
) -> None:
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
        # resolve spec
        spec_file = discover_spec(context)
        inline_context: list[str] = []

        if spec_file:
            try:
                goal_text = Path(spec_file).read_text().strip()
            except OSError as e:
                click.echo(
                    f"error: cannot read {spec_file}: {e}", err=True
                )
                sys.exit(1)
            if not goal_text:
                click.echo(f"error: {spec_file} is empty", err=True)
                sys.exit(1)
            # if extra args beyond the file, add as context
            if context and len(context) > 1:
                inline_context = list(context[1:])
        elif context:
            # all args are inline context, no spec file found
            # treat first arg as spec if it's a readable file
            # otherwise everything is context for the validator
            goal_text = " ".join(context)
            inline_context = list(context)
        else:
            click.echo(
                "error: no spec found "
                "(try SPEC.md, specs/*.md, or ship -p)",
                err=True,
            )
            sys.exit(1)

        validator = Validator(
            verbose=verbose,
            session_id=str(uuid.uuid4()),
        )
        validation = await validator.validate(
            goal_text, context=inline_context
        )
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
                click.echo(
                    f"error: cannot write {rejection_path}: {e}",
                    err=True,
                )
                sys.exit(1)
            click.echo("error: design rejected (see REJECTION.md)")
            sys.exit(1)

        project_text = validation.project_md.strip()
        if project_text:
            try:
                Path("PROJECT.md").write_text(project_text + "\n")
            except OSError as e:
                click.echo(
                    f"error: cannot write PROJECT.md: {e}", err=True
                )
                sys.exit(1)

        design_file = spec_file or "<inline>"
        logging.info(f"new run: {design_file}")
        combined_goal = goal_text
        if project_text:
            combined_goal = (
                f"{goal_text}\n\n---\n\n"
                f"# PROJECT\n\n{project_text}\n"
            )
        await state.init_work(design_file, combined_goal)

        planner = Planner(
            cfg, state, session_id=str(uuid.uuid4()),
        )
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
    completed = len(
        [t for t in all_tasks if t.status is TaskStatus.COMPLETED]
    )

    num_workers = min(cfg.num_workers, len(pending))
    if num_workers < cfg.num_workers:
        logging.info(
            f"reducing workers from {cfg.num_workers} "
            f"to {num_workers} (only {len(pending)} tasks)"
        )

    work = state.get_work_state()
    project_context = work.project_context if work else ""
    if project_context:
        click.echo(f"\n🎯 project: {project_context[:80]}...")

    click.echo(f"\n📊 progress: {completed}/{total} tasks completed")
    click.echo(f"👥 workers: {num_workers}")
    click.echo(f"🔄 max turns per task: {cfg.max_turns}")
    click.echo(f"⏱️  timeout: {cfg.task_timeout}s\n")
    click.echo("─" * 60)

    judge = Judge(
        state, queue,
        project_context=project_context, verbose=cfg.verbose,
        session_id=str(uuid.uuid4()),
    )
    worker_list = [
        Worker(
            f"w{i}", cfg, state,
            project_context=project_context, judge=judge,
            session_id=str(uuid.uuid4()),
        )
        for i in range(num_workers)
    ]

    worker_tasks = [
        asyncio.create_task(w.run(queue)) for w in worker_list
    ]
    judge_task = asyncio.create_task(judge.run())

    logging.info("system running")

    await judge_task

    for task in worker_tasks:
        task.cancel()

    await asyncio.gather(*worker_tasks, return_exceptions=True)

    final_tasks = await state.get_all_tasks()
    completed = len(
        [t for t in final_tasks if t.status is TaskStatus.COMPLETED]
    )
    failed = len(
        [t for t in final_tasks if t.status is TaskStatus.FAILED]
    )

    logging.info("goal satisfied")
    display.clear_status()
    click.echo("\n" + "─" * 60)
    click.echo(f"\ndone. {completed}/{total} completed", nl=False)
    if failed > 0:
        click.echo(f", {failed} failed", nl=False)
    click.echo()


if __name__ == "__main__":
    run()
