from __future__ import annotations

import logging
from pathlib import Path


def load_skills(skills_dir: Path | None = None) -> dict[str, str]:
    """load skill definitions from ~/.claude/skills/

    returns dict of skill_name -> skill_content
    """
    if skills_dir is None:
        skills_dir = Path.home() / ".claude" / "skills"

    if not skills_dir.exists():
        return {}

    skills = {}
    for skill_file in skills_dir.glob("*"):
        if skill_file.is_dir():
            # skill in subdirectory - look for SKILL.md or skill.md
            for md_file in ["SKILL.md", "skill.md", "README.md"]:
                md_path = skill_file / md_file
                if md_path.exists():
                    try:
                        content = md_path.read_text().strip()
                        skills[skill_file.name] = content
                        logging.debug(f"loaded skill: {skill_file.name}")
                    except OSError as e:
                        logging.warning(f"failed to read skill {skill_file.name}: {e}")
                    break
        elif skill_file.suffix in (".md", ".txt"):
            # skill as single file
            try:
                content = skill_file.read_text().strip()
                skills[skill_file.stem] = content
                logging.debug(f"loaded skill: {skill_file.stem}")
            except OSError as e:
                logging.warning(f"failed to read skill {skill_file.stem}: {e}")

    return skills


def format_skills_for_prompt(
    skills: dict[str, str], relevant: list[str] | None = None
) -> str:
    """format skills as prompt context

    if relevant is provided, only include those skills
    otherwise include all
    """
    if not skills:
        return ""

    if relevant:
        skills = {k: v for k, v in skills.items() if k in relevant}

    if not skills:
        return ""

    parts = ["Available skills and patterns:\n"]
    for name, content in skills.items():
        # truncate long skills
        if len(content) > 1000:
            content = content[:1000] + "\n... (truncated)"
        parts.append(f"### /{name}\n{content}\n")

    return "\n".join(parts)
