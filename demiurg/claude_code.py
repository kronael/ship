from __future__ import annotations

import asyncio


class ClaudeCodeClient:
    """client for calling claude code CLI"""

    def __init__(self, model: str = "sonnet", cwd: str = "."):
        self.model = model
        self.cwd = cwd

    async def execute(
        self, prompt: str, timeout: int = 120
    ) -> str:
        """execute prompt via claude code CLI

        spawns: claude -p <prompt> --model <model>
        runs in: self.cwd
        timeout: seconds (default 120)

        returns: stdout from claude CLI
        raises: RuntimeError on failure or timeout
        """
        proc = await asyncio.create_subprocess_exec(
            "claude",
            "-p",
            prompt,
            "--model",
            self.model,
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
            except Exception:
                pass
            raise RuntimeError(f"claude CLI timeout after {timeout}s")

        if proc.returncode != 0:
            error = stderr.decode().strip() or stdout.decode().strip()
            raise RuntimeError(f"claude CLI failed: {error}")

        output = stdout.decode().strip()
        if not output:
            raise RuntimeError("claude CLI returned empty output")

        return output
