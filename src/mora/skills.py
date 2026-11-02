"""Skill loader con Progressive Disclosure.

La identidad de marca es poco contenido, estable y tiene que estar en TODAS las llamadas: por eso es
una Skill que se carga siempre (no un vector store). Sus references/ se abren solo cuando un agente
las necesita. Las Skills no otorgan permisos: eso es ToolPolicy.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    _, fm, body = text.split("---", 2)
    meta = {}
    for line in fm.strip().splitlines():
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip()
    return meta, body.strip()


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    version: str
    body: str
    path: Path

    def reference(self, filename: str) -> str:
        return (self.path / "references" / filename).read_text(encoding="utf-8")

    def references(self) -> list[str]:
        return sorted(p.name for p in (self.path / "references").glob("*.md"))


def load_skill(skills_dir: Path, name: str) -> Skill:
    path = skills_dir / name
    meta, body = _frontmatter((path / "SKILL.md").read_text(encoding="utf-8"))
    return Skill(meta["name"], meta["description"], meta.get("mora-version", "0"), body, path)
