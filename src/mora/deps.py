"""Contenedor de dependencias compartidas por los nodos del grafo."""
from __future__ import annotations

from dataclasses import dataclass

from .config import Settings, load_settings
from .db import Database
from .integrations.facturacion import FacturacionProvider, MockFacturacion
from .llm import LLMProvider, get_provider
from .skills import Skill, load_skill
from .tools import ToolContext, ToolPolicy, build_registry


@dataclass
class Deps:
    settings: Settings
    db: Database
    policy: ToolPolicy
    facturacion: FacturacionProvider
    marca: Skill
    llm: LLMProvider | None

    @property
    def tool_ctx(self) -> ToolContext:
        return ToolContext(self.settings, self.db, self.facturacion, self.marca)

    @classmethod
    def build(cls, settings: Settings | None = None, *, llm: LLMProvider | None = None,
              facturacion: FacturacionProvider | None = None, seed: bool = True) -> "Deps":
        s = settings or load_settings()
        db = Database(s)
        db.init_schema()
        if seed:
            db.seed(s.seed_dir)
        return cls(settings=s, db=db, policy=ToolPolicy(build_registry()),
                   facturacion=facturacion or MockFacturacion(db), marca=load_skill(s.skills_dir, "identidad-marca"),
                   llm=llm if llm is not None else get_provider(s))
