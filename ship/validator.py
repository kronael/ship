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
    ):
        self.verbosity = verbosity
        self.claude = ClaudeCodeClient(
            model="sonnet",
            role="validator",
        )

    async def validate(
        self,
        design_text: str,
        context: list[str] | None = None,
        override_prompt: str = "",
        max_retries: int = 2,
    ) -> ValidationResult:
        context_section = ""
        if context:
            joined = "\n".join(f"- {c}" for c in context)
            context_section = f"\nAdditional context:\n{joined}\n"
        override_section = (
            f"\nOverride instructions: {override_prompt}\n" if override_prompt else ""
        )
        prompt = override_section + VALIDATOR.format(
            design_text=design_text,
            context_section=context_section,
        )

        for attempt in range(1 + max_retries):
            if self.verbosity >= 3:
                sep = "=" * 60
                print(f"\n{sep}\nVALIDATOR PROMPT:\n{sep}\n{prompt}\n{sep}\n")

            result, _ = await self.claude.execute(prompt, timeout=180)

            if self.verbosity >= 3:
                sep = "=" * 60
                print(f"\n{sep}\nVALIDATOR RESPONSE:\n{sep}\n{result}\n{sep}\n")

            parsed = self._parse(result)
            # retry if rejected without gaps (LLM failed to explain)
            if not parsed.accept and not parsed.gaps:
                if attempt < max_retries:
                    if self.verbosity >= 1:
                        print("warning: validator rejected without gaps, retrying...")
                    continue
            return parsed

        # exhausted retries, return last result with fallback gap
        return parsed

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

        # fallback: rejection without proper <gap> tags
        if not accept and not gaps:
            gaps_block = re.search(r"<gaps>(.*?)</gaps>", text, re.DOTALL)
            if gaps_block:
                for line in gaps_block.group(1).strip().splitlines():
                    line = line.strip().strip("-*\u2022 ")
                    if line:
                        gaps.append(line)
            if not gaps:
                gaps.append("rejected without explanation (LLM parse failure)")

        return ValidationResult(accept=accept, gaps=gaps, project_md=project_md)
