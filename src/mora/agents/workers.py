"""Workers especialistas (C12). Cada uno: contexto mínimo + tools de su rol + contrato WorkerOutput.

Ningún worker ejecuta efectos externos: solo LEE (vía ToolPolicy.call) y PROPONE PendingActions.
Una falla es un resultado válido del contrato (status=failed), no una excepción que rompe el grafo.
"""
from __future__ import annotations

import time

from ..contracts import Clasificacion, Evidence, PendingAction, SolicitudEntrante, WorkerOutput, WorkerTask
from ..deps import Deps

MIN_SCORE = 1.0


def documental(task: WorkerTask, sol: SolicitudEntrante, c: Clasificacion, deps: Deps) -> WorkerOutput:
    ctx, pol = deps.tool_ctx, deps.policy
    res = pol.call("documental", "buscar_documentos", ctx,
                   {"query": task.inputs["query"][:300], "proyecto_id": task.inputs.get("proyecto_id"), "k": 3})
    hits = [h for h in res["hits"] if h["score"] >= MIN_SCORE]
    evidence = [Evidence(claim=h["text"], source=h["source"], locator=h["section"]) for h in hits]
    data: dict = {"hits": hits}
    if pid := task.inputs.get("proyecto_id"):
        ficha = pol.call("documental", "consultar_proyecto", ctx, {"proyecto_id": pid})
        if ficha["found"]:
            p = ficha["proyecto"]
            data["proyecto"] = p
            evidence.append(Evidence(claim=f"{p['nombre']}: etapa {p['etapa_actual']}, avance {p['avance_pct']}%",
                                     source="clientes.json", locator=pid))
    if not evidence:
        return WorkerOutput(task_id=task.task_id, role="documental", status="partial",
                            summary="No se encontró evidencia suficiente en la documentación.",
                            open_questions=["Derivar la consulta al arquitecto responsable"], confidence=0.2)
    return WorkerOutput(task_id=task.task_id, role="documental", status="success",
                        summary=f"{len(evidence)} evidencias recuperadas", evidence=evidence, data=data,
                        confidence=min(0.95, 0.5 + 0.1 * len(evidence)))


def agenda(task: WorkerTask, sol: SolicitudEntrante, c: Clasificacion, deps: Deps) -> WorkerOutput:
    res = deps.policy.call("agenda", "listar_vencimientos", deps.tool_ctx,
                           {"dias": 30, "proyecto_id": task.inputs.get("proyecto_id"), "slots_libres": 3})
    pid = task.inputs.get("proyecto_id")
    # Solo eventos del proyecto del cliente: la agenda interna u otros clientes no son evidencia para él.
    res["eventos"] = [e for e in res["eventos"] if pid and e["proyecto_id"] == pid]
    evidence = [Evidence(claim=f"{e['fecha']} {e['hora']} — {e['titulo']}", source="agenda.json", locator=e["id"])
                for e in res["eventos"]]
    evidence += [Evidence(claim=f"Horario libre {sl['fecha']} {sl['hora']}", source="agenda.json",
                          locator="disponibilidad") for sl in res["slots_libres"]]
    actions: list[PendingAction] = []
    if task.inputs.get("proponer_evento") and res["slots_libres"]:
        slot = res["slots_libres"][0]
        quien = sol.nombre or (deps.repo.cliente(c.cliente_id) or {}).get("nombre") or sol.remitente
        actions.append(PendingAction(
            action_id="crear-evento-1", tool="crear_evento_agenda", proposed_by="agenda", risk_level="medium",
            args={"fecha": slot["fecha"], "hora": slot["hora"], "titulo": f"Reunión con {quien}",
                  "invitado": sol.remitente, "proyecto_id": c.proyecto_id},
            rationale="Reservar el primer horario libre ofrecido; el cliente debe confirmar.",
        ))
    return WorkerOutput(task_id=task.task_id, role="agenda", status="success",
                        summary=f"{len(res['eventos'])} eventos próximos, {len(res['slots_libres'])} horarios libres",
                        evidence=evidence, data=res, proposed_actions=actions, confidence=0.9)


def presupuestos(task: WorkerTask, sol: SolicitudEntrante, c: Clasificacion, deps: Deps) -> WorkerOutput:
    datos = task.inputs.get("datos", {})
    faltan = [q for k, q in (("tipo_proyecto", "¿Qué tipo de proyecto es (vivienda, reforma, local, oficina)?"),
                             ("superficie_m2", "¿Cuántos m² aproximados tendrá el proyecto?")) if not datos.get(k)]
    if faltan:
        return WorkerOutput(task_id=task.task_id, role="presupuestos", status="partial",
                            summary="Faltan datos para calcular honorarios.", open_questions=faltan, confidence=0.3)
    calc = deps.policy.call("presupuestos", "calcular_honorarios", deps.tool_ctx,
                            {k: datos[k] for k in ("tipo_proyecto", "superficie_m2", "etapas")})
    pres_id = f"PRES-{sol.id}"
    return WorkerOutput(
        task_id=task.task_id, role="presupuestos", status="success",
        summary=f"Honorarios {calc['moneda']} {calc['total']} (IVA incl.)",
        evidence=[Evidence(claim=f"Tarifa {datos['tipo_proyecto']}: {calc['moneda']} {calc['tarifa_m2']}/m²",
                           source="tarifario.json", locator=calc["fuente"])],
        data={"calculo": calc, "presupuesto_id": pres_id, "datos": datos},
        assumptions=[f"Superficie declarada por el cliente: {datos['superficie_m2']} m²"],
        proposed_actions=[PendingAction(
            action_id="registrar-presupuesto-1", tool="registrar_presupuesto", proposed_by="presupuestos",
            risk_level="low", args={"presupuesto_id": pres_id, "cliente": sol.remitente, "calculo": calc},
            rationale="Registrar el presupuesto enviado para seguimiento comercial.")],
        confidence=0.95,
    )


WORKERS = {"documental": documental, "agenda": agenda, "presupuestos": presupuestos}


def run_worker(task: WorkerTask, sol: SolicitudEntrante, c: Clasificacion, deps: Deps) -> WorkerOutput:
    t0 = time.perf_counter()
    try:
        out = WORKERS[task.role](task, sol, c, deps)
    except Exception as exc:  # falla contractual, sin exponer detalles sensibles al consolidador
        out = WorkerOutput(task_id=task.task_id, role=task.role, status="failed",
                           summary=f"El worker falló ({type(exc).__name__}).", confidence=0.0)
    out.latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    return out
