"""Supervisor — patrón 04 Supervisor–Workers con fan-out/fan-in (C12).

Descompone la solicitud en WorkerTasks. El plan puede venir de reglas o de un LLM;
en ambos casos el runtime lo valida con `validate_plan` antes de despachar.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..contracts import Clasificacion, RunBudget, SolicitudEntrante, WorkerTask
from ..llm.base import LLMError, LLMProvider

KNOWN_ROLES = {"documental", "agenda", "presupuestos"}


class PlanError(ValueError):
    pass


class Plan(BaseModel):
    tasks: list[WorkerTask] = Field(default_factory=list)


def _doc(tid: str, query: str, c: Clasificacion, criterio: str) -> WorkerTask:
    return WorkerTask(task_id=tid, role="documental", objective=f"Recuperar evidencia: {query}",
                      inputs={"query": query, "proyecto_id": c.proyecto_id},
                      success_criteria=[criterio, "Cada afirmación con fuente"])


def _agenda(tid: str, c: Clasificacion, proponer: bool, criterio: str) -> WorkerTask:
    return WorkerTask(task_id=tid, role="agenda", objective="Revisar agenda, vencimientos y horarios libres",
                      inputs={"proyecto_id": c.proyecto_id, "proponer_evento": proponer},
                      success_criteria=[criterio])


def plan_por_reglas(sol: SolicitudEntrante, c: Clasificacion) -> list[WorkerTask]:
    q = f"{sol.asunto} {sol.cuerpo}"
    match c.intencion:
        case "nuevo_lead":
            return [_doc("doc-1", f"servicios proceso de trabajo primera reunion {q}", c, "Servicios relevantes"),
                    _agenda("agenda-1", c, False, "Hasta 3 horarios libres para primera reunión")]
        case "consulta_proyecto":
            return [_doc("doc-1", f"estado general avance documentacion municipal proximos pasos {q}", c,
                         "Estado del proyecto documentado"),
                    _agenda("agenda-1", c, False, "Próximos hitos y vencimientos del proyecto")]
        case "presupuesto":
            return [WorkerTask(task_id="pres-1", role="presupuestos", objective="Calcular honorarios con tarifario",
                               inputs={"datos": c.datos.model_dump()},
                               success_criteria=["Montos por etapa, IVA y total del tarifario vigente"]),
                    _doc("doc-1", "honorarios forma de pago anticipo validez no incluye", c,
                         "Condiciones comerciales aplicables")]
        case "agenda":
            return [_agenda("agenda-1", c, True, "Horarios libres y propuesta de evento")]
        case "documentacion":
            return [_doc("doc-1", q, c, "Documento o procedimiento solicitado")]
        case "reclamo":
            return [_doc("doc-1", f"desvios estado general demora {q}", c, "Causa documentada del problema"),
                    _agenda("agenda-1", c, False, "Próxima visita o hito del proyecto")]
        case _:
            return [_doc("doc-1", q, c, "Respuesta en FAQ o documentación")]


def validate_plan(tasks: list[WorkerTask], budget: RunBudget) -> list[WorkerTask]:
    """Controles de negocio que un structured output no reemplaza."""
    if len(tasks) > budget.max_workers:
        raise PlanError(f"plan con {len(tasks)} tareas excede max_workers={budget.max_workers}")
    ids = [t.task_id for t in tasks]
    if len(ids) != len(set(ids)):
        raise PlanError("task_id duplicados")
    for t in tasks:
        if t.role not in KNOWN_ROLES:
            raise PlanError(f"rol desconocido: {t.role}")
        for d in t.depends_on:
            if d not in ids:
                raise PlanError(f"{t.task_id} depende de tarea inexistente {d}")
    # ciclos (DFS)
    graph = {t.task_id: t.depends_on for t in tasks}
    state: dict[str, int] = {}

    def visit(n: str) -> None:
        if state.get(n) == 1:
            raise PlanError(f"ciclo de dependencias en {n}")
        if state.get(n) == 2:
            return
        state[n] = 1
        for m in graph[n]:
            visit(m)
        state[n] = 2

    for n in graph:
        visit(n)
    if sum(t.max_steps for t in tasks) > budget.max_total_steps:
        raise PlanError("el plan excede max_total_steps")
    return tasks


SYSTEM = (
    "Sos el supervisor de Mora Estudio. Generá un plan mínimo de tareas para workers: "
    "documental (evidencia en documentos), agenda (vencimientos y horarios), presupuestos (honorarios). "
    "No redactes la respuesta. Usá la menor cantidad de tareas posible."
)


def planificar(sol: SolicitudEntrante, c: Clasificacion, budget: RunBudget,
               llm: LLMProvider | None = None) -> tuple[list[WorkerTask], str]:
    if llm is not None:
        try:
            plan = llm.generate_structured(system=SYSTEM, prompt=c.model_dump_json(), schema=Plan)
            return validate_plan(plan.tasks, budget), "llm"
        except (LLMError, PlanError):
            pass  # fallback determinístico explícito
    return validate_plan(plan_por_reglas(sol, c), budget), "reglas"
