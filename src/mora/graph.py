"""Grafo LangGraph del estudio.

            carga_contexto  (marca + cliente)
                  ↓
               router  ── confianza < umbral ──► aclaracion (interrupt: la diseñadora elige)
     ┌──────────┬─┴────────┬──────────┐                │
 comercial  contenidos  administrativo  proyectos ◄────┘
     └──────────┴─┬────────┴──────────┘
        ¿acción con efecto? ── no ──► END (respuesta informativa)
                  ↓ sí
            revision (interrupt)  ── modificado ──► vuelve al agente (único ciclo)
                  │                ── rechazado ──► END
                  ↓ aprobado
               ejecutor (policy + idempotencia) ──► END

Reglas:
- Los agentes NO ejecutan nada: dejan `accion_pendiente` en el estado.
- Al reanudar, LangGraph re-entra al nodo que contiene interrupt(): `revision` no tiene efectos.
- El ejecutor re-autoriza cada operación (la aprobación no reemplaza la policy) y usa un ledger
  con idempotency_key = thread:accion:operacion, así un reintento no duplica facturas ni mensajes.
"""
from __future__ import annotations

import json
import operator
from datetime import datetime
from typing import Annotated

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt
from pydantic import ValidationError
from typing_extensions import TypedDict

from .agents.base import EntradaAgente
from .agents.registro import AGENTES_CLASES
from .agents.router import pregunta_aclaracion, rutear
from .contracts import AGENTES, AccionPendiente, DecisionHumana, DecisionRouter, ResultadoOperacion
from .deps import Deps
from .tools import PolicyError
from .tracing import traced


