from __future__ import annotations

import asyncio
import json
import os
import re
import signal
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path


class ClaudeError(RuntimeError):
    def __init__(self, msg: str, partial: str = "", session_id: str = ""):
        super().__init__(msg)
        self.partial = partial
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
    ):
        self.model = model
        self.cwd = cwd
        self.permission_mode = permission_mode
        self.max_turns = max_turns
        self.allowed_tools = allowed_tools or self.DEFAULT_ALLOWED_TOOLS
        self.role = role
        self._proc: asyncio.subprocess.Process | None = None

    async def execute(
        self,
        prompt: str,
        timeout: int = 120,
        on_progress: Callable[[str], None] | None = None,
    ) -> tuple[str, str]:
        """returns (output, session_id); raises ClaudeError on failure/timeout"""
        args = [
            "claude",
            "-p",
            prompt,
            "--model",
            self.model,
            "--permission-mode",
            self.permission_mode,
            "--output-format",
            "stream-json",
            "--verbose",
            "--no-session-persistence",
        ]
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
            limit=16 * 1024 * 1024,  # 16MB, stream-json lines can be large
        )
        self._proc = proc

        result_text = ""
        session_id = ""
        subtype = ""
        try:
            async with asyncio.timeout(timeout):
                assert proc.stdout is not None
                assert proc.stderr is not None
                async for raw in proc.stdout:
                    line = raw.decode().strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    etype = event.get("type", "")
                    if etype == "assistant" and on_progress:
                        msg = event.get("message", {})
                        for block in msg.get("content", []):
                            if block.get("type") == "text":
                                text = block.get("text", "")
                                for m in re.finditer(
                                    r"<progress>(.*?)</progress>",
                                    text,
                                ):
                                    on_progress(m.group(1).strip())
                    elif etype == "result":
                        result_text = event.get("result", "")
                        session_id = event.get("session_id", "")
                        subtype = event.get("subtype", "")
                stderr_bytes = await proc.stderr.read()
                await proc.wait()
        except asyncio.CancelledError:
            await self._kill_proc(proc)
            raise
        except TimeoutError:
            await self._kill_proc(proc)
            self._trace(
                len(prompt),
                len(result_text),
                timeout,
                False,
                prompt=prompt,
                response=result_text,
            )
            raise ClaudeError(
                f"claude CLI timeout after {timeout}s",
                partial=result_text,
                session_id=session_id,
            )
        finally:
            self._proc = None

        if proc.returncode != 0:
            stderr_text = stderr_bytes.decode().strip()
            error = stderr_text or result_text or f"exit {proc.returncode}"
            self._trace(
                len(prompt),
                0,
                timeout,
                False,
                prompt=prompt,
                response=result_text,
            )
            raise ClaudeError(
                f"claude CLI failed (exit {proc.returncode}): {error}",
                partial=result_text,
                session_id=session_id,
            )

        if not result_text:
            raise ClaudeError(
                "claude CLI returned empty output",
                session_id=session_id,
            )

        if subtype == "error_max_turns":
            raise ClaudeError(
                "reached max turns",
                partial=result_text,
                session_id=session_id,
            )

        self._trace(
            len(prompt),
            len(result_text),
            timeout,
            True,
            prompt=prompt,
            response=result_text,
        )
        return result_text, session_id

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

    def _trace(
        self,
        prompt_len: int,
        response_len: int,
        timeout: int,
        ok: bool,
        prompt: str = "",
        response: str = "",
    ) -> None:
        trace_path = Path(".ship/log/trace.jl")
        try:
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                "role": self.role,
                "model": self.model,
                "prompt_len": prompt_len,
                "response_len": response_len,
                "timeout": timeout,
                "ok": ok,
                "prompt": prompt,
                "response": response,
            }
            with open(trace_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass
