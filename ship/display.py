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

    def refresh(self) -> None:
        """redraw the task panel in place (tty only)"""
        if self.verbosity < 1 or not self.is_tty or not self._tasks:
            return

        cols = self._cols()
        total = len(self._tasks)
        done = sum(1 for _, s, _ in self._tasks if s is TaskStatus.COMPLETED)
        fail = sum(1 for _, s, _ in self._tasks if s is TaskStatus.FAILED)
        run = sum(1 for _, s, _ in self._tasks if s is TaskStatus.RUNNING)

        lines: list[str] = [""]
        w = len(str(total))
        for i, (desc, status, worker) in enumerate(self._tasks):
            tag = f"[{i + 1:>{w}}/{total}]"
            ind = {
                TaskStatus.COMPLETED: "done",
                TaskStatus.FAILED: "FAIL",
                TaskStatus.RUNNING: f"{worker} ..." if worker else "...",
            }.get(status, " -")
            pre = f"  {tag} "
            suf = f"  {ind}"
            avail = cols - len(pre) - len(suf)
            if avail > 0 and len(desc) > avail:
                desc = desc[: avail - 1] + "\u2026"
            lines.append(f"{pre}{desc:<{max(avail, 0)}}{suf}")

        lines.append("")
        parts = [f"{done}/{total} ({done * 100 // total}%)"]
        if run:
            parts.append(f"{run} running")
        if fail:
            parts.append(f"{fail} failed")
        lines.append(f"  {', '.join(parts)} {self._phase}")
        lines.append("")

        # move cursor up to overwrite previous panel
        if self._panel_lines > 0:
            sys.stdout.write(f"\033[{self._panel_lines}A")
        self._panel_lines = len(lines)
        for line in lines:
            sys.stdout.write(f"\033[K{line}\n")
        sys.stdout.flush()

    def event(self, msg: str, min_level: int = 1) -> None:
        """print a log line above the panel"""
        if self.verbosity < min_level:
            return
        if self.is_tty and self._panel_lines > 0:
            sys.stdout.write(f"\033[{self._panel_lines}A\033[K{msg}\n")
            saved = self._panel_lines
            self._panel_lines = 0
            self.refresh()
            if self._panel_lines == 0:
                self._panel_lines = saved
        else:
            print(msg)

    def error(self, msg: str) -> None:
        """always print, even in quiet mode"""
        print(msg, file=sys.stderr)

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
