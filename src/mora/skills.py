"""Skill loader con Progressive Disclosure (C10).

Discovery: solo frontmatter (name, description, mora-intents). El body de SKILL.md y sus references/
se cargan recién cuando la Skill es seleccionada. Las Skills NO otorgan permisos: eso es ToolPolicy.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    intents: tuple[str, ...]
    version: str
    path: Path


@dataclass(frozen=True)
class LoadedSkill:
    meta: SkillMeta
    body: str

    def reference(self, filename: str) -> str:
        return (self.meta.path / "references" / filename).read_text(encoding="utf-8")


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    _, fm, body = text.split("---", 2)
    meta = {}
    for line in fm.strip().splitlines():
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip()
    return meta, body.strip()


class SkillLoader:
    def __init__(self, skills_dir: Path):
        self.dir = skills_dir
        self.catalog: list[SkillMeta] = []
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
            head = skill_md.read_text(encoding="utf-8").split("---", 2)[1]
            meta, _ = _parse_frontmatter(f"---{head}---")
            self.catalog.append(SkillMeta(
                name=meta["name"], description=meta["description"],
                intents=tuple(i.strip() for i in meta.get("mora-intents", "").split(",") if i.strip()),
                version=meta.get("mora-version", "0"), path=skill_md.parent,
            ))

    def select(self, intencion: str) -> SkillMeta | None:
        return next((s for s in self.catalog if intencion in s.intents), None)

    def load(self, meta: SkillMeta) -> LoadedSkill:
        _, body = _parse_frontmatter((meta.path / "SKILL.md").read_text(encoding="utf-8"))
        return LoadedSkill(meta, body)