class EstadoEstudio(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    thread_id: str
    cliente_activo: str | None
    agente_destino: str | None
    confianza_router: float
    justificacion_router: str
    metodo_router: str
    accion_pendiente: dict | None     # qué se va a ejecutar, esperando el OK
    decision_humana: str | None       # aprobado / modificado / rechazado
    correccion: str | None
    cambios: dict | None
    resultado_ejecucion: list[dict]
    turno: int
    estado: str                       # informativo | esperando_aclaracion | esperando_aprobacion | ejecutado | rechazado
    trazas: Annotated[list[dict], operator.add]  # tokens, costo y latencia por nodo


def _ultimo_humano(state: EstadoEstudio) -> str:
    for m in reversed(state.get("messages", [])):
        if isinstance(m, HumanMessage):
            return str(m.content)
    return ""


def build_graph(deps: Deps, checkpointer=None):
    s = deps.settings

    @traced("carga_contexto", s)
    def carga_contexto(state: EstadoEstudio):
        turno = sum(1 for m in state.get("messages", []) if isinstance(m, HumanMessage))
        return {"turno": turno, "accion_pendiente": None, "decision_humana": None, "correccion": None,
                "cambios": None, "resultado_ejecucion": [], "estado": "en_curso",
                "_traza_extra": {"marca": f"{deps.marca.name}@{deps.marca.version}",
                                 "cliente": state.get("cliente_activo")}}

    @traced("router", s)
    def router(state: EstadoEstudio):
        d = rutear(_ultimo_humano(state), deps.llm)
        return {"agente_destino": d.agente, "confianza_router": d.confianza, "justificacion_router": d.justificacion,
                "metodo_router": d.metodo,
                "_traza_extra": {"agente": d.agente, "confianza": d.confianza, "metodo": d.metodo,
                                 "justificacion": d.justificacion}}

    def salida_router(state: EstadoEstudio) -> str:
        return state["agente_destino"] if state["confianza_router"] >= s.umbral_router else "aclaracion"

    def aclaracion(state: EstadoEstudio):
        """Pregunta en vez de adivinar. Sin efectos (se re-ejecuta al reanudar)."""
        d = DecisionRouter(agente=state["agente_destino"], confianza=state["confianza_router"],
                           justificacion=state.get("justificacion_router", ""))
        resp = interrupt({"tipo": "aclaracion", **pregunta_aclaracion(_ultimo_humano(state), d)})
        agente = resp.get("agente") if isinstance(resp, dict) else None
        if agente not in AGENTES:
            return {"estado": "informativo", "messages": [AIMessage("No derivé el pedido. Reformulalo cuando quieras.")]}
        return {"agente_destino": agente, "confianza_router": 1.0, "metodo_router": "humano",
                "justificacion_router": "elegido por la diseñadora"}

    def salida_aclaracion(state: EstadoEstudio) -> str:
        return state["agente_destino"] if state.get("metodo_router") == "humano" else END

    def make_agente(nombre: str):
        @traced(nombre, s)
        def nodo(state: EstadoEstudio):
            previa = AccionPendiente.model_validate(state["accion_pendiente"]) if state.get("accion_pendiente") else None
            texto = _ultimo_humano(state)
            if state.get("correccion"):
                texto = f"{state['correccion']} || {texto}"  # la corrección tiene prioridad al extraer datos
            cliente = deps.db.one("SELECT * FROM clientes WHERE id=?", (state["cliente_activo"],)) \
                if state.get("cliente_activo") else None
            e = EntradaAgente(texto=texto, turno=state.get("turno", 0), thread_id=state.get("thread_id", ""),
                              cliente=cliente, correccion=state.get("correccion") or "", accion_previa=previa,
                              cambios=state.get("cambios") or {},
                              historial=[str(m.content) for m in state.get("messages", [])[-6:]])
            r = AGENTES_CLASES[nombre](deps).ejecutar(e)
            return {"accion_pendiente": r.accion.model_dump(mode="json") if r.accion else None,
                    "estado": "esperando_aprobacion" if r.accion else "informativo",
                    "correccion": None, "cambios": None,
                    "messages": [AIMessage(r.respuesta, name=nombre)],
                    "_traza_extra": {"tools": r.tools_usadas, "errores": r.errores, "modo": r.modo,
                                     "propone_accion": bool(r.accion)}}
        return nodo

    def salida_agente(state: EstadoEstudio) -> str:
        return "revision" if state.get("accion_pendiente") else END

    def revision(state: EstadoEstudio):
        """Human-in-the-loop. Sin efectos: al reanudar, este nodo se ejecuta de nuevo desde el principio."""
        accion = AccionPendiente.model_validate(state["accion_pendiente"])
        raw = interrupt({"tipo": "aprobacion", "accion_hash": accion.hash, "accion": accion.model_dump(mode="json")})
        try:
            d = DecisionHumana.model_validate(raw)
        except ValidationError:
            return {"decision_humana": "invalida"}
        if d.accion_hash != accion.hash:  # aprobación de una versión vieja: no vale
            return {"decision_humana": "desactualizada",
                    "messages": [AIMessage("Esa decisión era sobre otra versión de la propuesta. Revisá la actual.")]}
        if d.decision == "rechazado":
            return {"decision_humana": "rechazado", "estado": "rechazado", "accion_pendiente": None,
                    "messages": [AIMessage(f"Listo, descarté: {accion.resumen}." + (f" ({d.comentario})" if d.comentario else ""))]}
        if d.decision == "modificado":
            return {"decision_humana": "modificado", "correccion": d.correccion or d.comentario, "cambios": d.cambios}
        return {"decision_humana": "aprobado"}

    def salida_revision(state: EstadoEstudio) -> str:
        d = state.get("decision_humana")
        if d == "aprobado":
            return "ejecutor"
        if d == "modificado":
            return state["agente_destino"]  # único ciclo del grafo
        if d == "rechazado":
            return END
        return "revision"  # inválida o desactualizada: se vuelve a pedir

    @traced("ejecutor", s)
    def ejecutor(state: EstadoEstudio):
        accion = AccionPendiente.model_validate(state["accion_pendiente"])
        thread = state["thread_id"]  # obligatorio: forma parte de la idempotency_key
        ctx, resultados = deps.tool_ctx, []
        for i, op in enumerate(accion.operaciones):
            key = f"{thread}:{accion.accion_id}:{i}"
            if deps.db.one("SELECT estado FROM efectos WHERE idempotency_key=?", (key,)):
                resultados.append(ResultadoOperacion(indice=i, tool=op.tool, estado="duplicada_omitida",
                                                     detalle="ya ejecutada antes (ledger)"))
                continue
            try:
                spec = deps.policy.autorizar(accion, op, ctx, aprobada=True)
            except (PolicyError, ValidationError, ValueError) as exc:
                resultados.append(ResultadoOperacion(indice=i, tool=op.tool, estado="bloqueada", detalle=str(exc)))
                continue
            if not deps.db.insert("efectos", {"idempotency_key": key, "thread_id": thread, "tool": op.tool,
                                              "estado": "en_curso", "resultado": None,
                                              "creado": datetime.now().isoformat()}, on_conflict_nothing=True):
                resultados.append(ResultadoOperacion(indice=i, tool=op.tool, estado="duplicada_omitida",
                                                     detalle="ya ejecutada antes (ledger)"))
                continue
            try:
                out = spec.run(ctx, op.args)
                deps.db.execute("UPDATE efectos SET estado='ejecutada', resultado=? WHERE idempotency_key=?",
                                (json.dumps(out, default=str, ensure_ascii=False), key))
                resultados.append(ResultadoOperacion(indice=i, tool=op.tool, estado="ejecutada",
                                                     detalle=json.dumps(out, default=str, ensure_ascii=False)[:300]))
            except Exception as exc:  # outcome ambiguo: queda registrado como fallido, NO se reintenta solo
                deps.db.execute("UPDATE efectos SET estado='fallida', resultado=? WHERE idempotency_key=?",
                                (json.dumps({"error": str(exc)}), key))
                resultados.append(ResultadoOperacion(indice=i, tool=op.tool, estado="fallida", detalle=str(exc)))
        ok = [r for r in resultados if r.estado == "ejecutada"]
        mal = [r for r in resultados if r.estado in ("fallida", "bloqueada")]
        texto = f"Hecho: {len(ok)}/{len(resultados)} operación(es) de «{accion.resumen}»."
        if mal:
            texto += " Problemas: " + "; ".join(f"{r.tool} {r.estado} ({r.detalle})" for r in mal)
        return {"resultado_ejecucion": [r.model_dump() for r in resultados],
                "estado": "ejecutado" if not mal else "ejecutado_con_errores",
                "messages": [AIMessage(texto, name="ejecutor")],
                "_traza_extra": {"resultados": {r.indice: r.estado for r in resultados}}}

    g = StateGraph(EstadoEstudio)
    g.add_node("carga_contexto", carga_contexto)
    g.add_node("router", router)
    g.add_node("aclaracion", aclaracion)
    for a in AGENTES:
        g.add_node(a, make_agente(a))
    g.add_node("revision", revision)
    g.add_node("ejecutor", ejecutor)

    g.add_edge(START, "carga_contexto")
    g.add_edge("carga_contexto", "router")
    g.add_conditional_edges("router", salida_router, [*AGENTES, "aclaracion"])          # arista 1
    g.add_conditional_edges("aclaracion", salida_aclaracion, [*AGENTES, END])
    for a in AGENTES:
        g.add_conditional_edges(a, salida_agente, ["revision", END])                     # arista 2
    g.add_conditional_edges("revision", salida_revision, ["ejecutor", "revision", END, *AGENTES])  # arista 3
    g.add_edge("ejecutor", END)
    return g.compile(checkpointer=checkpointer)
