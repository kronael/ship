"""Smoke tests — hit real claude CLI. Run via `make smoke`."""

from __future__ import annotations

import subprocess

import pytest

from ship.claude_code import ClaudeCodeClient
from ship.config import Config
from ship.state import StateManager
from ship.worker import Worker


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_worker_roundtrip(tmp_path):
    # init a git repo so _git_head / _git_diff_stat work
    subprocess.run(
        ["git", "init"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    # seed commit so HEAD exists
    seed = tmp_path / "seed.txt"
    seed.write_text("seed")
    subprocess.run(
        ["git", "add", "seed.txt"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )

    cfg = Config(
        num_workers=1,
        log_dir=str(tmp_path / ".ship" / "log"),
        data_dir=str(tmp_path / ".ship"),
        max_turns=3,
        task_timeout=60,
        verbosity=1,
        use_codex=False,
    )
    state = StateManager(str(tmp_path))
    w = Worker("smoke-0", cfg, state)
    w.claude = ClaudeCodeClient(
        model="sonnet",
        cwd=str(tmp_path),
        max_turns=3,
        role="smoke-test",
    )

    progress: list[str] = []

    prompt = (
        "Create a file called hello.txt containing "
        "'hello world'. Then output exactly:\n"
        "<progress>created hello.txt</progress>\n"
        "<status>done</status>"
    )
    result, sid = await w.claude.execute(
        prompt,
        timeout=60,
        on_progress=lambda msg: progress.append(msg),
    )

    assert result, "expected non-empty result"
    hello_path = tmp_path / "hello.txt"
    has_hello = hello_path.exists() or "hello" in result
    assert has_hello, "hello.txt not created and not in output"
    assert len(progress) >= 1, "expected at least one progress"

    head = await w._git_head()
    if head:
        await w._git_diff_stat(head)
        # may be empty if claude committed, that's ok
