"""Contenedor de dependencias compartidas por los nodos del grafo."""
from __future__ import annotations

from dataclasses import dataclass

from .config import Settings, load_settings
from .contracts import RunBudget
from .llm import LLMProvider, get_provider
from .memory import MemoryStore
from .repository import EstudioRepo
from .retrieval import BM25Retriever, Retriever
from .runtime.ledger import ActionLedger
from .skills import SkillLoader
from .tools import ToolContext, ToolPolicy, build_registry


@dataclass
class Deps:
    settings: Settings
    repo: EstudioRepo
    retriever: Retriever
    policy: ToolPolicy
    ledger: ActionLedger
    memory: MemoryStore
    skills: SkillLoader
    llm: LLMProvider | None
    budget: RunBudget

    @property
    def tool_ctx(self) -> ToolContext:
        return ToolContext(self.settings, self.repo, self.retriever)

    @classmethod
    def build(cls, settings: Settings | None = None, llm: LLMProvider | None = None,
              budget: RunBudget | None = None) -> "Deps":
        s = settings or load_settings()
        rt = s.runtime_dir
        return cls(
            settings=s,
            repo=EstudioRepo(s.estudio_dir),
            retriever=BM25Retriever.from_dir(s.docs_dir),
            policy=ToolPolicy(build_registry()),
            ledger=ActionLedger(rt / "ledger.sqlite"),
            memory=MemoryStore(rt / "memory.sqlite"),
            skills=SkillLoader(s.skills_dir),
            llm=llm if llm is not None else get_provider(s),
            budget=budget or RunBudget(),
        )
