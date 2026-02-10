from __future__ import annotations

import asyncio
import logging
import sys
from typing import AsyncIterator


class ClaudeCodeClient:
    """client for calling claude code CLI

    spawns claude CLI subprocess and handles communication
    supports both buffered (execute) and streaming (execute_stream) modes
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
    ):
        self.model = model
        self.cwd = cwd
        self.permission_mode = permission_mode
        self.max_turns = max_turns
        self.allowed_tools = allowed_tools or self.DEFAULT_ALLOWED_TOOLS

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
        if self.max_turns is not None:
            args.extend(["--max-turns", str(self.max_turns)])
        if self.allowed_tools:
            args.extend(["--allowedTools", " ".join(self.allowed_tools)])
        return args

    async def execute(
        self, prompt: str, timeout: int = 120
    ) -> str:
        """execute prompt via claude code CLI

        spawns: claude -p <prompt> --model <model> [--max-turns N]
        runs in: self.cwd
        timeout: seconds (default 120)

        returns: stdout from claude CLI
        raises: RuntimeError on failure or timeout
        """
        args = self._build_args(prompt)
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=self.cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            async with asyncio.timeout(timeout):
                stdout, stderr = await proc.communicate()
        except TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception as e:
                logging.warning(f"error cleaning up process after timeout: {e}")
            raise RuntimeError(f"claude CLI timeout after {timeout}s")

        if proc.returncode != 0:
            error = stderr.decode().strip() or stdout.decode().strip()
            raise RuntimeError(f"claude CLI failed: {error}")

        output = stdout.decode().strip()
        if not output:
            raise RuntimeError("claude CLI returned empty output")

        return output

    async def execute_stream(
        self, prompt: str, timeout: int = 120
    ) -> AsyncIterator[str]:
        """execute prompt with streaming output

        yields lines from claude CLI stdout in real-time
        raises: RuntimeError on failure or timeout
        """
        args = self._build_args(prompt)
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=self.cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        output_lines = []

        try:
            async with asyncio.timeout(timeout):
                if proc.stdout is None:
                    raise RuntimeError("claude CLI stdout is None")

                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break

                    decoded = line.decode().rstrip()
                    output_lines.append(decoded)
                    yield decoded

                await proc.wait()
        except TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception as e:
                logging.warning(f"error cleaning up process after timeout: {e}")
            raise RuntimeError(f"claude CLI timeout after {timeout}s")

        if proc.returncode != 0:
            stderr_text = ""
            if proc.stderr:
                stderr_text = (await proc.stderr.read()).decode().strip()
            error = stderr_text or "\n".join(output_lines)
            raise RuntimeError(f"claude CLI failed: {error}")
