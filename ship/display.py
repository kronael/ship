from __future__ import annotations

import shutil
import sys
from datetime import datetime

from ship.types_ import TaskStatus


class Display:
    """pacman-style multi-line task panel

    tty: redraws panel in place using ANSI escape codes.
    non-tty: prints one line per state change.
    quiet (verbosity=0): errors only.
    """

    def __init__(self):
        self.is_tty = sys.stdout.isatty()
        self.verbosity = 1
        self._tasks: list[tuple[str, TaskStatus, str]] = []
        self._phase = "executing"
        self._panel_lines = 0
        self._prev_statuses: dict[str, TaskStatus] = {}
        self._plan_shown = False

    def banner(self, msg: str) -> None:
        """print header + separator"""
        if self.verbosity < 1:
            return
        cols = self._cols()
        print(msg)
        print("\u2500" * min(len(msg), cols))

    def set_tasks(
        self,
        tasks: list[tuple[str, TaskStatus, str]],
    ) -> None:
        self._tasks = tasks

    def set_phase(self, phase: str) -> None:
        self._phase = phase

    def show_plan(
        self,
        tasks: list[tuple[str, TaskStatus, str]] | None = None,
    ) -> None:
        """print the full task list once (no cursor tricks)

        tasks: full list to display; falls back to self._tasks if omitted.
        Always seeds _prev_statuses from the full list so the live window
        doesn't emit spurious 'launched' events for already-known tasks.
        """
        render = tasks if tasks is not None else self._tasks
        if self.verbosity < 1 or not render:
            return
        self._plan_shown = True

        cols = self._cols()
        total = len(render)
        w = len(str(total))
        print()
        for i, (desc, status, _worker) in enumerate(render):
            tag = f"[{i + 1:>{w}}/{total}]"
            ind = {
                TaskStatus.COMPLETED: "done",
                TaskStatus.FAILED: "FAIL",
                TaskStatus.RUNNING: "...",
            }.get(status, " -")
            pre = f"  {tag} "
            suf = f"  {ind}"
            avail = cols - len(pre) - len(suf)
            if avail > 0 and len(desc) > avail:
                desc = desc[: avail - 1] + "\u2026"
            print(f"{pre}{desc:<{max(avail, 0)}}{suf}")
        print()

        # seed from full list so live window never shows spurious events
        self._prev_statuses = {desc: status for desc, status, _ in render}

    def refresh(self) -> None:
        """emit lines for tasks whose status changed, then summary"""
        if self.verbosity < 1 or not self._tasks:
            return

        # non-tty: skip (event() already prints lines)
        if not self.is_tty:
            return

        # emit change lines
        for desc, status, worker in self._tasks:
            prev = self._prev_statuses.get(desc)
            if prev == status:
                continue
            self._prev_statuses[desc] = status
            if status is TaskStatus.RUNNING:
                tag = worker if worker else "..."
                self._print_change(f"  [{tag}] launching: {desc}")
            elif status is TaskStatus.COMPLETED:
                self._print_change(f"  [--] done: {desc}")
            elif status is TaskStatus.FAILED:
                self._print_change(f"  [--] failed: {desc}")

        # overwrite summary line in place
        total = len(self._tasks)
        done = sum(1 for _, s, _ in self._tasks if s is TaskStatus.COMPLETED)
        fail = sum(1 for _, s, _ in self._tasks if s is TaskStatus.FAILED)
        run = sum(1 for _, s, _ in self._tasks if s is TaskStatus.RUNNING)

        parts = [f"{done}/{total} ({done * 100 // total}%)"]
        if run:
            parts.append(f"{run} running")
        if fail:
            parts.append(f"{fail} failed")
        summary = f"  {', '.join(parts)}  {self._phase}"

        if self._panel_lines > 0:
            sys.stdout.write(f"\033[{self._panel_lines}A")
        self._panel_lines = 1
        sys.stdout.write(f"\033[K{summary}\n")
        sys.stdout.flush()

    def _print_change(self, msg: str) -> None:
        """print a change line above the summary"""
        if self._panel_lines > 0:
            sys.stdout.write(f"\033[{self._panel_lines}A")
            sys.stdout.write(f"\033[K{msg}\n")
            # re-reserve summary space
            for _ in range(self._panel_lines):
                sys.stdout.write("\n")
            sys.stdout.write(f"\033[{self._panel_lines}A")
        else:
            sys.stdout.write(f"{msg}\n")
        sys.stdout.flush()

    def event(self, msg: str, min_level: int = 1) -> None:
        """print a log line above the summary"""
        if self.verbosity < min_level:
            return
        if self.is_tty and self._panel_lines > 0:
            # insert line above summary
            sys.stdout.write(f"\033[{self._panel_lines}A")
            sys.stdout.write(f"\033[K{msg}\n")
            # rewrite summary below
            for _ in range(self._panel_lines):
                sys.stdout.write("\n")
            sys.stdout.write(f"\033[{self._panel_lines}A")
            sys.stdout.flush()
        else:
            print(msg)

    def error(self, msg: str) -> None:
        """always print, even in quiet mode"""
        print(msg, file=sys.stderr)

    def clear_status(self) -> None:
        """clear the summary line"""
        if self.is_tty and self._panel_lines > 0:
            sys.stdout.write(f"\033[{self._panel_lines}A")
            for _ in range(self._panel_lines):
                sys.stdout.write("\033[K\n")
            sys.stdout.write(f"\033[{self._panel_lines}A")
            sys.stdout.flush()
        self._panel_lines = 0

    def finish(self) -> None:
        """clear panel"""
        if self.is_tty and self._panel_lines > 0:
            sys.stdout.write(f"\033[{self._panel_lines}A")
            for _ in range(self._panel_lines):
                sys.stdout.write("\033[K\n")
            sys.stdout.write(f"\033[{self._panel_lines}A")
            sys.stdout.flush()
        self._panel_lines = 0
        self._tasks = []

    def _cols(self) -> int:
        try:
            return shutil.get_terminal_size().columns
        except Exception:
            return 80


