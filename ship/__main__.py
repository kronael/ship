from __future__ import annotations

import asyncio
import fcntl
import hashlib
import logging
import shutil
import signal
import sys
from pathlib import Path

import click

from ship.claude_code import ClaudeCodeClient
from ship.config import Config
from ship.display import display
from ship.judge import Judge
from ship.planner import Planner
from ship.state import StateManager
from ship.types_ import Task, TaskStatus
from ship.validator import Validator
from ship.worker import Worker

SPEC_CANDIDATES = ["SPEC.md", "spec.md"]


VERSION = "0.6.4"


def _has_real_state(data_dir: Path) -> bool:
    return (data_dir / "work.json").exists() and (data_dir / "tasks.json").exists()


def _wipe_state(data_dir: Path) -> None:
    shutil.rmtree(data_dir, ignore_errors=True)


def _spec_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _load_validated_hash(data_dir: Path) -> str:
    try:
        return (data_dir / "validated").read_text().strip()
    except OSError:
        return ""


def _save_validated_hash(data_dir: Path, h: str) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "validated").write_text(h + "\n")


def _spec_slug(context: tuple[str, ...]) -> str | None:
    """derive a slug from a single .md file arg, or None"""
    if len(context) != 1:
        return None
    p = Path(context[0])
    if p.suffix == ".md" and not p.is_dir():
        return p.stem
    return None


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
@click.option(
    "-c",
    "--continue",
    "cont",
    is_flag=True,
    hidden=True,
    help="[deprecated] alias for default behaviour",
)
@click.option("-f", "--fresh", is_flag=True, help="wipe state and start fresh")
@click.option("-k", "--check", is_flag=True, help="validate spec only, then exit")
@click.option("-s", "--skip-validation", is_flag=True, help="skip spec validation")
@click.option(
    "-n", "--max-workers", "workers", type=int, help="number of parallel workers"
)
@click.option(
    "-w",
    "--workers",
    "workers_legacy",
    type=int,
    hidden=True,
    help="[deprecated] use -n",
)
@click.option("-t", "--timeout", type=int, help="task timeout in seconds")
@click.option("-m", "--max-turns", type=int, help="max agentic turns per task")
@click.option("-v", "--verbose", count=True, help="increase verbosity (-v, -vv)")
@click.option("-q", "--quiet", is_flag=True, help="errors only")
@click.option(
    "-x", "--codex", is_flag=True, help="enable codex refiner (off by default)"
)
@click.option(
    "-p",
    "--prompt",
    "override_prompt",
    default="",
    help="override instruction for all LLM calls",
)
def run(
    context: tuple[str, ...],
    cont: bool,
    fresh: bool,
    check: bool,
    skip_validation: bool,
    workers: int | None,
    workers_legacy: int | None,
    timeout: int | None,
    max_turns: int | None,
    verbose: int,
    quiet: bool,
    codex: bool,
    override_prompt: str,
) -> None:
    """autonomous coding agent

    Discovers SPEC.md by default, or pass files/dirs as args.
    """

    def _sigterm(signum, frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, _sigterm)

    if check and skip_validation:
        click.echo("error: -k and -s are mutually exclusive", err=True)
        sys.exit(1)

    verbosity = 0 if quiet else min(1 + verbose, 3)
    # -w is legacy alias for -n
    effective_workers = workers if workers is not None else workers_legacy

    try:
        asyncio.run(
            _main(
                context,
                fresh,
                check,
                skip_validation,
                effective_workers,
                timeout,
                max_turns,
                verbosity,
                codex,
                override_prompt,
            )
        )
    except KeyboardInterrupt:
        display.finish()
        display.error("\ninterrupted")
        sys.exit(130)


