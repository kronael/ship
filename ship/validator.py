from __future__ import annotations

import re
from dataclasses import dataclass

from ship.claude_code import ClaudeCodeClient
from ship.prompts import VALIDATOR


@dataclass(slots=True)
class ValidationResult:
    accept: bool
    gaps: list[str]
    project_md: str


class Validator:
    """validate design/spec quality before planning"""

    def __init__(
        self,
        verbosity: int = 1,
        session_id: str | None = None,
    ):
        self.verbosity = verbosity
        self.claude = ClaudeCodeClient(
            model="sonnet",
            role="validator",
            session_id=session_id,
        )

    async def validate(
        self,
        design_text: str,
        context: list[str] | None = None,
    ) -> ValidationResult:
        context_section = ""
        if context:
            joined = "\n".join(f"- {c}" for c in context)
            context_section = f"\nAdditional context:\n{joined}\n"
        prompt = VALIDATOR.format(
            design_text=design_text,
            context_section=context_section,
        )

        if self.verbosity >= 3:
            print(f"\n{'=' * 60}")
            print("VALIDATOR PROMPT:")
            print(f"{'=' * 60}")
            print(prompt)
            print(f"{'=' * 60}\n")

        result, _ = await self.claude.execute(
            prompt, timeout=180
        )

        if self.verbosity >= 3:
            print(f"\n{'=' * 60}")
            print("VALIDATOR RESPONSE:")
            print(f"{'=' * 60}")
            print(result)
            print(f"{'=' * 60}\n")

        return self._parse(result)

    def _parse(self, text: str) -> ValidationResult:
        decision_match = re.search(r"<decision>(.*?)</decision>", text, re.DOTALL)
        decision = decision_match.group(1).strip().lower() if decision_match else ""
        accept = decision == "accept"

        gaps = []
        for m in re.findall(r"<gap>(.*?)</gap>", text, re.DOTALL):
            gap = m.strip()
            if gap:
                gaps.append(gap)

        project_match = re.search(r"<project>(.*?)</project>", text, re.DOTALL)
        project_md = project_match.group(1).strip() if project_match else ""

        return ValidationResult(accept=accept, gaps=gaps, project_md=project_md)
