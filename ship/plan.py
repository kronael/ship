"""interactive plan mode - real claude sessions per phase

each phase launches an interactive claude session via fork+exec.
state accumulates in .ship/plan/. user confirms between phases.
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path

import click

from ship.claude_code import ClaudeCodeClient
from ship.prompts import (
    PLAN_DECOMPOSE,
    PLAN_PHASES,
    PLAN_RESEARCH,
    PLAN_SIMPLIFY,
    PLAN_SPEC,
    PLAN_UNDERSTAND,
)

PLAN_DIR = Path(".ship/plan")

# (name, description, output_file or None, interactive)
PHASES = [
    ("understand", "understand the problem", "summary", True),
    ("research", "research the tech", "research", True),
    ("simplify", "simplify ruthlessly", "simplified", True),
    ("decompose", "decompose into components", "components", True),
    ("spec", "write component specs", None, False),
    ("phases", "define implementation phases", None, False),
]


def _load(name: str) -> str:
    p = PLAN_DIR / f"{name}.md"
    return p.read_text() if p.exists() else ""


def _banner(phase: str, desc: str) -> None:
    click.echo(f"\n{'─' * 60}")
    click.echo(f"  {phase}: {desc}")
    click.echo(f"{'─' * 60}\n")


def _confirm(msg: str) -> bool:
    try:
        return click.confirm(msg)
    except (click.Abort, EOFError):
        click.echo("\ninterrupted")
        sys.exit(130)


def _build_phase_prompt(name: str, context: tuple[str, ...]) -> str:
    """build system prompt for a phase, baking in previous outputs"""
    ctx = ""
    if context:
        ctx = "User provided context:\n" + " ".join(context)

    summary = _load("summary")
    research = _load("research")
    simplified = _load("simplified")
    components = _load("components")

    prev = ""
    if summary:
        prev += f"\n\n## previous: summary\n{summary}"
    if research:
        prev += f"\n\n## previous: research\n{research}"
    if simplified:
        prev += f"\n\n## previous: simplified scope\n{simplified}"
    if components:
        prev += f"\n\n## previous: components\n{components}"

    output_dir = f"write your output to .ship/plan/{name}.md"

    prompts = {
        "understand": PLAN_UNDERSTAND.format(context_section=ctx),
        "research": PLAN_RESEARCH.format(summary=summary or "(not yet written)"),
        "simplify": PLAN_SIMPLIFY.format(
            summary=summary or "(not yet written)",
            research=research or "(not yet written)",
        ),
        "decompose": PLAN_DECOMPOSE.format(
            summary=summary or "(not yet written)",
            research=research or "(not yet written)",
            simplified=simplified or "(not yet written)",
        ),
    }

    base = prompts.get(name, "")
    return (
        f"{base}\n\n{output_dir}\n\n"
        f"Interview the user. Push back on vague answers. "
        f"Don't write the output file until you're satisfied "
        f"the answers are specific enough."
        f"{prev}"
    )


def _launch_claude(
    system_prompt: str,
    session_id: str,
    resume: bool = False,
) -> None:
    """launch interactive claude session, block until it exits"""
    pid = os.fork()
    if pid == 0:
        args = [
            "claude",
            "--append-system-prompt",
            system_prompt,
        ]
        if resume:
            args.extend(["--resume", session_id])
        else:
            args.extend(["--session-id", session_id])
        os.execvp("claude", args)
    else:
        _, status = os.waitpid(pid, 0)
        if os.WIFSIGNALED(status):
            sig = os.WTERMSIG(status)
            if sig in (2, 15):
                click.echo("\nsession ended")


def _make_noninteractive_client(
    session_id: str | None = None,
) -> ClaudeCodeClient:
    return ClaudeCodeClient(
        model="sonnet",
        role="planner",
        session_id=session_id,
    )


def _show_phase_summary(name: str) -> None:
    content = _load(name)
    if content:
        # show first 20 lines
        lines = content.strip().splitlines()
        preview = "\n".join(lines[:20])
        if len(lines) > 20:
            preview += f"\n... ({len(lines) - 20} more lines)"
        click.echo(f"\n{name} output:\n{preview}")
    else:
        click.echo(f"\nno output file for {name}")


async def _run_spec_phase(
    context: tuple[str, ...],
    client: ClaudeCodeClient,
) -> list[str]:
    """phase 5: write component specs (non-interactive)"""
    summary = _load("summary")
    research = _load("research")
    simplified = _load("simplified")
    components = _load("components")

    comp_names = re.findall(r"name:\s*(.+)", components)
    if not comp_names:
        comp_names = ["main"]

    click.echo(f"components to spec: {', '.join(comp_names)}")

    spec_files: list[str] = []
    for comp_name in comp_names:
        comp_name = comp_name.strip()
        click.echo(f"\n  writing spec for: {comp_name}")

        comp_detail = ""
        comp_match = re.search(
            rf"<component>\s*name:\s*{re.escape(comp_name)}"
            r"(.*?)</component>",
            components,
            re.DOTALL,
        )
        if comp_match:
            comp_detail = comp_match.group(0)

        if len(comp_names) == 1:
            spec_path = "SPEC.md"
        else:
            Path("specs").mkdir(exist_ok=True)
            spec_path = f"specs/{comp_name}.md"

        prompt = PLAN_SPEC.format(
            summary=summary,
            research=research,
            simplified=simplified,
            components=components,
            component_name=comp_name,
            component_detail=comp_detail,
            spec_path=spec_path,
        )
        await client.execute(prompt, timeout=180)  # returns tuple, ignore
        click.echo(f"  wrote {spec_path}")
        spec_files.append(spec_path)

    return spec_files


async def _run_phases_phase(
    spec_files: list[str],
    client: ClaudeCodeClient,
) -> None:
    """phase 6: define implementation phases (non-interactive)"""
    summary = _load("summary")
    components = _load("components")

    prompt = PLAN_PHASES.format(
        summary=summary,
        components=components,
        spec_files=", ".join(spec_files),
    )
    response, _ = await client.execute(prompt, timeout=120)
    click.echo(f"\n{response}")


async def run_plan(context: tuple[str, ...]) -> None:
    """run the interactive planning loop"""
    PLAN_DIR.mkdir(parents=True, exist_ok=True)

    # one session per interactive phase, reused on retry
    # one shared session for non-interactive phases
    gen_session = str(uuid.uuid4())
    gen_client = _make_noninteractive_client(gen_session)

    # phases 1-4: interactive claude sessions
    interactive_phases = [p for p in PHASES if p[3]]
    for i, (name, desc, output_file, _) in enumerate(interactive_phases):
        _banner(f"phase {i + 1}/{len(PHASES)}", desc)

        session_id = str(uuid.uuid4())
        launched = False

        while True:
            prompt = _build_phase_prompt(name, context)
            _launch_claude(
                prompt,
                session_id,
                resume=launched,
            )
            launched = True

            if output_file and not (PLAN_DIR / f"{output_file}.md").exists():
                click.echo(f"warning: .ship/plan/{output_file}.md not written yet")

            _show_phase_summary(output_file if output_file else name)

            if _confirm("continue to next phase?"):
                break
            # re-launch same phase, resuming session

    # phase 5: write specs (non-interactive, shared session)
    _banner(f"phase 5/{len(PHASES)}", "write component specs")
    spec_files = await _run_spec_phase(context, gen_client)

    if not _confirm("specs look good?"):
        click.echo("edit spec files and re-run ship -p")
        return

    # phase 6: implementation phases (non-interactive, same session)
    _banner(
        f"phase 6/{len(PHASES)}",
        "define implementation phases",
    )
    await _run_phases_phase(spec_files, gen_client)

    click.echo(f"\n{'─' * 60}")
    click.echo("  planning complete")
    click.echo(f"{'─' * 60}")
    click.echo(f"\nspec files: {', '.join(spec_files)}")
    click.echo("run `ship` to execute from specs")
