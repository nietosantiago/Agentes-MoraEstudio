"""Orquestación con LangGraph (C11 + C12).

intake → triage → plan ─Send×N→ worker ─fan-in→ consolidate ⇄ critic → prepare → review(interrupt)
   review ─approve→ policy → execute → remember → END
   review ─edit→ review (nueva versión)      review ─reject→ rejected → END

Reglas de diseño:
- Los side effects viven SOLO en `execute`, después de `review` (al reanudar, LangGraph re-entra al nodo
  que contiene interrupt(): ese nodo no debe tener efectos).
- `policy` vuelve a validar todo: la aprobación humana no reemplaza al Policy Gate.
- `execute` usa idempotency_key = run_id:action_id contra el ledger: reanudar no duplica efectos.
"""
from __future__ import annotations

import operator
from datetime import datetime
from typing import Annotated, Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt
from typing_extensions import TypedDict

from .agents.atencion import consolidar
from .agents.critic import criticar
from .agents.supervisor import PlanError, planificar
from .agents.triage import clasificar
from .agents.workers import run_worker
from .contracts import (ActionResult, Clasificacion, ConsolidatedAnswer, HumanDecision, PendingAction, Propuesta,
                        SolicitudEntrante, WorkerOutput, WorkerTask)
from .deps import Deps
from .memory import MemoryItem
from .tools import PolicyError


class MoraState(TypedDict, total=False):
    run_id: str
    solicitud: dict
    memoria: list[str]
    clasificacion: dict
    tasks: list[dict]
    plan_source: str
    worker_outputs: Annotated[list[dict], operator.add]  # reducer para ramas paralelas
    trace: Annotated[list[dict], operator.add]
    respuesta: dict
    critica: dict
    revisiones: int
    propuesta: dict
    decision: dict
    autorizadas: list[dict]
    resultados: list[dict]
    status: str
    error: str


def _ev(actor: str, event: str, **data) -> dict:
    return {"actor": actor, "event": event, "at": datetime.now().isoformat(timespec="seconds"), **data}