async def _reeval_spec_change(
    data_dir: Path,
    old_tasks: list[Task],
    new_spec: str,
    verbosity: int,
) -> str:
    """ask LLM to evaluate spec change: returns 'keep' or 'replan'"""
    plan_path = data_dir / "PLAN.md"
    old_plan = ""
    try:
        old_plan = plan_path.read_text()
    except OSError:
        pass

    done = sum(1 for t in old_tasks if t.status is TaskStatus.COMPLETED)
    pending = len(old_tasks) - done
    task_summary = "\n".join(
        f"- [{t.status.value}] {t.description[:80]}" for t in old_tasks
    )

    prompt = (
        "The spec has changed. Evaluate whether the existing completed work "
        "is still valid under the new spec.\n\n"
        f"Old plan:\n{old_plan}\n\n"
        f"Task summary ({done} done, {pending} remaining):\n{task_summary}\n\n"
        f"New spec:\n{new_spec}\n\n"
        "If most completed work is still valid and only new tasks need to be added, "
        "output <keep/>.\n"
        "If the spec change fundamentally alters what was built, output <replan/>.\n"
        "Output only the tag."
    )

    if verbosity >= 2:
        print("\n[spec-change re-evaluation prompt]")
        print(prompt[:500] + "..." if len(prompt) > 500 else prompt)

    client = ClaudeCodeClient(model="sonnet", role="replanner")
    try:
        result, _ = await client.execute(prompt, timeout=120)
    except Exception as e:
        logging.warning(f"spec-change eval failed: {e}, defaulting to replan")
        return "replan"

    if "<keep" in result:
        return "keep"
    return "replan"


