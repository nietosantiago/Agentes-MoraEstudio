"""Tool Registry + Policy Gate (C9) y niveles de autonomía (C11).

Tres preguntas separadas:
  1. ¿Qué tools existen?                  -> REGISTRY
  2. ¿Qué tools puede usar/proponer un rol? -> ToolPolicy.allowed_tools / can_propose
  3. ¿Esta llamada concreta se ejecuta?   -> ToolPolicy.authorize_execution (+ aprobación humana)

Niveles de autonomía:
  1 automático (lecturas, cálculos) · 2 automático + log (escrituras internas reversibles)
  3 aprobar antes (efectos externos) · 4 no delegar (excede la autoridad del sistema)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import BaseModel

from ..config import Settings
from ..contracts import PendingAction
from ..repository import EstudioRepo
from ..retrieval import Retriever

Risk = Literal["read", "internal_write", "side_effect"]


class PolicyError(PermissionError):
    pass


@dataclass
class ToolContext:
    settings: Settings
    repo: EstudioRepo
    retriever: Retriever


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str          # model-facing: cuándo usarla y cuándo no
    args_model: type[BaseModel]
    handler: Callable[[ToolContext, BaseModel], dict[str, Any]]
    risk: Risk
    autonomy_level: Literal[1, 2, 3, 4]
    timeout_s: float = 10.0

    def run(self, ctx: ToolContext, raw_args: dict[str, Any]) -> dict[str, Any]:
        args = self.args_model.model_validate(raw_args)  # validación estructural antes del handler
        return self.handler(ctx, args)


# Qué puede LEER cada rol y qué puede PROPONER (nunca ejecutar) -----------------
ROLE_READ: dict[str, set[str]] = {
    "documental": {"buscar_documentos", "consultar_proyecto"},
    "agenda": {"listar_vencimientos", "consultar_proyecto"},
    "presupuestos": {"calcular_honorarios", "consultar_proyecto", "buscar_documentos"},
    "atencion": set(),  # redacta con lo que recibe; no consulta fuentes por su cuenta
}
ROLE_PROPOSE: dict[str, set[str]] = {
    "agenda": {"crear_evento_agenda"},
    "presupuestos": {"registrar_presupuesto"},
    "atencion": {"enviar_respuesta"},
}


class ToolPolicy:
    def __init__(self, registry: dict[str, ToolSpec]):
        self.registry = registry

    def allowed_tools(self, role: str) -> list[ToolSpec]:
        return [self.registry[n] for n in sorted(ROLE_READ.get(role, set()))]

    def call(self, role: str, tool: str, ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        """Lectura directa por un worker: solo tools de riesgo 'read' habilitadas para su rol."""
        spec = self.registry.get(tool)
        if spec is None:
            raise PolicyError(f"tool desconocida: {tool}")
        if tool not in ROLE_READ.get(role, set()) or spec.risk != "read":
            raise PolicyError(f"rol '{role}' no puede ejecutar '{tool}'")
        return spec.run(ctx, args)

    def can_propose(self, role: str, tool: str) -> bool:
        spec = self.registry.get(tool)
        return bool(spec) and tool in ROLE_PROPOSE.get(role, set()) and spec.autonomy_level < 4

    def authorize_execution(self, action: PendingAction, *, human_approved: bool) -> ToolSpec:
        """Se vuelve a validar TODO antes del efecto: la aprobación humana no reemplaza la policy."""
        spec = self.registry.get(action.tool)
        if spec is None:
            raise PolicyError(f"tool desconocida: {action.tool}")
        if not self.can_propose(action.proposed_by, action.tool):
            raise PolicyError(f"'{action.proposed_by}' no está autorizado a proponer '{action.tool}'")
        if spec.autonomy_level == 4:
            raise PolicyError(f"'{action.tool}' es nivel 4: no se delega")
        if spec.autonomy_level == 3 and not human_approved:
            raise PolicyError(f"'{action.tool}' requiere aprobación humana")
        spec.args_model.model_validate(action.args)
        return spec


def build_registry() -> dict[str, ToolSpec]:
    from . import handlers as h

    specs = [
        ToolSpec("buscar_documentos",
                 "Busca en documentos del estudio (servicios, procesos, condiciones, informes de avance). "
                 "Usar para respaldar afirmaciones con fuente. No usar para datos numéricos de tarifario.",
                 h.BuscarDocumentosArgs, h.buscar_documentos, "read", 1),
        ToolSpec("consultar_proyecto",
                 "Devuelve ficha de un proyecto (etapa, avance, hitos, responsable) por proyecto_id.",
                 h.ConsultarProyectoArgs, h.consultar_proyecto, "read", 1),
        ToolSpec("listar_vencimientos",
                 "Lista eventos y vencimientos de agenda en una ventana de días, opcionalmente por proyecto, "
                 "y los próximos horarios libres para reuniones con clientes.",
                 h.ListarVencimientosArgs, h.listar_vencimientos, "read", 1),
        ToolSpec("calcular_honorarios",
                 "Calcula honorarios según tarifario vigente (tipo de proyecto, m², etapas). Determinístico.",
                 h.CalcularHonorariosArgs, h.calcular_honorarios, "read", 1),
        ToolSpec("registrar_presupuesto",
                 "Registra un presupuesto en borrador en el sistema interno (reversible).",
                 h.RegistrarPresupuestoArgs, h.registrar_presupuesto, "internal_write", 2),
        ToolSpec("crear_evento_agenda",
                 "Crea un evento en la agenda del estudio e invita al cliente (efecto externo).",
                 h.CrearEventoArgs, h.crear_evento_agenda, "side_effect", 3),
        ToolSpec("enviar_respuesta",
                 "Envía la respuesta al cliente por su canal (email/WhatsApp). Efecto externo irreversible.",
                 h.EnviarRespuestaArgs, h.enviar_respuesta, "side_effect", 3),
        ToolSpec("comprometer_descuento",
                 "Compromete un descuento sobre el tarifario. Reservado a la dirección del estudio.",
                 h.DescuentoArgs, h.no_delegable, "side_effect", 4),
    ]
    return {s.name: s for s in specs}