def build_graph(deps: Deps, checkpointer=None):
    def log(state: MoraState, actor: str, event: str, **data) -> list[dict]:
        deps.ledger.log(state["run_id"], actor, event, **data)
        return [_ev(actor, event, **data)]

    # ------------------------------------------------------------ nodos
    def intake(state: MoraState):
        sol = SolicitudEntrante.model_validate(state["solicitud"])
        cliente = deps.repo.cliente_por_contacto(sol.remitente)
        key = cliente["id"] if cliente else sol.remitente.lower()
        memoria = [m.content for m in deps.memory.retrieve(key)]
        return {"memoria": memoria, "revisiones": 0, "status": "in_progress",
                "trace": log(state, "intake", "request_received", canal=sol.canal, memorias=len(memoria))}

    def triage(state: MoraState):
        sol = SolicitudEntrante.model_validate(state["solicitud"])
        c = clasificar(sol, deps.repo, deps.llm)
        return {"clasificacion": c.model_dump(mode="json"),
                "trace": log(state, "triage", "classified", intencion=c.intencion, urgencia=c.urgencia,
                             cliente_id=c.cliente_id, metodo=c.metodo)}

    def plan(state: MoraState):
        sol = SolicitudEntrante.model_validate(state["solicitud"])
        c = Clasificacion.model_validate(state["clasificacion"])
        try:
            tasks, source = planificar(sol, c, deps.budget, deps.llm)
        except PlanError as exc:
            return {"tasks": [], "plan_source": "error", "error": str(exc),
                    "trace": log(state, "supervisor", "plan_invalid", error=str(exc))}
        return {"tasks": [t.model_dump() for t in tasks], "plan_source": source,
                "trace": log(state, "supervisor", "plan_created", source=source,
                             tasks=[f"{t.task_id}:{t.role}" for t in tasks])}

    def dispatch(state: MoraState):
        if not state.get("tasks"):
            return "consolidate"
        payload = {k: state[k] for k in ("run_id", "solicitud", "clasificacion")}
        return [Send("worker", {**payload, "task": t}) for t in state["tasks"]]

    def worker(state: dict):
        task = WorkerTask.model_validate(state["task"])
        out = run_worker(task, SolicitudEntrante.model_validate(state["solicitud"]),
                         Clasificacion.model_validate(state["clasificacion"]), deps)
        deps.ledger.log(state["run_id"], task.role, "task_completed", task_id=task.task_id, status=out.status,
                        latency_ms=out.latency_ms)
        return {"worker_outputs": [out.model_dump(mode="json")],
                "trace": [_ev(task.role, "task_completed", task_id=task.task_id, status=out.status,
                              latency_ms=out.latency_ms)]}

    def consolidate(state: MoraState):
        outs = [WorkerOutput.model_validate(o) for o in state.get("worker_outputs", [])]
        feedback = (state.get("critica") or {}).get("critical_issues")
        ans = consolidar(SolicitudEntrante.model_validate(state["solicitud"]),
                         Clasificacion.model_validate(state["clasificacion"]), outs, deps,
                         feedback=feedback, memoria=state.get("memoria"))
        return {"respuesta": ans.model_dump(mode="json"),
                "trace": log(state, "atencion", "draft_created", status=ans.status, skill=ans.skill,
                             fuentes=len(ans.sources))}

    def critic(state: MoraState):
        outs = [WorkerOutput.model_validate(o) for o in state.get("worker_outputs", [])]
        crit = criticar(ConsolidatedAnswer.model_validate(state["respuesta"]),
                        Clasificacion.model_validate(state["clasificacion"]), outs)
        return {"critica": crit.model_dump(), "revisiones": state.get("revisiones", 0) + (0 if crit.passed else 1),
                "trace": log(state, "critic", "reviewed", passed=crit.passed, issues=crit.critical_issues)}

    def after_critic(state: MoraState):
        if state["critica"]["passed"] or state["revisiones"] > deps.budget.max_revisiones:
            return "prepare"
        return "consolidate"

    def prepare(state: MoraState):
        """Fase PREPARE: arma la propuesta revisable. Sin efectos."""
        sol = SolicitudEntrante.model_validate(state["solicitud"])
        ans = ConsolidatedAnswer.model_validate(state["respuesta"])
        acciones: list[PendingAction] = []
        for o in state.get("worker_outputs", []):
            for a in WorkerOutput.model_validate(o).proposed_actions:
                if deps.policy.can_propose(a.proposed_by, a.tool):
                    acciones.append(a)
        acciones.append(PendingAction(
            action_id="enviar-respuesta-1", tool="enviar_respuesta", proposed_by="atencion", risk_level="high",
            args={"canal": sol.canal, "destinatario": sol.remitente, "asunto": ans.asunto, "cuerpo": ans.answer,
                  "en_respuesta_a": sol.id},
            rationale="Respuesta al cliente redactada por el agente de atención."))
        for a in acciones:
            a.idempotency_key = f"{state['run_id']}:{a.action_id}"
        prop = Propuesta(run_id=state["run_id"], respuesta=ans, acciones=acciones,
                         critica=state.get("critica"))
        return {"propuesta": prop.model_dump(mode="json"), "status": "waiting_for_approval",
                "trace": log(state, "runtime", "approval_requested", version=prop.version,
                             proposal_hash=prop.proposal_hash, acciones=[a.tool for a in acciones])}

    def review(state: MoraState):
        """HITL. Sin efectos: al reanudar, LangGraph re-ejecuta este nodo desde el principio."""
        prop = Propuesta.model_validate(state["propuesta"])
        raw = interrupt({
            "type": "approval_request", "run_id": prop.run_id, "version": prop.version,
            "proposal_hash": prop.proposal_hash, "escalar_a_humano": prop.respuesta.escalar_a_humano,
            "respuesta": prop.respuesta.model_dump(mode="json"),
            "acciones": [a.model_dump(mode="json") for a in prop.acciones],
            "critica": prop.critica.model_dump() if prop.critica else None,
        })
        dec = HumanDecision.model_validate(raw)
        if dec.proposal_hash != prop.proposal_hash:
            return {"decision": {**dec.model_dump(), "decision": "stale"},
                    "trace": log(state, dec.actor, "decision_stale", recibido=dec.proposal_hash,
                                 vigente=prop.proposal_hash)}
        if dec.decision == "edit":
            nuevas = []
            for a in prop.acciones:
                args = {**a.args, **dec.edited_args.get(a.action_id, {})}
                if a.tool == "enviar_respuesta" and dec.edited_answer:
                    args["cuerpo"] = dec.edited_answer
                deps.policy.registry[a.tool].args_model.model_validate(args)  # edición también se valida
                nuevas.append(a.model_copy(update={"args": args}))
            resp = prop.respuesta.model_copy(update={"answer": dec.edited_answer or prop.respuesta.answer})
            nueva = prop.model_copy(update={"version": prop.version + 1, "acciones": nuevas, "respuesta": resp})
            return {"propuesta": nueva.model_dump(mode="json"), "decision": dec.model_dump(),
                    "trace": log(state, dec.actor, "proposal_edited", version=nueva.version,
                                 proposal_hash=nueva.proposal_hash)}
        return {"decision": dec.model_dump(),
                "trace": log(state, dec.actor, f"decision_{dec.decision}", comment=dec.comment)}

    def after_review(state: MoraState):
        d = state["decision"]["decision"]
        return {"approve": "policy", "reject": "rejected"}.get(d, "review")  # edit/stale -> nueva revisión

    def policy(state: MoraState):
        prop = Propuesta.model_validate(state["propuesta"])
        dec = HumanDecision.model_validate(state["decision"])
        aprobadas = set(dec.approved_action_ids or [a.action_id for a in prop.acciones])
        autorizadas, bloqueadas = [], []
        for a in prop.acciones:
            if a.action_id not in aprobadas:
                bloqueadas.append(ActionResult(action_id=a.action_id, tool=a.tool, status="blocked",
                                               detail="no aprobada por el humano"))
                continue
            try:
                deps.policy.authorize_execution(a, human_approved=dec.proposal_hash == prop.proposal_hash)
                autorizadas.append(a.model_dump(mode="json"))
            except (PolicyError, ValueError) as exc:
                bloqueadas.append(ActionResult(action_id=a.action_id, tool=a.tool, status="blocked", detail=str(exc)))
        return {"autorizadas": autorizadas, "resultados": [b.model_dump() for b in bloqueadas],
                "trace": log(state, "policy", "authorized", ok=[a["action_id"] for a in autorizadas],
                             bloqueadas=[b.action_id for b in bloqueadas])}

    def execute(state: MoraState):
        resultados = list(state.get("resultados", []))
        for raw in state.get("autorizadas", []):
            a = PendingAction.model_validate(raw)
            spec = deps.policy.registry[a.tool]
            prev = deps.ledger.get(a.idempotency_key)
            if prev or not deps.ledger.reserve(a.idempotency_key, state["run_id"], a.tool):
                resultados.append(ActionResult(action_id=a.action_id, tool=a.tool, status="skipped_duplicate",
                                               detail=f"ya registrado: {(prev or {}).get('status')}").model_dump())
                continue
            try:
                out = spec.run(deps.tool_ctx, a.args)
                deps.ledger.complete(a.idempotency_key, "executed", out)
                resultados.append(ActionResult(action_id=a.action_id, tool=a.tool, status="executed",
                                               detail=str(out.get("registro", ""))).model_dump())
            except Exception as exc:
                # outcome ambiguo: queda 'failed' en ledger; NO se reintenta automáticamente
                deps.ledger.complete(a.idempotency_key, "failed", {"error": type(exc).__name__})
                resultados.append(ActionResult(action_id=a.action_id, tool=a.tool, status="failed",
                                               detail=type(exc).__name__).model_dump())
        ok = all(r["status"] in ("executed", "skipped_duplicate") for r in resultados if r["status"] != "blocked")
        return {"resultados": resultados, "status": "completed" if ok else "completed_with_errors",
                "trace": log(state, "runtime", "actions_executed",
                             resultados={r["action_id"]: r["status"] for r in resultados})}

    def remember(state: MoraState):
        """Write gate de memoria: solo hechos confirmados por ejecución aprobada."""
        sol = SolicitudEntrante.model_validate(state["solicitud"])
        c = Clasificacion.model_validate(state["clasificacion"])
        key = c.cliente_id or sol.remitente.lower()
        ejecutadas = {r["tool"] for r in state.get("resultados", []) if r["status"] == "executed"}
        escritos = 0
        if "enviar_respuesta" in ejecutadas:
            escritos += deps.memory.write(MemoryItem(
                cliente_key=key, kind="interaccion", source=state["run_id"], confidence=0.9,
                content=f"{deps.settings.hoy.isoformat()}: respondimos consulta de tipo '{c.intencion}' por {sol.canal}",
                expires_at=deps.memory.ttl(180)))
            escritos += deps.memory.write(MemoryItem(
                cliente_key=key, kind="preferencia", source=state["run_id"], confidence=0.6,
                content=f"Suele contactar por {sol.canal}"))
        if "registrar_presupuesto" in ejecutadas:
            pres = next(o for o in state["worker_outputs"] if o["role"] == "presupuestos")
            calc = pres["data"]["calculo"]
            escritos += deps.memory.write(MemoryItem(
                cliente_key=key, kind="hecho", source=state["run_id"], confidence=1.0,
                content=f"Presupuesto {pres['data']['presupuesto_id']} enviado: {calc['moneda']} {calc['total']}",
                expires_at=deps.memory.ttl(calc["validez_dias"])))
        return {"trace": log(state, "memory", "memory_written", items=escritos)}

    def rejected(state: MoraState):
        return {"status": "rejected", "trace": log(state, "runtime", "run_rejected")}

    # ------------------------------------------------------------ grafo
    g = StateGraph(MoraState)
    for name, fn in [("intake", intake), ("triage", triage), ("plan", plan), ("worker", worker),
                     ("consolidate", consolidate), ("critic", critic), ("prepare", prepare), ("review", review),
                     ("policy", policy), ("execute", execute), ("remember", remember), ("rejected", rejected)]:
        g.add_node(name, fn)
    g.add_edge(START, "intake")
    g.add_edge("intake", "triage")
    g.add_edge("triage", "plan")
    g.add_conditional_edges("plan", dispatch, ["worker", "consolidate"])
    g.add_edge("worker", "consolidate")  # fan-in: espera a todas las ramas del superstep
    g.add_edge("consolidate", "critic")
    g.add_conditional_edges("critic", after_critic, ["prepare", "consolidate"])
    g.add_edge("prepare", "review")
    g.add_conditional_edges("review", after_review, ["policy", "rejected", "review"])
    g.add_edge("policy", "execute")
    g.add_edge("execute", "remember")
    g.add_edge("remember", END)
    g.add_edge("rejected", END)
    return g.compile(checkpointer=checkpointer)


def run_config(run_id: str, deps: Deps) -> dict[str, Any]:
    return {"configurable": {"thread_id": run_id}, "max_concurrency": deps.budget.max_parallel_workers,
            "recursion_limit": 40}
