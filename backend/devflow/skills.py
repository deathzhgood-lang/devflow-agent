from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SkillDefinition:
    skill_id: str
    name: str
    version: str
    description: str
    allowed_tools: tuple[str, ...]
    required_permissions: tuple[str, ...]
    risk_level: str
    path: Path


class SkillRegistry:
    def __init__(self, root: Path):
        self.root = root
        self._skills: dict[str, SkillDefinition] = {}

    def load(self) -> None:
        skills: dict[str, SkillDefinition] = {}
        for manifest_path in sorted(self.root.glob("*/skill.yaml")):
            data: dict[str, Any] = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            metadata = data.get("metadata", {})
            spec = data.get("spec", {})
            skill_id = str(metadata.get("id", "")).strip()
            allowed_tools = tuple(str(item) for item in spec.get("allowed_tools", []))
            if not skill_id or not allowed_tools:
                raise ValueError(f"Invalid skill manifest: {manifest_path}")
            if skill_id in skills:
                raise ValueError(f"Duplicate skill id: {skill_id}")
            skills[skill_id] = SkillDefinition(
                skill_id=skill_id,
                name=str(metadata.get("name", skill_id)),
                version=str(metadata.get("version", "0.0.0")),
                description=str(spec.get("description", "")),
                allowed_tools=allowed_tools,
                required_permissions=tuple(str(item) for item in spec.get("required_permissions", [])),
                risk_level=str(spec.get("risk_level", "read")),
                path=manifest_path.parent,
            )
        self._skills = skills

    def get(self, skill_id: str) -> SkillDefinition:
        try:
            return self._skills[skill_id]
        except KeyError as exc:
            raise KeyError(f"Unknown skill: {skill_id}") from exc

    def list_metadata(self) -> list[dict[str, Any]]:
        return [
            {
                "skill_id": skill.skill_id,
                "name": skill.name,
                "version": skill.version,
                "description": skill.description,
                "risk_level": skill.risk_level,
            }
            for skill in self._skills.values()
        ]

    def validate_binding(self, skill_id: str, tool_name: str) -> None:
        skill = self.get(skill_id)
        if tool_name not in skill.allowed_tools:
            raise PermissionError(f"Skill {skill_id} cannot call tool {tool_name}")