async def _main(
    context: tuple[str, ...],
    fresh: bool,
    check: bool,
    skip_validation: bool,
    workers: int | None,
    timeout: int | None,
    max_turns: int | None,
    verbosity: int,
    use_codex: bool = False,
    override_prompt: str = "",
) -> None:
    slug = _spec_slug(context)
    data_dir_arg = f".ship/{slug}" if slug else None

    try:
        cfg = Config.load(
            workers=workers,
            timeout=timeout,
            max_turns=max_turns,
            verbosity=verbosity,
            use_codex=use_codex,
            data_dir=data_dir_arg,
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

    data_dir = Path(cfg.data_dir)

    # state detection: implicit continuation / spec-change / fresh
    _auto_cont = False
    _spec_changed = False
    _new_spec_text: str = ""

    if fresh:
        if _has_real_state(data_dir) or data_dir.exists():
            _wipe_state(data_dir)
            logging.info("fresh: wiped state")
    elif not check:
        if _has_real_state(data_dir):
            try:
                _probe = StateManager(cfg.data_dir)
            except RuntimeError:
                _probe = None
            _work = _probe.get_work_state() if _probe else None
            _tasks = await _probe.get_all_tasks() if _probe else []
            _done = sum(1 for t in _tasks if t.status is TaskStatus.COMPLETED)
            _total = len(_tasks)

            # compute current spec hash to detect changes
            _spec_files = discover_spec(context)
            if _spec_files:
                try:
                    _new_spec_text = "\n\n".join(
                        f.read_text() for f in _spec_files
                    ).strip()
                except OSError:
                    _new_spec_text = ""
            elif context:
                _new_spec_text = " ".join(context)

            _new_hash = _spec_hash(_new_spec_text) if _new_spec_text else ""
            _saved_hash = _work.spec_hash if _work else ""

            if (
                _work
                and _work.is_complete
                and (not _new_hash or _new_hash == _saved_hash)
            ):
                print(f"ship: done ({_done}/{_total} tasks). use -f to restart.")
                sys.exit(0)
            elif _new_hash and _saved_hash and _new_hash != _saved_hash:
                # spec changed — will handle below
                _spec_changed = True
                logging.info("spec changed: entering re-evaluation")
            else:
                # same spec, incomplete run — auto-continue
                _auto_cont = True
                logging.info(f"auto-continuing: {_done}/{_total} tasks done")
        elif data_dir.exists():
            # stale state with no real work — wipe silently
            _wipe_state(data_dir)

    try:
        state = StateManager(cfg.data_dir)
    except RuntimeError as e:
        display.error(f"error: {e}")
        sys.exit(1)

    # exclusive non-blocking lock: bail if another ship owns this data_dir
    lock_path = data_dir / "ship.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    _lock_fd = lock_path.open("w")
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        display.error(f"error: ship already running in {cfg.data_dir}")
        sys.exit(1)

    if _spec_changed:
        # re-evaluation path: LLM decides keep vs replan
        _old_tasks = await state.get_all_tasks()
        _decision = await _reeval_spec_change(
            data_dir, _old_tasks, _new_spec_text, verbosity
        )
        if _decision == "keep":
            display.event("spec changed: keeping completed tasks, adding new tasks")
            _auto_cont = True
        else:
            display.event("spec changed: replanning from scratch")
            _wipe_state(data_dir)
            _auto_cont = False
            # rebuild state after wipe
            try:
                state = StateManager(cfg.data_dir)
            except RuntimeError as e:
                display.error(f"error: {e}")
                sys.exit(1)

    if _auto_cont:
        work = state.get_work_state()
        if not work:
            display.error("error: no previous run found")
            sys.exit(1)
        if work.is_complete:
            display.event("goal already satisfied")
            sys.exit(0)
        logging.info(f"continuing: {work.design_file}")
        await state.reset_interrupted_tasks()
        # guard: no tasks in state means planning never completed
        _saved = await state.get_all_tasks()
        if not _saved:
            display.error("error: no tasks in saved state — re-run to re-plan")
            sys.exit(1)
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

        # skip validation if spec unchanged since last accepted run
        spec_h = _spec_hash(goal_text)
        already_validated = _load_validated_hash(data_dir) == spec_h

        if skip_validation:
            _save_validated_hash(data_dir, spec_h)
            display.event("\033[33m⏭\033[0m skipping validation (-s)")
            validation_project_md = ""
        elif already_validated:
            display.event("\033[32m✓\033[0m spec already validated")
            validation_project_md = ""
        else:
            display.event("\033[36m⟳\033[0m validating spec...")
            validator = Validator(verbosity=cfg.verbosity)
            validation = await validator.validate(
                goal_text,
                context=inline_context,
                override_prompt=override_prompt,
            )

            if not validation.accept:
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
                rejection_path = data_dir / "REJECTION.md"
                data_dir.mkdir(parents=True, exist_ok=True)
                try:
                    rejection_path.write_text(rejection)
                except OSError as e:
                    display.error(f"error: cannot write {rejection_path}: {e}")
                if verbosity >= 1:
                    print("\nrejection gaps:")
                    for g in validation.gaps:
                        print(f"  - {g}")
                    if verbosity >= 2:
                        print()
                        print(rejection)
                display.error(f"error: design rejected (see {rejection_path})")
                sys.exit(1)

            _save_validated_hash(data_dir, spec_h)
            display.event("\033[32m✓\033[0m spec ok")
            validation_project_md = validation.project_md

        if check:
            sys.exit(0)

        project_text = validation_project_md.strip() if not already_validated else ""
        if not already_validated and project_text:
            project_path = data_dir / "PROJECT.md"
            try:
                project_path.write_text(project_text + "\n")
            except OSError as e:
                display.error(f"error: cannot write {project_path}: {e}")
                sys.exit(1)

        design_file = spec_label if spec_files else "<inline>"
        logging.info(f"new run: {design_file}")
        combined_goal = goal_text
        if not already_validated and project_text:
            combined_goal = f"{goal_text}\n\n---\n\n# PROJECT\n\n{project_text}\n"
        await state.init_work(
            design_file,
            combined_goal,
            spec_hash=spec_h,
            override_prompt=override_prompt,
        )

        display.event("\033[36m⟳\033[0m planning tasks...")
        planner = Planner(cfg, state)
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

    work = state.get_work_state()
    project_context = work.project_context if work else ""
    exec_mode = work.execution_mode if work else "parallel"
    effective_override = work.override_prompt if work else override_prompt

    # -n always wins: explicit workers override exec_mode and pending cap
    if workers is not None:
        num_workers = cfg.num_workers
    elif exec_mode == "sequential":
        num_workers = 1
        logging.info("sequential mode: using 1 worker")
    else:
        num_workers = min(cfg.num_workers, max(1, len(pending)))
        if num_workers < cfg.num_workers:
            logging.info(
                f"reducing workers from {cfg.num_workers} "
                f"to {num_workers} (only {len(pending)} tasks)"
            )

    display.set_worker_count(num_workers)
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
        use_codex=cfg.use_codex,
        progress_path=str(Path(cfg.data_dir) / "PROGRESS.md"),
    )
    spec_label_for_workers = (
        (work.design_file if work else "")
        if _auto_cont
        else (spec_label if spec_files else "")
    )
    worker_list = [
        Worker(
            f"w{i}",
            cfg,
            state,
            project_context=project_context,
            override_prompt=effective_override,
            judge=judge,
            spec_files=spec_label_for_workers,
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

    if failed > 0:
        print()
        print("failed tasks:")
        for t in final_tasks:
            if t.status is TaskStatus.FAILED:
                err = (t.error or "no error")[:80]
                summ = t.summary or t.description[:40]
                print(f"  \u2717 {summ}  [{err}]")
        print()

    display.event(
        f"done. {completed}/{len(final_tasks)} completed"
        + (f", {failed} failed" if failed > 0 else "")
    )


if __name__ == "__main__":
    run()
