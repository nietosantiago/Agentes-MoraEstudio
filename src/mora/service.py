"""Fachada del sistema: iniciar un run, inspeccionarlo y reanudarlo con una decisión humana.

Es la interfaz que van a usar la CLI, una API (FastAPI) o un servidor MCP en fases siguientes.
"""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from .contracts import HumanDecision, SolicitudEntrante
from .deps import Deps
from .graph import build_graph, run_config


@dataclass
class RunView:
    run_id: str
    status: str
    approval_request: dict | None
    resultados: list[dict]
    trace: list[dict]
    state: dict[str, Any]


class MoraSystem:
    def __init__(self, deps: Deps | None = None, checkpointer=None):
        self.deps = deps or Deps.build()
        if checkpointer is None:
            path = self.deps.settings.runtime_dir / "checkpoints.sqlite"
            path.parent.mkdir(parents=True, exist_ok=True)
            checkpointer = SqliteSaver(sqlite3.connect(path, check_same_thread=False))  # sobrevive reinicios
        self.graph = build_graph(self.deps, checkpointer)

    def _view(self, run_id: str) -> RunView:
        snap = self.graph.get_state(run_config(run_id, self.deps))
        values = dict(snap.values)
        pending = [i.value for t in snap.tasks for i in t.interrupts]
        return RunView(run_id=run_id, status=values.get("status", "unknown"),
                       approval_request=pending[0] if pending else None,
                       resultados=values.get("resultados", []), trace=values.get("trace", []), state=values)

    def start(self, solicitud: SolicitudEntrante | dict, run_id: str | None = None) -> RunView:
        sol = SolicitudEntrante.model_validate(solicitud)
        run_id = run_id or f"run-{sol.id}-{uuid.uuid4().hex[:6]}"
        self.graph.invoke({"run_id": run_id, "solicitud": sol.model_dump(mode="json")},
                          run_config(run_id, self.deps))
        return self._view(run_id)

    def get(self, run_id: str) -> RunView:
        return self._view(run_id)

    def decide(self, run_id: str, decision: HumanDecision | dict) -> RunView:
        dec = HumanDecision.model_validate(decision)
        self.graph.invoke(Command(resume=dec.model_dump()), run_config(run_id, self.deps))
        return self._view(run_id)
