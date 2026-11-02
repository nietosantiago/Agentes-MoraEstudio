"""Contratos tipados entre router, agentes, ejecutor y la diseñadora (HITL)."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

Agente = Literal["comercial", "contenidos", "administrativo", "proyectos"]
AGENTES: tuple[str, ...] = ("comercial", "contenidos", "administrativo", "proyectos")
Riesgo = Literal["bajo", "medio", "alto"]


class Subpedido(BaseModel):
    agente: Agente
    pedido: str = Field(min_length=2, max_length=500)


class DecisionRouter(BaseModel):
    """Structured output del router. La justificación no la usa el sistema: es para evaluar errores.

    `subpedidos` (2-3) solo cuando el pedido mezcla tareas de áreas distintas; si está vacío, el
    pedido completo va a `agente`.
    """

    agente: Agente
    confianza: float = Field(ge=0, le=1)
    justificacion: str = Field(max_length=300)
    subpedidos: list[Subpedido] = Field(default_factory=list, max_length=3)
    metodo: Literal["reglas", "llm", "humano"] = "reglas"

    @property
    def es_multiple(self) -> bool:
        return len({s.agente for s in self.subpedidos}) >= 2


class Operacion(BaseModel):
    tool: str
    args: dict[str, Any]
    descripcion: str
    agente: Agente | None = None          # quién la propuso (la policy valida contra este agente)


class AccionPendiente(BaseModel):
    """Lo que un agente PROPONE. Nunca lo ejecuta quien lo propone: lo ejecuta el nodo ejecutor."""

    accion_id: str
    agente: Agente | Literal["multiagente"]
    resumen: str
    justificacion: str = ""
    operaciones: list[Operacion] = Field(min_length=1)
    riesgo: Riesgo
    efecto_externo: bool
    version: int = 1
    agentes: list[Agente] = Field(default_factory=list)
    observaciones: list[str] = Field(default_factory=list)  # avisos del consolidador para la diseñadora

    @property
    def hash(self) -> str:
        payload = {"id": self.accion_id, "v": self.version,
                   "ops": [o.model_dump(mode="json") for o in self.operaciones]}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


class ResultadoAgente(BaseModel):
    respuesta: str                        # texto para la diseñadora
    accion: AccionPendiente | None = None  # None = respuesta informativa -> END
    datos: dict[str, Any] = Field(default_factory=dict)
    tools_usadas: list[str] = Field(default_factory=list)
    errores: list[str] = Field(default_factory=list)
    modo: Literal["local", "llm", "llm_fallback_local"] = "local"


class DecisionHumana(BaseModel):
    decision: Literal["aprobado", "modificado", "rechazado"]
    accion_hash: str                      # aprueba ESTA versión, no otra
    comentario: str = ""
    correccion: str = ""                  # texto libre que vuelve al agente (modificado)
    cambios: dict[str, dict[str, Any]] = Field(default_factory=dict)  # args por índice de operación ("0", "1"...)


class ResultadoOperacion(BaseModel):
    indice: int
    tool: str
    estado: Literal["ejecutada", "duplicada_omitida", "bloqueada", "fallida"]
    detalle: str = ""
