from __future__ import annotations

import shutil
import sys
from datetime import datetime

from ship.types_ import TaskStatus


def _truncate(text: str, max_words: int = 8) -> str:
    """first N words, truncated with ellipsis if needed"""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "\u2026"


_STATUS_ICON = {
    TaskStatus.COMPLETED: ("\033[32m\u2713\033[0m", "\u2713"),
    TaskStatus.FAILED: ("\033[31m\u2717\033[0m", "\u2717"),
    TaskStatus.RUNNING: ("\033[33m\u27f3\033[0m", "\u27f3"),
    TaskStatus.PENDING: ("\033[2m\u00b7\033[0m", "\u00b7"),
}


class Display:
    """worker-centric TUI with task overview + worker panel

    tty: redraws panel in place using ANSI escape codes.
    non-tty: prints one line per state change.
    quiet (verbosity=0): errors only.
    """

    def __init__(self):
        self.is_tty = sys.stdout.isatty()
        self.verbosity = 1
        self._tasks: list[tuple[str, TaskStatus, str, str, str]] = []
        self._phase = "executing"
        self._panel_lines = 0
        self._prev_statuses: dict[str, TaskStatus] = {}
        self._plan_shown = False
        self._global_done: int = 0
        self._global_total: int = 0
        # task summaries (8-word truncated)
        self._task_summaries: list[str] = []
        self._task_desc_to_idx: dict[str, int] = {}
        # worker panel state
        self._worker_count: int = 0
        self._worker_progress: dict[str, tuple[int, str, str]] = {}
        # task_idx, task_summary, progress_msg

    def banner(self, msg: str) -> None:
        """print header + separator"""
        if self.verbosity < 1:
            return
        cols = self._cols()
        print(msg)
        print("\u2500" * min(len(msg), cols))

    def set_tasks(
        self,
        tasks: list[tuple[str, TaskStatus, str, str, str]],
    ) -> None:
        self._tasks = tasks

    def set_phase(self, phase: str) -> None:
        self._phase = phase

    def set_global(self, done: int, total: int) -> None:
        self._global_done = done
        self._global_total = total

    def set_worker_count(self, n: int) -> None:
        self._worker_count = n

    def set_worker_progress(
        self,
        wid: str,
        task_idx: int,
        task_summary: str,
        msg: str,
    ) -> None:
        self._worker_progress[wid] = (task_idx, task_summary, msg)

    def clear_worker(self, wid: str) -> None:
        self._worker_progress.pop(wid, None)

    def task_info(self, desc: str) -> tuple[int, str]:
        """return (1-based index, 8-word summary) for a task desc"""
        idx = self._task_desc_to_idx.get(desc, -1)
        if idx >= 0 and idx < len(self._task_summaries):
            return idx + 1, self._task_summaries[idx]
        return 0, _truncate(desc)

    def show_plan(
        self,
        tasks: list[tuple[str, TaskStatus, str, str, str]] | None = None,
    ) -> None:
        """print the full task list once (no cursor tricks)"""
        render = tasks if tasks is not None else self._tasks
        if self.verbosity < 1 or not render:
            return
        self._plan_shown = True

        # build 8-word summaries and desc->index mapping
        self._task_summaries = [_truncate(desc) for desc, *_ in render]
        self._task_desc_to_idx = {desc: i for i, (desc, *_) in enumerate(render)}

        cols = self._cols()
        w = len(str(len(render)))
        print()
        for i, (desc, status, *_rest) in enumerate(render):
            icon_c, _ = _STATUS_ICON.get(status, ("\u00b7", "\u00b7"))
            summary = self._task_summaries[i]
            pre = f"  [{i + 1:>{w}}] {icon_c} "
            avail = cols - 2 - w - 5  # approx
            if len(summary) > avail > 0:
                summary = summary[: avail - 1] + "\u2026"
            print(f"{pre}{summary}")
        print()

        self._prev_statuses = {desc: status for desc, status, *_ in render}

    def refresh(self) -> None:
        """redraw task list + worker panel in place"""
        if self.verbosity < 1 or not self._tasks:
            return

        if not self.is_tty:
            return

        # emit change lines above panel
        for desc, status, worker, summary, error in self._tasks:
            prev = self._prev_statuses.get(desc)
            if prev == status:
                continue
            self._prev_statuses[desc] = status
            if status is TaskStatus.RUNNING:
                tag = worker if worker else "..."
                self._print_change(f"  [{tag}] launching: {desc}")
            elif status is TaskStatus.COMPLETED:
                label = summary if summary else desc
                self._print_change(f"  done: {label}")
            elif status is TaskStatus.FAILED:
                err = error[:60] if error else ""
                tail = f" \u2014 {err}" if err else ""
                self._print_change(f"  failed: {desc[:50]}{tail}")

        # build panel lines
        lines: list[str] = []
        cols = self._cols()

        # task section from full task list
        n = len(self._tasks)
        w = len(str(n))
        for i, (desc, status, *_rest) in enumerate(self._tasks):
            icon_c, _ = _STATUS_ICON.get(status, ("\u00b7", "\u00b7"))
            summary = (
                self._task_summaries[i]
                if i < len(self._task_summaries)
                else _truncate(desc)
            )
            lines.append(f"  [{i + 1:>{w}}] {icon_c} {summary}")

        # blank line
        lines.append("")

        # worker section
        wcount = self._worker_count or 1
        for wi in range(wcount):
            wid = f"w{wi}"
            if wid in self._worker_progress:
                tidx, tsummary, msg = self._worker_progress[wid]
                # truncate progress msg
                tag = f"[{tidx}] {tsummary}"
                pmsg = msg[:40] if len(msg) > 40 else msg
                avail = cols - 6 - len(tag) - 3
                if len(pmsg) > avail > 0:
                    pmsg = pmsg[: avail - 1] + "\u2026"
                lines.append(f"  {wid}  {pmsg}   {tag}")
            else:
                lines.append(f"  \033[2m{wid}  idle\033[0m")

        # summary line
        if self._global_total > 0:
            g_done = self._global_done
            g_total = self._global_total
            pct = g_done * 100 // g_total
            parts = [f"{g_done}/{g_total} ({pct}%)"]
        else:
            total = len(self._tasks)
            done = sum(1 for _, s, *_ in self._tasks if s is TaskStatus.COMPLETED)
            pct = done * 100 // total if total else 0
            parts = [f"{done}/{total} ({pct}%)"]
        fail = sum(1 for _, s, *_ in self._tasks if s is TaskStatus.FAILED)
        run = sum(1 for _, s, *_ in self._tasks if s is TaskStatus.RUNNING)
        if run:
            parts.append(f"{run} running")
        if fail:
            parts.append(f"{fail} failed")
        lines.append(f"  {', '.join(parts)}  {self._phase}")

        # erase old panel, draw new
        if self._panel_lines > 0:
            sys.stdout.write(f"\033[{self._panel_lines}A")
        self._panel_lines = len(lines)
        for line in lines:
            sys.stdout.write(f"\033[K{line}\n")
        sys.stdout.flush()

    def _print_change(self, msg: str) -> None:
        """print a change line above the panel"""
        if self._panel_lines > 0:
            sys.stdout.write(f"\033[{self._panel_lines}A")
            sys.stdout.write(f"\033[K{msg}\n")
            for _ in range(self._panel_lines):
                sys.stdout.write("\n")
            sys.stdout.write(f"\033[{self._panel_lines}A")
        else:
            sys.stdout.write(f"{msg}\n")
        sys.stdout.flush()

    def event(self, msg: str, min_level: int = 1) -> None:
        """print a log line above the panel"""
        if self.verbosity < min_level:
            return
        if self.is_tty and self._panel_lines > 0:
            sys.stdout.write(f"\033[{self._panel_lines}A")
            sys.stdout.write(f"\033[K{msg}\n")
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
        """clear the panel"""
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
        self._worker_progress.clear()

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
