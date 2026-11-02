"""Grafo LangGraph del estudio.

            carga_contexto  (marca + cliente)
                  ↓
               router  ── confianza < umbral ──► aclaracion (interrupt: la diseñadora elige)
                  │  delegación: Send por subpedido (1 a 3 agentes, en paralelo)
     ┌──────────┬─┴────────┬──────────┐                │
 comercial  contenidos  administrativo  proyectos ◄────┘
     └──────────┴─┬────────┴──────────┘
             consolidador  (una respuesta + una acción; duplicados, conflictos plata×tiempo)
        ¿acción con efecto? ── no ──► END (respuesta informativa)
                  ↓ sí
            revision (interrupt)  ── modificado ──► vuelve a los agentes (único ciclo)
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
from langgraph.types import Send, interrupt
from pydantic import ValidationError
from typing_extensions import TypedDict

from .agents.base import EntradaAgente
from .agents.registro import AGENTES_CLASES
from .agents.router import pregunta_aclaracion, rutear
from .consolidacion import consolidar
from .contracts import AGENTES, AccionPendiente, DecisionHumana, DecisionRouter, ResultadoAgente, ResultadoOperacion
from .deps import Deps
from .tools import PolicyError
from .tracing import traced


def acumular_resultados(actual: list | None, nuevo: list | None) -> list:
    """Reducer para el fan-in de agentes en paralelo. `None` reinicia la lista (nueva ronda)."""
    if nuevo is None:
        return []
    return (actual or []) + nuevo


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
    tareas: list[dict]                # delegación: [{"agente", "pedido"}] (1 a 3)
    ronda: int                        # cada (re)despacho a los agentes es una ronda
    resultados_agentes: Annotated[list[dict], acumular_resultados]
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
                "cambios": None, "resultado_ejecucion": [], "estado": "en_curso", "resultados_agentes": None,
                "tareas": [], "ronda": 0,
                "_traza_extra": {"marca": f"{deps.marca.name}@{deps.marca.version}",
                                 "cliente": state.get("cliente_activo")}}

    @traced("router", s)
    def router(state: EstadoEstudio):
        texto = _ultimo_humano(state)
        d = rutear(texto, deps.llm, s.umbral_router)
        tareas = ([{"agente": x.agente, "pedido": x.pedido} for x in d.subpedidos] if d.es_multiple
                  else [{"agente": d.agente, "pedido": texto}])
        return {"agente_destino": d.agente, "confianza_router": d.confianza, "justificacion_router": d.justificacion,
                "metodo_router": d.metodo, "tareas": tareas, "ronda": 1,
                "_traza_extra": {"agente": d.agente, "confianza": d.confianza, "metodo": d.metodo,
                                 "justificacion": d.justificacion, "delegacion": [t["agente"] for t in tareas]}}

    def despachar(state: EstadoEstudio) -> list[Send]:
        """Delegación: un Send por subpedido. Cada agente recibe solo lo que necesita."""
        base = {k: state.get(k) for k in ("messages", "thread_id", "cliente_activo", "turno", "accion_pendiente",
                                          "correccion", "ronda")}
        completo = _ultimo_humano(state)
        return [Send(t["agente"], {**base, "tarea": {**t, "indice": i, "contexto": completo}})
                for i, t in enumerate(state["tareas"])]

    def salida_router(state: EstadoEstudio):
        if state["confianza_router"] < s.umbral_router:
            return "aclaracion"
        return despachar(state)

    def aclaracion(state: EstadoEstudio):
        """Pregunta en vez de adivinar. Sin efectos (se re-ejecuta al reanudar)."""
        d = DecisionRouter(agente=state["agente_destino"], confianza=state["confianza_router"],
                           justificacion=state.get("justificacion_router", ""))
        resp = interrupt({"tipo": "aclaracion", **pregunta_aclaracion(_ultimo_humano(state), d)})
        agente = resp.get("agente") if isinstance(resp, dict) else None
        if agente not in AGENTES:
            return {"estado": "informativo", "messages": [AIMessage("No derivé el pedido. Reformulalo cuando quieras.")]}
        return {"agente_destino": agente, "confianza_router": 1.0, "metodo_router": "humano",
                "justificacion_router": "elegido por la diseñadora", "ronda": 1,
                "tareas": [{"agente": agente, "pedido": _ultimo_humano(state)}]}

    def salida_aclaracion(state: EstadoEstudio):
        return despachar(state) if state.get("metodo_router") == "humano" else END

    def make_agente(nombre: str):
        @traced(nombre, s)
        def nodo(state: dict):
            tarea = state.get("tarea") or {"pedido": _ultimo_humano(state), "indice": 0, "contexto": ""}
            previa = AccionPendiente.model_validate(state["accion_pendiente"]) if state.get("accion_pendiente") else None
            texto = tarea["pedido"]
            if state.get("correccion"):
                texto = f"{state['correccion']} || {texto}"  # la corrección tiene prioridad al extraer datos
            cliente = deps.db.one("SELECT * FROM clientes WHERE id=?", (state["cliente_activo"],)) \
                if state.get("cliente_activo") else None
            e = EntradaAgente(texto=texto, turno=state.get("turno", 0), thread_id=state.get("thread_id", ""),
                              cliente=cliente, correccion=state.get("correccion") or "", accion_previa=previa,
                              historial=[str(m.content) for m in state.get("messages", [])[-6:]],
                              contexto=tarea.get("contexto") or "")
            try:
                r = AGENTES_CLASES[nombre](deps).ejecutar(e)
            except Exception as exc:  # falla parcial: el resto de los agentes sigue y el consolidador la muestra
                r = ResultadoAgente(respuesta="No pude completar esta parte del pedido.",
                                    errores=[f"{type(exc).__name__}: {str(exc)[:120]}"])
            return {"resultados_agentes": [{"ronda": state.get("ronda", 1), "indice": tarea["indice"],
                                            "agente": nombre, "resultado": r.model_dump(mode="json")}],
                    "_traza_extra": {"tools": r.tools_usadas, "errores": r.errores, "modo": r.modo,
                                     "propone_accion": bool(r.accion), "subpedido": tarea["pedido"][:120]}}
        return nodo

    @traced("consolidador", s)
    def consolidador(state: EstadoEstudio):
        ronda = state.get("ronda", 1)
        res = sorted((x for x in state.get("resultados_agentes", []) if x["ronda"] == ronda), key=lambda x: x["indice"])
        pares = [(x["agente"], ResultadoAgente.model_validate(x["resultado"])) for x in res]
        previa = state.get("accion_pendiente")
        version = (previa or {}).get("version", 0) + 1 if state.get("decision_humana") == "modificado" else 1
        respuesta, accion, meta = consolidar(pares, turno=state.get("turno", 0), version=version, db=deps.db,
                                             cambios=state.get("cambios"))
        autor = pares[0][0] if len(pares) == 1 else "consolidador"
        return {"accion_pendiente": accion.model_dump(mode="json") if accion else None,
                "estado": "esperando_aprobacion" if accion else "informativo", "correccion": None, "cambios": None,
                "messages": [AIMessage(respuesta, name=autor)], "_traza_extra": meta}

    def salida_consolidador(state: EstadoEstudio) -> str:
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
            return {"decision_humana": "modificado", "correccion": d.correccion or d.comentario, "cambios": d.cambios,
                    "ronda": state.get("ronda", 1) + 1, "resultados_agentes": None}
        return {"decision_humana": "aprobado"}

    def salida_revision(state: EstadoEstudio):
        d = state.get("decision_humana")
        if d == "aprobado":
            return "ejecutor"
        if d == "modificado":
            return despachar(state)  # único ciclo del grafo: vuelven los mismos agentes con la corrección
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
    g.add_node("consolidador", consolidador)
    g.add_node("revision", revision)
    g.add_node("ejecutor", ejecutor)

    g.add_edge(START, "carga_contexto")
    g.add_edge("carga_contexto", "router")
    g.add_conditional_edges("router", salida_router, [*AGENTES, "aclaracion"])          # arista 1
    g.add_conditional_edges("aclaracion", salida_aclaracion, [*AGENTES, END])
    for a in AGENTES:
        g.add_edge(a, "consolidador")                                                   # fan-in
    g.add_conditional_edges("consolidador", salida_consolidador, ["revision", END])      # arista 2
    g.add_conditional_edges("revision", salida_revision, ["ejecutor", "revision", END, *AGENTES])  # arista 3
    g.add_edge("ejecutor", END)
    return g.compile(checkpointer=checkpointer)
