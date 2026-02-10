from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path


class CodexClient:
    """client for calling Codex CLI non-interactively"""

    def __init__(
        self,
        model: str | None = None,
        cwd: str = ".",
        sandbox: str = "read-only",
    ):
        self.model = model
        self.cwd = cwd
        self.sandbox = sandbox
        self.binary = self._find_codex()

    def _find_codex(self) -> str:
        """locate codex CLI binary (PATH or bun default)"""
        found = shutil.which("codex")
        if found:
            return found

        bun_path = Path.home() / ".bun" / "bin" / "codex"
        if bun_path.exists():
            return str(bun_path)

        raise RuntimeError(
            "codex CLI not found (expected in PATH or ~/.bun/bin/codex)"
        )

    def _build_args(self, output_path: str) -> list[str]:
        """build codex CLI arguments"""
        args = [
            self.binary,
            "exec",
            "--output-last-message",
            output_path,
            "--sandbox",
            self.sandbox,
        ]
        if self.model:
            args.extend(["--model", self.model])
        return args

    async def execute(self, prompt: str, timeout: int = 120) -> str:
        """execute prompt via codex CLI

        runs: codex exec --output-last-message <file> --sandbox <mode>
        uses: stdin for prompt
        returns: final message from codex agent
        """
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.close()
        output_path = tmp.name

        args = self._build_args(output_path)
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=self.cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            async with asyncio.timeout(timeout):
                stdout, stderr = await proc.communicate(input=prompt.encode())
        except TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception as e:
                logging.warning(f"error cleaning up process after timeout: {e}")
            raise RuntimeError(f"codex CLI timeout after {timeout}s")

        try:
            output_text = Path(output_path).read_text().strip()
        except OSError:
            output_text = ""
        finally:
            try:
                Path(output_path).unlink(missing_ok=True)
            except OSError:
                pass

        if proc.returncode != 0:
            error = stderr.decode().strip() or stdout.decode().strip()
            raise RuntimeError(f"codex CLI failed: {error}")

        if not output_text:
            output_text = stdout.decode().strip()

        if not output_text:
            raise RuntimeError("codex CLI returned empty output")

        return output_text
