"""Load the routable catalog: skills on disk plus optional deterministic commands."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .typesafe import RouterUnavailable

# Jev accepts at most this many options in one choice question.
MAX_CHOICE_OPTIONS = 255
SKILLS_DIR_ENV = "SKILL_PICKER_SKILLS_DIR"
ACTIONS_ENV = "SKILL_PICKER_ACTIONS"
CONVENTIONAL_SKILLS_DIRS = (
    Path("~/.agents/skills"),
    Path("~/.claude/skills"),
)


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    opening: str
    kind: str = "skill"
    invocation: str | None = None


def _clean_scalar(value: str) -> str:
    return " ".join(value.split()).strip("\"'")


def _frontmatter_scalar(frontmatter: str, key: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(key)}:[ \t]*(?:[>|][-+]?)?[ \t]*(.*?)(?=^\S+:|\Z)",
        frontmatter,
    )
    return _clean_scalar(match.group(1)) if match else ""


def _frontmatter_bool(frontmatter: str, key: str, default: bool) -> bool:
    value = _frontmatter_scalar(frontmatter, key).lower()
    if not value:
        return default
    if value == "true":
        return True
    if value == "false":
        return False
    return default


def parse_skill(path: Path, opening_limit: int = 2_000) -> Skill | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None

    parts = text.split("---", 2)
    if len(parts) != 3:
        return None

    frontmatter = parts[1]
    if not _frontmatter_bool(frontmatter, "user-invocable", default=True):
        return None

    name = _frontmatter_scalar(frontmatter, "name") or path.parent.name
    description = _frontmatter_scalar(frontmatter, "description")
    if not description:
        return None

    opening = parts[2].strip()[:opening_limit]
    return Skill(
        name=name,
        description=description,
        opening=opening,
        kind="skill",
        invocation=f"/{name}",
    )


def default_skills_dir(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    if configured := env.get(SKILLS_DIR_ENV, "").strip():
        return Path(configured).expanduser()

    for candidate in CONVENTIONAL_SKILLS_DIRS:
        expanded = candidate.expanduser()
        if expanded.is_dir():
            return expanded

    return CONVENTIONAL_SKILLS_DIRS[0].expanduser()


def default_actions_path(env: Mapping[str, str] | None = None) -> Path | None:
    env = os.environ if env is None else env
    configured = env.get(ACTIONS_ENV, "").strip()
    return Path(configured).expanduser() if configured else None


def _validated(catalog: list[Skill]) -> list[Skill]:
    names = [action.name for action in catalog]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise RouterUnavailable(
            f"duplicate action names found: {', '.join(duplicates)}"
        )
    if len(catalog) > MAX_CHOICE_OPTIONS:
        raise RouterUnavailable(
            f"{len(catalog)} actions exceed the {MAX_CHOICE_OPTIONS}-option limit"
        )
    return catalog


def load_skills(skills_dir: Path) -> list[Skill]:
    if not skills_dir.is_dir():
        raise RouterUnavailable(f"no skills directory at {skills_dir}")
    skills = [
        skill
        for skill_md in sorted(skills_dir.glob("*/SKILL.md"))
        if (skill := parse_skill(skill_md)) is not None
    ]
    if not skills:
        raise RouterUnavailable(f"no user-invocable skills found in {skills_dir}")
    return _validated(skills)


def load_actions(path: Path) -> list[Skill]:
    """Load deterministic commands that compete with skills in the same ranking."""
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RouterUnavailable(f"{path}: {error}") from error
    if not isinstance(records, list):
        raise RouterUnavailable(f"{path}: expected a JSON array")

    actions = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise RouterUnavailable(f"{path}: action {index} must be an object")
        name = record.get("name")
        description = record.get("description")
        command = record.get("command")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (name, description, command)
        ):
            raise RouterUnavailable(
                f"{path}: action {index} needs non-empty name, description, "
                "and command"
            )
        actions.append(
            Skill(
                name=name.strip(),
                description=description.strip(),
                opening=f"Run the deterministic command: {command.strip()}",
                kind="script",
                invocation=command.strip(),
            )
        )
    return actions


def load_catalog(skills_dir: Path, actions_path: Path | None = None) -> list[Skill]:
    catalog = load_skills(skills_dir)
    if actions_path is not None:
        catalog += load_actions(actions_path)
    return _validated(catalog)