# singleton
display = Display()

# in-memory log entries appended by workers/judge
_log_entries: list[str] = []


def log_entry(msg: str) -> None:
    """append a timestamped log entry (shown in PROGRESS.md)"""
    now = datetime.now().strftime("%H:%M:%S")
    _log_entries.append(f"- `{now}` {msg}")


def write_progress_md(
    total: int,
    completed: int,
    running: int,
    pending: int,
    failed: int,
    workers: list[str],
    phase: str = "executing",
    path: str = "PROGRESS.md",
) -> None:
    """write PROGRESS.md with state + log"""
    now = datetime.now().strftime("%b %d %H:%M:%S")
    pct = (completed / total * 100) if total > 0 else 0
    bar_len = 30
    filled = int(bar_len * completed / total) if total > 0 else 0
    bar = "\u2588" * filled + "\u2591" * (bar_len - filled)

    lines = [
        "# PROGRESS",
        "",
        f"updated: {now}  ",
        f"phase: {phase}",
        "",
        "```",
        f"[{bar}] {pct:.0f}%  {completed}/{total}",
        "```",
        "",
        "| | count |",
        "|---|---|",
        f"| completed | {completed} |",
        f"| running | {running} |",
        f"| pending | {pending} |",
        f"| failed | {failed} |",
        "",
    ]

    if workers:
        lines.append("## workers")
        lines.append("")
        for w in workers:
            lines.append(f"- {w}")
        lines.append("")

    if _log_entries:
        lines.append("## log")
        lines.append("")
        for entry in _log_entries:
            lines.append(entry)
        lines.append("")

    try:
        with open(path, "w") as f:
            f.write("\n".join(lines))
    except OSError:
        pass
