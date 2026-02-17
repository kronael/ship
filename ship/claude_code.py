from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path


class ClaudeError(RuntimeError):
    """claude CLI failure with optional session context"""
    def __init__(self, message: str, session_id: str = ""):
        super().__init__(message)
        self.session_id = session_id


class ClaudeCodeClient:
    """client for calling claude code CLI

    spawns claude CLI subprocess and handles communication
    spawns claude CLI subprocess and returns (output, session_id)

    session reuse: pass session_id to continue conversations.
    first call creates the session, subsequent calls resume it.
    """

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

    def _build_args(self, prompt: str) -> list[str]:
        """build claude CLI arguments"""
        args = [
            "claude",
            "-p",
            prompt,
            "--model",
            self.model,
            "--permission-mode",
            self.permission_mode,
        ]
        if self.session_id:
            if self._session_started:
                args.extend(["--resume", self.session_id])
            else:
                args.extend(["--session-id", self.session_id])
        if self.max_turns is not None:
            args.extend(["--max-turns", str(self.max_turns)])
        if self.allowed_tools:
            args.extend(["--allowedTools", " ".join(self.allowed_tools)])
        return args

    async def execute(
        self, prompt: str, timeout: int = 120
    ) -> tuple[str, str]:
        """execute prompt via claude code CLI

        spawns: claude -p <prompt> --model <model> [--max-turns N]
        runs in: self.cwd
        timeout: seconds (default 120)

        returns: (stdout, session_id) tuple
        raises: ClaudeError on failure or timeout
        """
        args = self._build_args(prompt)
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=self.cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._proc = proc

        sid = self.session_id or ""

        try:
            async with asyncio.timeout(timeout):
                stdout, stderr = await proc.communicate()
        except TimeoutError:
            await self._kill_proc(proc)
            self._trace(len(prompt), 0, timeout, False)
            raise ClaudeError(
                f"claude CLI timeout after {timeout}s",
                session_id=sid,
            )
        except asyncio.CancelledError:
            await self._kill_proc(proc)
            raise
        finally:
            self._proc = None

        if proc.returncode != 0:
            error = (
                stderr.decode().strip()
                or stdout.decode().strip()
            )
            if "already in use" in error:
                logging.warning(
                    "session collision, retrying with"
                    " fresh session_id"
                )
                self.session_id = str(uuid.uuid4())
                self._session_started = False
                return await self.execute(prompt, timeout)
            self._trace(len(prompt), 0, timeout, False)
            raise ClaudeError(
                f"claude CLI failed: {error}",
                session_id=sid,
            )

        output = stdout.decode().strip()
        if not output:
            raise ClaudeError(
                "claude CLI returned empty output",
                session_id=sid,
            )

        if self.session_id:
            self._session_started = True
        self._trace(len(prompt), len(output), timeout, True)
        return output, sid

    async def _kill_proc(
        self, proc: asyncio.subprocess.Process
    ) -> None:
        """kill subprocess and wait for exit"""
        try:
            proc.kill()
            await proc.wait()
        except Exception as e:
            logging.warning(
                f"error cleaning up process: {e}"
            )

    def _trace(
        self,
        prompt_len: int,
        response_len: int,
        duration_ms: int,
        ok: bool,
    ) -> None:
        """append trace entry to .ship/log/trace.jl"""
        trace_path = Path(".ship/log/trace.jl")
        try:
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": datetime.now(timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%S"),
                "role": self.role,
                "model": self.model,
                "prompt_len": prompt_len,
                "response_len": response_len,
                "duration_ms": duration_ms,
                "ok": ok,
            }
            with open(trace_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass
