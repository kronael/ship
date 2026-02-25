from __future__ import annotations

import asyncio
import json
import logging
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
            self._trace(len(prompt), len(result_text), timeout, False)
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
            self._trace(len(prompt), 0, timeout, False)
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

        self._trace(len(prompt), len(result_text), timeout, True)
        return result_text, session_id

    async def _resume(self, session_id: str, prompt: str) -> str:
        """resume a session with a follow-up prompt, return result text"""
        args = [
            "claude",
            "--resume",
            session_id,
            "-p",
            prompt,
            "--model",
            self.model,
            "--permission-mode",
            self.permission_mode,
            "--output-format",
            "json",
        ]
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=self.cwd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        async with asyncio.timeout(60):
            out, _ = await proc.communicate()
        raw = out.decode().strip()
        try:
            return json.loads(raw).get("result", raw)
        except json.JSONDecodeError:
            return raw

    async def summarize(self, session_id: str, partial: str = "") -> str:
        """resume an interrupted session and extract a progress summary"""
        context = f"\n\nYour partial output:\n{partial[:600]}" if partial else ""
        prompt = (
            f"You were interrupted before finishing your task.{context}\n\n"
            "Summarize in 3-5 lines:\n"
            "1. What you completed\n"
            "2. What remains\n"
            "3. Any errors or blockers\n\n"
            "Then output:\n"
            "<status>partial</status>\n"
            "<followups>\n"
            "<task>description of remaining work</task>\n"
            "</followups>"
        )
        try:
            return await self._resume(session_id, prompt)
        except Exception as e:
            logging.warning(f"summarize failed: {e}")
            return partial or "interrupted (no summary available)"

    async def reformat(self, session_id: str) -> str:
        """resume session and request only the structured XML output tags"""
        prompt = (
            "Your previous response is complete. "
            "Now emit ONLY the required structured tags — nothing else:\n\n"
            "If the work is done:\n"
            "<summary>3-5 word outcome</summary>\n"
            "<status>done</status>\n\n"
            "If work was incomplete:\n"
            "<summary>3-5 word outcome</summary>\n"
            "<status>partial</status>\n"
            "<followups>\n<task>remaining work description</task>\n</followups>"
        )
        try:
            return await self._resume(session_id, prompt)
        except Exception as e:
            logging.warning(f"reformat failed: {e}")
            return ""

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
        self, prompt_len: int, response_len: int, timeout: int, ok: bool
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
            }
            with open(trace_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass
