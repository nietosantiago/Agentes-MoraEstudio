"""Contratos tipados entre router, agentes, ejecutor y la diseñadora (HITL)."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

Agente = Literal["comercial", "contenidos", "administrativo", "proyectos"]
AGENTES: tuple[str, ...] = ("comercial", "contenidos", "administrativo", "proyectos")
Riesgo = Literal["bajo", "medio", "alto"]


class DecisionRouter(BaseModel):
    """Structured output del router. La justificación no la usa el sistema: es para evaluar errores."""

    agente: Agente
    confianza: float = Field(ge=0, le=1)
    justificacion: str = Field(max_length=300)
    metodo: Literal["reglas", "llm", "humano"] = "reglas"


class Operacion(BaseModel):
    tool: str
    args: dict[str, Any]
    descripcion: str


class AccionPendiente(BaseModel):
    """Lo que un agente PROPONE. Nunca lo ejecuta quien lo propone: lo ejecuta el nodo ejecutor."""

    accion_id: str
    agente: Agente
    resumen: str
    justificacion: str = ""
    operaciones: list[Operacion] = Field(min_length=1)
    riesgo: Riesgo
    efecto_externo: bool
    version: int = 1

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
