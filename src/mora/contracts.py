"""Contratos tipados entre agentes, runtime y humanos (C2, C9, C11, C12).

Ningún agente intercambia texto libre: todo cruza una frontera validada con Pydantic.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Canal = Literal["email", "whatsapp", "web", "interno"]
Intencion = Literal[
    "nuevo_lead",         # alguien que todavía no es cliente consulta por servicios
    "consulta_proyecto",  # cliente pregunta por avance/estado de su proyecto
    "presupuesto",        # pedido de cotización / honorarios
    "agenda",             # coordinar reunión, visita a obra, cambio de turno
    "documentacion",      # pide planos, contratos, memorias, permisos
    "reclamo",            # queja o problema (escala siempre a un humano)
    "otro",
]
Urgencia = Literal["baja", "media", "alta"]
WorkerRole = Literal["documental", "agenda", "presupuestos"]
RiskLevel = Literal["low", "medium", "high"]
Status = Literal["success", "partial", "failed"]


# ---------------------------------------------------------------- entrada
class SolicitudEntrante(BaseModel):
    """Mensaje que llega al estudio por cualquier canal. Su contenido es dato NO confiable."""

    id: str
    canal: Canal = "email"
    remitente: str
    nombre: str | None = None
    asunto: str = ""
    cuerpo: str
    recibido_en: datetime = Field(default_factory=datetime.now)


class DatosExtraidos(BaseModel):
    tipo_proyecto: str | None = None  # vivienda, reforma, local_comercial, interiorismo, oficina
    superficie_m2: float | None = None
    etapas: list[str] = Field(default_factory=list)
    ubicacion: str | None = None


class Clasificacion(BaseModel):
    intencion: Intencion
    urgencia: Urgencia = "media"
    cliente_id: str | None = None
    proyecto_id: str | None = None
    resumen: str
    datos: DatosExtraidos = Field(default_factory=DatosExtraidos)
    confianza: float = Field(ge=0, le=1, default=0.7)
    metodo: Literal["reglas", "llm"] = "reglas"


# ---------------------------------------------------------------- delegación
class WorkerTask(BaseModel):
    task_id: str
    role: WorkerRole
    objective: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    success_criteria: list[str] = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    max_steps: int = Field(default=3, ge=1, le=6)


class Evidence(BaseModel):
    claim: str
    source: str           # archivo o sistema autoritativo
    locator: str = ""     # sección, id de proyecto, id de evento


class PendingAction(BaseModel):
    """Acción con efecto propuesta por un agente. Nunca la ejecuta quien la propone."""

    action_id: str
    tool: str
    args: dict[str, Any]
    rationale: str
    risk_level: RiskLevel
    proposed_by: str
    idempotency_key: str = ""


class WorkerOutput(BaseModel):
    task_id: str
    role: WorkerRole
    status: Status
    summary: str
    evidence: list[Evidence] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    proposed_actions: list[PendingAction] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1, default=0.5)
    latency_ms: float = 0.0


class RunBudget(BaseModel):
    """El supervisor no puede ampliar su propio presupuesto (C12)."""

    max_workers: int = Field(default=3, ge=1, le=5)
    max_parallel_workers: int = Field(default=2, ge=1, le=5)
    max_total_steps: int = Field(default=12, ge=1)
    max_revisiones: int = Field(default=1, ge=0, le=3)


# ---------------------------------------------------------------- consolidación
class ConsolidatedAnswer(BaseModel):
    asunto: str
    answer: str
    sources: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    contributing_agents: list[str] = Field(default_factory=list)
    skill: str | None = None
    status: Literal["complete", "partial", "failed"]
    escalar_a_humano: bool = False


class Critique(BaseModel):
    passed: bool
    critical_issues: list[str] = Field(default_factory=list)
    suggested_changes: list[str] = Field(default_factory=list)
    rubric_scores: dict[str, float] = Field(default_factory=dict)


# ---------------------------------------------------------------- HITL
class Propuesta(BaseModel):
    """Paquete revisable: borrador + acciones. Cada edición crea una versión nueva."""

    run_id: str
    version: int = 1
    respuesta: ConsolidatedAnswer
    acciones: list[PendingAction]
    critica: Critique | None = None

    @property
    def proposal_hash(self) -> str:
        payload = {
            "run_id": self.run_id,
            "version": self.version,
            "acciones": [a.model_dump(mode="json") for a in self.acciones],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


class HumanDecision(BaseModel):
    decision: Literal["approve", "edit", "reject"]
    actor: str
    proposal_hash: str
    comment: str = ""
    # Para "edit": nuevo cuerpo del mail y/o args por action_id
    edited_answer: str | None = None
    edited_args: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # Para "approve": permite aprobar solo algunas acciones (default: todas)
    approved_action_ids: list[str] | None = None


class ActionResult(BaseModel):
    action_id: str
    tool: str
    status: Literal["executed", "skipped_duplicate", "blocked", "failed"]
    detail: str = ""
