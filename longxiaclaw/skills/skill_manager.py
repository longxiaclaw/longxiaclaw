"""Skill discovery, parsing, and management."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger("longxiaclaw")


@dataclass
class Skill:
    name: str
    description: str
    version: str
    triggers: list[str]  # Empty = prompt-only skill (always loaded)
    enabled: bool
    author: str
    body: str  # Markdown body (instructions)
    file_path: Path = field(default_factory=lambda: Path("."))

    @property
    def is_tool_skill(self) -> bool:
        """Skills with triggers have daemon-side tool implementations."""
        return len(self.triggers) > 0


# Regex to match YAML frontmatter between --- markers
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class SkillManager:
    """Loads skills from disk and provides lookup/matching."""

    def __init__(self, skills_dir: Path):
        self._skills_dir = skills_dir
        self._skills: list[Skill] = []
        self.reload()

    def reload(self) -> None:
        """Scan skills directory and load all enabled skills."""
        if not self._skills_dir.exists():
            logger.warning("Skills directory not found: %s", self._skills_dir)
            self._skills = []
            return

        skills = []
        for path in sorted(self._skills_dir.glob("*.md")):
            if path.name.startswith("_"):
                continue
            try:
                skill = self._load_skill(path)
                if skill.enabled:
                    skills.append(skill)
                    logger.info("Skill loaded: %s (%s)", skill.name,
                                "tool" if skill.is_tool_skill else "prompt")
                else:
                    logger.info("Skill skipped (disabled): %s", path.name)
            except (ValueError, yaml.YAMLError, KeyError) as e:
                logger.warning("Failed to load skill %s: %s", path.name, e)
                continue
        self._skills = skills

    def _load_skill(self, path: Path) -> Skill:
        """Parse YAML frontmatter (between --- markers) + body."""
        content = path.read_text(encoding="utf-8")

        match = _FRONTMATTER_RE.match(content)
        if not match:
            raise ValueError(f"No valid YAML frontmatter in {path}")

        frontmatter_text = match.group(1)
        body = content[match.end():].strip()

        meta = yaml.safe_load(frontmatter_text)
        if not isinstance(meta, dict):
            raise ValueError(f"Invalid frontmatter in {path}")

        return Skill(
            name=meta.get("name", path.stem),
            description=meta.get("description", ""),
            version=str(meta.get("version", "1.0")),
            triggers=meta.get("triggers", []),
            enabled=meta.get("enabled", True),
            author=meta.get("author", ""),
            body=body,
            file_path=path,
        )

    def get_active_skills(self) -> list[Skill]:
        """Return all enabled skills."""
        return list(self._skills)

    def get_skill(self, name: str) -> Optional[Skill]:
        """Look up a skill by name."""
        for skill in self._skills:
            if skill.name == name:
                return skill
        return None

    def get_triggered_skills(self, message: str) -> list[Skill]:
        """Return tool skills whose triggers match the message."""
        message_lower = message.lower()
        matched = []
        for skill in self._skills:
            if not skill.is_tool_skill:
                continue
            for trigger in skill.triggers:
                if trigger.lower() in message_lower:
                    matched.append(skill)
                    break
        return matched

    def get_prompt_skills(self) -> list[Skill]:
        """Return prompt-only skills (no triggers, always loaded)."""
        return [s for s in self._skills if not s.is_tool_skill]

    def format_skills_context(self, skills: list[Skill]) -> str:
        """Wrap each skill body in <skill name="...">...</skill> tags."""
        if not skills:
            return ""
        parts = []
        for skill in skills:
            parts.append(f'<skill name="{skill.name}">\n{skill.body}\n</skill>')
        return "\n\n".join(parts)

    @property
    def count(self) -> int:
        return len(self._skills)
