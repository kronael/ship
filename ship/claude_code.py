from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path


class ClaudeError(RuntimeError):
    def __init__(self, message: str, session_id: str = ""):
        super().__init__(message)
        self.session_id = session_id


class ClaudeCodeClient:
    """claude CLI wrapper; returns (output, session_id)"""

    # common dev tools to allow in sandbox
    DEFAULT_ALLOWED_TOOLS = [
        "Bash(make:*)",
        "Bash(go:*)",
        "Bash(npm:*)",
        "Bash(npx:*)",
        "Bash(node:*)",
        "Bash(python:*)",
        "Bash(python3:*)",
        "Bash(uv:*)",
        "Bash(pytest:*)",
        "Bash(cargo:*)",
        "Bash(rustc:*)",
        "Bash(grep:*)",
        "Bash(sed:*)",
        "Bash(awk:*)",
        "Bash(find:*)",
        "Bash(cat:*)",
        "Bash(head:*)",
        "Bash(tail:*)",
        "Bash(ls:*)",
        "Bash(mkdir:*)",
        "Bash(rm:*)",
        "Bash(cp:*)",
        "Bash(mv:*)",
        "Bash(chmod:*)",
        "Bash(git:*)",
        "Bash(curl:*)",
        "Bash(tar:*)",
        "Bash(unzip:*)",
        "Read",
        "Write",
        "Edit",
        "Glob",
        "Grep",
    ]

    def __init__(
        self,
        model: str = "sonnet",
        cwd: str = ".",
        permission_mode: str = "bypassPermissions",
        max_turns: int | None = None,
        allowed_tools: list[str] | None = None,
        role: str = "unknown",
        session_id: str | None = None,
    ):
        self.model = model
        self.cwd = cwd
        self.permission_mode = permission_mode
        self.max_turns = max_turns
        self.allowed_tools = allowed_tools or self.DEFAULT_ALLOWED_TOOLS
        self.role = role
        self.session_id = session_id
        self._session_started = False
        self._proc: asyncio.subprocess.Process | None = None

    async def execute(
        self,
        prompt: str,
        timeout: int = 120,
        on_progress: Callable[[str], None] | None = None,
    ) -> tuple[str, str]:
        """returns (stdout, session_id); raises ClaudeError on failure/timeout"""
        args = [
            "claude", "-p", prompt,
            "--model", self.model,
            "--permission-mode", self.permission_mode,
        ]
        if self.session_id and self._session_started:
            args.extend(["--resume", self.session_id])
        if self.max_turns is not None:
            args.extend(["--max-turns", str(self.max_turns)])
        if self.allowed_tools:
            args.extend(["--allowedTools", " ".join(self.allowed_tools)])
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=self.cwd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        self._proc = proc

        sid = self.session_id or ""

        try:
            lines: list[str] = []
            async with asyncio.timeout(timeout):
                assert proc.stdout is not None
                assert proc.stderr is not None
                async for raw in proc.stdout:
                    line = raw.decode()
                    lines.append(line)
                    if on_progress:
                        m = re.search(
                            r"<progress>(.*?)</progress>",
                            line,
                        )
                        if m:
                            on_progress(m.group(1).strip())
                stderr_bytes = await proc.stderr.read()
                await proc.wait()
        except asyncio.CancelledError:
            await self._kill_proc(proc)
            raise
        except TimeoutError:
            await self._kill_proc(proc)
            self._trace(len(prompt), 0, timeout, False)
            raise ClaudeError(
                f"claude CLI timeout after {timeout}s",
                session_id=sid,
            )
        finally:
            self._proc = None

        output = "".join(lines).strip()

        if proc.returncode != 0:
            error = stderr_bytes.decode().strip() or output
            if "already in use" in error:
                logging.warning(
                    "session collision, retrying with fresh session_id"
                )
                self.session_id = str(uuid.uuid4())
                self._session_started = False
                return await self.execute(
                    prompt, timeout, on_progress
                )
            self._trace(len(prompt), 0, timeout, False)
            raise ClaudeError(
                f"claude CLI failed: {error}",
                session_id=sid,
            )

        if not output:
            raise ClaudeError(
                "claude CLI returned empty output",
                session_id=sid,
            )

        if self.session_id:
            self._session_started = True
        self._trace(len(prompt), len(output), timeout, True)
        return output, sid

    @staticmethod
    async def _kill_proc(proc: asyncio.subprocess.Process) -> None:
        """SIGTERM the process group, SIGKILL after 10s"""
        if proc.returncode is not None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass

    def _trace(self, prompt_len: int, response_len: int, timeout: int, ok: bool) -> None:
        trace_path = Path(".ship/log/trace.jl")
        try:
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S"
                ),
                "role": self.role,
                "model": self.model,
                "prompt_len": prompt_len,
                "response_len": response_len,
                "timeout": timeout,
                "ok": ok,
            }
            with open(trace_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass
