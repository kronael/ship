from __future__ import annotations

import sys
from datetime import datetime


class Display:
    """tui display with rewriting status line

    when stdout is a tty, the bottom line rewrites in place (like wget).
    events print above the status line as permanent log entries.
    when not a tty, falls back to plain print.
    """

    def __init__(self):
        self.is_tty = sys.stdout.isatty()
        self._status = ""
        self._status_len = 0

    def event(self, msg: str) -> None:
        """print a permanent log line above the status line"""
        if self.is_tty and self._status:
            sys.stdout.write(f"\r\033[K{msg}\n")
            sys.stdout.write(f"\r\033[K{self._status}")
            sys.stdout.flush()
        else:
            print(msg)

    def status(self, msg: str) -> None:
        """rewrite the status line in place (tty only)"""
        self._status = msg
        if self.is_tty:
            try:
                import shutil
                cols = shutil.get_terminal_size().columns
                if len(msg) > cols:
                    msg = msg[:cols - 1]
            except Exception:
                pass
            sys.stdout.write(f"\r\033[K{msg}")
            sys.stdout.flush()
        else:
            print(msg)

    def clear_status(self) -> None:
        """clear the status line"""
        self._status = ""
        if self.is_tty:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()

    def banner(self, msg: str) -> None:
        """print a line that's always visible (bypasses status)"""
        if self.is_tty and self._status:
            sys.stdout.write(f"\r\033[K{msg}\n")
            sys.stdout.write(f"\r\033[K{self._status}")
            sys.stdout.flush()
        else:
            print(msg)


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
    bar = "█" * filled + "░" * (bar_len - filled)

    lines = [
        "# PROGRESS",
        "",
        f"updated: {now}  ",
        f"phase: {phase}",
        "",
        f"```",
        f"[{bar}] {pct:.0f}%  {completed}/{total}",
        f"```",
        "",
        f"| | count |",
        f"|---|---|",
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
