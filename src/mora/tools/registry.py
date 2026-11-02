"""Tool Registry + Policy Gate.

Cada agente tiene SUS tools: eso es lo que justifica el multiagente (herramientas, permisos y riesgos
distintos). Tres preguntas separadas:
  ¿qué tools existen?                      -> registry
  ¿qué puede leer / proponer este agente?  -> ToolPolicy.lectura / propuesta
  ¿se ejecuta ESTA operación?              -> ToolPolicy.autorizar (+ aprobación humana + precondiciones)

Definición de "efecto externo" (contexto TFI §9):
  tipo="externa" -> sale del estudio o es difícil de revertir (mensaje a lead/cliente, presupuesto
                    enviado, factura, post programado, invitación de calendario). Nivel 3: aprobar antes.
  tipo="interna" -> cambia datos propios y es reversible (registrar lead, actualizar hito, registrar
                    cobro). Nivel 2. En el TFI también pasa por revisión (los agentes no ejecutan nada).
  tipo="lectura" -> consultas y cálculos. Nivel 1. Respuesta informativa -> END sin molestar a nadie.
  Nivel 4        -> no delegable (aplicar descuentos).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Literal

from pydantic import BaseModel

from ..config import Settings
from ..contracts import AccionPendiente, Operacion
from ..skills import Skill

Tipo = Literal["lectura", "interna", "externa"]
NIVEL_RIESGO = {"bajo": 0, "medio": 1, "alto": 2}


class PolicyError(PermissionError):
    pass


@dataclass
class ToolContext:
    settings: Settings
    db: Any
    facturacion: Any
    marca: Skill

    @property
    def hoy(self) -> date:
        return self.settings.hoy


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str                       # model-facing: qué hace, cuándo usarla y cuándo no
    args_model: type[BaseModel]
    handler: Callable[[ToolContext, BaseModel], dict[str, Any]]
    tipo: Tipo
    nivel: Literal[1, 2, 3, 4]
    riesgo: Literal["bajo", "medio", "alto"]
    agentes: frozenset[str]
    precondicion: Callable[[ToolContext, BaseModel], None] | None = field(default=None)

    def validar(self, args: dict[str, Any]) -> BaseModel:
        return self.args_model.model_validate(args)

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        parsed = self.validar(args)
        if self.precondicion:
            self.precondicion(ctx, parsed)
        return self.handler(ctx, parsed)

    def schema_resumido(self) -> dict:
        return {"name": self.name, "description": self.description, "tipo": self.tipo,
                "args_schema": self.args_model.model_json_schema()}


class ToolPolicy:
    def __init__(self, registry: dict[str, ToolSpec]):
        self.registry = registry

    def lectura(self, agente: str) -> list[ToolSpec]:
        return [s for s in self.registry.values() if s.tipo == "lectura" and agente in s.agentes]

    def propuesta(self, agente: str) -> list[ToolSpec]:
        return [s for s in self.registry.values() if s.tipo != "lectura" and agente in s.agentes and s.nivel < 4]

    def call(self, agente: str, tool: str, ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        """Lectura directa por un agente. Escribir o enviar está prohibido acá: solo se propone."""
        spec = self.registry.get(tool)
        if spec is None:
            raise PolicyError(f"tool desconocida: {tool}")
        if spec.tipo != "lectura" or agente not in spec.agentes:
            raise PolicyError(f"el agente '{agente}' no puede ejecutar '{tool}'")
        return spec.run(ctx, args)

    def validar_operacion(self, agente: str, op: Operacion) -> ToolSpec:
        spec = self.registry.get(op.tool)
        if spec is None:
            raise PolicyError(f"tool desconocida: {op.tool}")
        if spec.nivel == 4:
            raise PolicyError(f"'{op.tool}' no es delegable: lo decide la diseñadora")
        if spec.tipo == "lectura" or agente not in spec.agentes:
            raise PolicyError(f"el agente '{agente}' no puede proponer '{op.tool}'")
        spec.validar(op.args)
        return spec

    def clasificar(self, agente: str, ops: list[Operacion]) -> tuple[str, bool]:
        specs = [self.validar_operacion(agente, o) for o in ops]
        riesgo = max((s.riesgo for s in specs), key=NIVEL_RIESGO.__getitem__)
        return riesgo, any(s.tipo == "externa" for s in specs)

    def autorizar(self, accion: AccionPendiente, op: Operacion, ctx: ToolContext, *, aprobada: bool) -> ToolSpec:
        """Se re-valida TODO antes del efecto: la aprobación humana no reemplaza la policy."""
        spec = self.validar_operacion(op.agente or accion.agente, op)
        if spec.nivel >= 2 and not aprobada:
            raise PolicyError(f"'{op.tool}' requiere aprobación de la diseñadora")
        if spec.precondicion:
            spec.precondicion(ctx, spec.validar(op.args))
        return spec


def build_registry() -> dict[str, ToolSpec]:
    from . import administrativo as adm
    from . import comercial as com
    from . import contenidos as con
    from . import proyectos as pro

    C, CO, A, P = "comercial", "contenidos", "administrativo", "proyectos"
    f = frozenset
    specs = [
        # --- comercial
        ToolSpec("buscar_contacto", "Busca clientes y leads por nombre o contacto. Usar para identificar a la persona.",
                 com.BuscarContactoArgs, com.buscar_contacto, "lectura", 1, "bajo", f({C, A, P})),
        ToolSpec("listar_leads", "Lista leads por estado y/o días sin contacto. Usar para seguimiento comercial.",
                 com.ListarLeadsArgs, com.listar_leads, "lectura", 1, "bajo", f({C})),
        ToolSpec("calificar_lead", "Califica un lead (A/B/C) según zona, presupuesto declarado y tipo de proyecto. "
                 "Determinística: no usar el criterio propio.", com.CalificarLeadArgs, com.calificar_lead,
                 "lectura", 1, "bajo", f({C})),
        ToolSpec("consultar_servicios", "Describe los servicios del estudio (sin precios: los precios son del "
                 "agente administrativo).", com.SinArgs, com.consultar_servicios, "lectura", 1, "bajo", f({C, CO})),
        ToolSpec("registrar_lead", "Crea o actualiza un lead en la base del estudio.",
                 com.RegistrarLeadArgs, com.registrar_lead, "interna", 2, "bajo", f({C})),
        ToolSpec("enviar_mensaje", "Envía un mensaje a un lead o cliente por su canal. EFECTO EXTERNO.",
                 com.EnviarMensajeArgs, com.enviar_mensaje, "externa", 3, "medio", f({C, P})),
        # --- contenidos
        ToolSpec("calendario_contenidos", "Posts programados o publicados de un mes (YYYY-MM).",
                 con.CalendarioArgs, con.calendario_contenidos, "lectura", 1, "bajo", f({CO})),
        ToolSpec("pilares_contenido", "Pilares de contenido y frecuencia de publicación de la marca.",
                 con.SinArgs, con.pilares_contenido, "lectura", 1, "bajo", f({CO})),
        ToolSpec("obras_publicables", "Obras con permiso del cliente para mostrarse en redes.",
                 con.SinArgs, con.obras_publicables, "lectura", 1, "bajo", f({CO})),
        ToolSpec("programar_posts", "Deja posts programados en el calendario para publicarse. EFECTO EXTERNO.",
                 con.ProgramarPostsArgs, con.programar_posts, "externa", 3, "medio", f({CO})),
        # --- administrativo (plata)
        ToolSpec("consultar_precios", "Lista de precios vigente (tabla exacta).",
                 adm.PreciosArgs, adm.consultar_precios, "lectura", 1, "bajo", f({A})),
        ToolSpec("calcular_presupuesto", "Calcula un presupuesto con la tabla de precios: subtotal, mínimos, "
                 "seña 50% y saldo. Determinística.", adm.CalcularPresupuestoArgs, adm.calcular_presupuesto,
                 "lectura", 1, "bajo", f({A})),
        ToolSpec("resumen_facturacion", "Total facturado entre dos fechas, por cliente.",
                 adm.ResumenFacturacionArgs, adm.resumen_facturacion, "lectura", 1, "bajo", f({A})),
        ToolSpec("cobros_pendientes", "Cobros pendientes (opcionalmente de un cliente), con días de atraso.",
                 adm.CobrosPendientesArgs, adm.cobros_pendientes, "lectura", 1, "bajo", f({A})),
        ToolSpec("enviar_presupuesto", "Registra y envía un presupuesto al cliente o lead. EFECTO EXTERNO.",
                 adm.EnviarPresupuestoArgs, adm.enviar_presupuesto, "externa", 3, "medio", f({A})),
        ToolSpec("emitir_factura", "Emite una factura electrónica por la API de facturación. EFECTO EXTERNO, "
                 "irreversible.", adm.EmitirFacturaArgs, adm.emitir_factura, "externa", 3, "alto", f({A}),
                 precondicion=adm.pre_emitir_factura),
        ToolSpec("enviar_recordatorio_cobro", "Envía un recordatorio amable de pago. EFECTO EXTERNO.",
                 adm.RecordatorioArgs, adm.enviar_recordatorio_cobro, "externa", 3, "medio", f({A}),
                 precondicion=adm.pre_recordatorio),
        ToolSpec("registrar_cobro", "Marca un cobro como recibido.",
                 adm.RegistrarCobroArgs, adm.registrar_cobro, "interna", 2, "bajo", f({A})),
        ToolSpec("aplicar_descuento", "Aplica un descuento. NO DELEGABLE.",
                 adm.DescuentoArgs, adm.no_delegable, "externa", 4, "alto", f({A})),
        # --- proyectos (tiempo)
        ToolSpec("listar_obras", "Obras del estudio (activas o todas) con su etapa.",
                 pro.ListarObrasArgs, pro.listar_obras, "lectura", 1, "bajo", f({P})),
        ToolSpec("consultar_obra", "Ficha de una obra con hitos, entregables y eventos.",
                 pro.ConsultarObraArgs, pro.consultar_obra, "lectura", 1, "bajo", f({P})),
        ToolSpec("proximos_hitos", "Hitos y entregables de los próximos N días y los atrasados.",
                 pro.ProximosHitosArgs, pro.proximos_hitos, "lectura", 1, "bajo", f({P})),
        ToolSpec("actualizar_hito", "Cambia estado, fecha o notas de un hito/entregable.",
                 pro.ActualizarHitoArgs, pro.actualizar_hito, "interna", 2, "bajo", f({P})),
        ToolSpec("agendar_evento", "Crea un evento en el calendario e invita al cliente. EFECTO EXTERNO.",
                 pro.AgendarEventoArgs, pro.agendar_evento, "externa", 3, "medio", f({P})),
    ]
    return {s.name: s for s in specs}
