from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from demiurg.config import Config
from demiurg.judge import Judge
from demiurg.planner import Planner
from demiurg.state import StateManager
from demiurg.types_ import Task
from demiurg.worker import Worker


async def main() -> None:
    parser = argparse.ArgumentParser(description="autonomous coding agent")
    parser.add_argument("design", nargs="?", help="design file")
    parser.add_argument("-c", "--continue", dest="cont", action="store_true", help="continue from last run")
    args = parser.parse_args()

    if not args.cont and not args.design:
        parser.print_help()
        sys.exit(1)

    try:
        cfg = Config.load()
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    Path(cfg.log_dir).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=f"{cfg.log_dir}/demiurg.log",
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%Y/%m/%d %H:%M:%S",
    )

    logging.info("starting demiurg")

    try:
        state = StateManager(cfg.data_dir)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.cont:
        work = state.get_work_state()
        if not work:
            print("error: no previous run found", file=sys.stderr)
            sys.exit(1)
        if work.is_complete:
            print("goal already satisfied")
            sys.exit(0)
        logging.info(f"continuing: {work.design_file}")
        await state.reset_interrupted_tasks()
    else:
        design_file = args.design
        if not Path(design_file).exists():
            print(f"error: {design_file} not found", file=sys.stderr)
            sys.exit(1)

        try:
            goal_text = Path(design_file).read_text().strip()
        except OSError as e:
            print(f"error: cannot read {design_file}: {e}", file=sys.stderr)
            sys.exit(1)

        if not goal_text:
            print(f"error: {design_file} is empty", file=sys.stderr)
            sys.exit(1)

        logging.info(f"new run: {design_file}")
        await state.init_work(design_file, goal_text)

        planner = Planner(cfg, state)
        tasks = await planner.plan_once()

        if not tasks:
            print("error: no tasks generated from design")
            sys.exit(1)

        logging.info(f"generated {len(tasks)} tasks")
        print(f"generated {len(tasks)} tasks")

    queue: asyncio.Queue[Task] = asyncio.Queue()

    pending = await state.get_pending_tasks()
    for task in pending:
        await queue.put(task)

    workers = [Worker(f"worker-{i}", cfg, state) for i in range(cfg.num_workers)]
    judge = Judge(state)

    worker_tasks = [asyncio.create_task(w.run(queue)) for w in workers]
    judge_task = asyncio.create_task(judge.run())

    logging.info("system running")
    print("working...")

    await judge_task

    for task in worker_tasks:
        task.cancel()

    await asyncio.gather(*worker_tasks, return_exceptions=True)

    logging.info("goal satisfied")
    print("goal satisfied")


def run() -> None:
    """entry point for uvx/installed command"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\ninterrupted")
        sys.exit(130)


if __name__ == "__main__":
    run()
