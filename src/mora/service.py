"""Fachada del sistema: conversaciones, mensajes, decisiones humanas y vistas. La usan la API y la CLI."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from .contracts import DecisionHumana
from .deps import Deps
from .graph import build_graph
from .tracing import resumen_trazas


def make_checkpointer(deps: Deps):
    """thread_id por conversación y cliente. Postgres si hay MORA_DATABASE_URL; si no, SQLite local."""
    s = deps.settings
    if s.es_postgres:
        import psycopg
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row

        conn = psycopg.connect(s.database_url, autocommit=True, prepare_threshold=0, row_factory=dict_row)
        saver = PostgresSaver(conn)
        saver.setup()
        return saver
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    s.runtime_dir.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(s.runtime_dir / "checkpoints.sqlite", check_same_thread=False))


class MoraService:
    def __init__(self, deps: Deps | None = None, checkpointer=None):
        self.deps = deps or Deps.build()
        self.graph = build_graph(self.deps, checkpointer or make_checkpointer(self.deps))

    def _cfg(self, thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": 30}

    # ------------------------------------------------------------ conversaciones
    def nueva_conversacion(self, cliente_id: str | None = None, titulo: str = "") -> str:
        thread_id = f"{cliente_id or 'general'}-{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat(timespec="seconds")
        self.deps.db.insert("conversaciones", {"thread_id": thread_id, "cliente_id": cliente_id,
                                               "titulo": titulo or "Nueva conversación", "creada": now,
                                               "actualizada": now, "estado": "nueva"})
        return thread_id

    def listar_conversaciones(self) -> list[dict]:
        return self.deps.db.query("SELECT * FROM conversaciones ORDER BY actualizada DESC")

    def _touch(self, thread_id: str, vista: dict, titulo: str | None = None) -> None:
        sql, params = "UPDATE conversaciones SET actualizada=?, estado=?", [datetime.now().isoformat(timespec="seconds"),
                                                                             vista["estado"]]
        if titulo:
            sql += ", titulo=CASE WHEN titulo='Nueva conversación' THEN ? ELSE titulo END"
            params.append(titulo[:60])
        self.deps.db.execute(sql + " WHERE thread_id=?", params + [thread_id])

    # ------------------------------------------------------------ interacción
    def enviar(self, thread_id: str, texto: str) -> dict:
        conv = self.deps.db.one("SELECT * FROM conversaciones WHERE thread_id=?", (thread_id,))
        if conv is None:
            raise KeyError(f"conversación inexistente: {thread_id}")
        if self.vista(thread_id)["pendiente"]:
            raise RuntimeError("Hay una decisión pendiente en esta conversación: resolvela antes de seguir.")
        self.graph.invoke({"messages": [HumanMessage(texto)], "cliente_activo": conv["cliente_id"],
                           "thread_id": thread_id},
                          self._cfg(thread_id))
        v = self.vista(thread_id)
        self._touch(thread_id, v, titulo=texto)
        return v

    def decidir(self, thread_id: str, decision: DecisionHumana | dict) -> dict:
        d = DecisionHumana.model_validate(decision)
        self._exigir_pendiente(thread_id, "aprobacion")
        self.graph.invoke(Command(resume=d.model_dump()), self._cfg(thread_id))
        v = self.vista(thread_id)
        self._touch(thread_id, v)
        return v

    def aclarar(self, thread_id: str, agente: str | None) -> dict:
        self._exigir_pendiente(thread_id, "aclaracion")
        self.graph.invoke(Command(resume={"agente": agente}), self._cfg(thread_id))
        v = self.vista(thread_id)
        self._touch(thread_id, v)
        return v

    def _exigir_pendiente(self, thread_id: str, tipo: str) -> None:
        p = self.vista(thread_id)["pendiente"]
        if not p or p.get("tipo") != tipo:
            raise RuntimeError(f"No hay una {tipo} pendiente en {thread_id}.")

    # ------------------------------------------------------------ lectura
    def vista(self, thread_id: str) -> dict[str, Any]:
        snap = self.graph.get_state(self._cfg(thread_id))
        v = dict(snap.values or {})
        pendientes = [i.value for t in snap.tasks for i in t.interrupts]
        pendiente = pendientes[0] if pendientes else None
        estado = v.get("estado", "nueva")
        if pendiente:
            estado = "esperando_aprobacion" if pendiente["tipo"] == "aprobacion" else "esperando_aclaracion"
        mensajes = [{"rol": "diseñadora" if isinstance(m, HumanMessage) else (m.name or "sistema"),
                     "texto": str(m.content)} for m in v.get("messages", []) if isinstance(m, (HumanMessage, AIMessage))]
        turno = v.get("turno")
        return {
            "thread_id": thread_id, "estado": estado, "pendiente": pendiente, "mensajes": mensajes,
            "router": {"agente": v.get("agente_destino"), "confianza": v.get("confianza_router"),
                       "justificacion": v.get("justificacion_router"), "metodo": v.get("metodo_router")},
            "resultado_ejecucion": v.get("resultado_ejecucion", []),
            "trazas_turno": [t for t in v.get("trazas", []) if t.get("turno") == turno],
            "resumen_turno": resumen_trazas(v.get("trazas", []), turno),
            "resumen_conversacion": resumen_trazas(v.get("trazas", [])),
        }
