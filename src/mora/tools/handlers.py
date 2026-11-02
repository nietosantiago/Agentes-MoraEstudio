"""Handlers de tools. Los de efecto escriben en data/runtime (simulación) hasta conectar MCP real."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from .registry import ToolContext


def _append_jsonl(ctx: ToolContext, name: str, record: dict) -> str:
    ctx.settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    path = ctx.settings.runtime_dir / name
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return str(path.relative_to(ctx.settings.runtime_dir.parent.parent))


# ---------------------------------------------------------------- lecturas
class BuscarDocumentosArgs(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    proyecto_id: str | None = None
    k: int = Field(default=3, ge=1, le=6)


def buscar_documentos(ctx: ToolContext, a: BuscarDocumentosArgs) -> dict:
    hits = []
    if a.proyecto_id:
        hits = ctx.retriever.search(a.query, k=a.k, filters={"proyecto_id": a.proyecto_id})
    hits += ctx.retriever.search(a.query, k=a.k)
    seen, out = set(), []
    for h in hits:
        # Aislamiento entre clientes: un documento de proyecto solo se devuelve para ESE proyecto.
        doc_pid = h.chunk.metadata.get("proyecto_id")
        if doc_pid and doc_pid != a.proyecto_id:
            continue
        if h.chunk.chunk_id not in seen:
            seen.add(h.chunk.chunk_id)
            out.append({"source": h.chunk.source, "section": h.chunk.section, "text": h.chunk.text,
                        "score": round(h.score, 3), "proyecto_id": h.chunk.metadata.get("proyecto_id")})
    return {"hits": out[: a.k + 1]}


class ConsultarProyectoArgs(BaseModel):
    proyecto_id: str = Field(pattern=r"^PRJ-\d{4}-\d{3}$")


def consultar_proyecto(ctx: ToolContext, a: ConsultarProyectoArgs) -> dict:
    p = ctx.repo.proyecto(a.proyecto_id)
    return {"found": p is not None, "proyecto": p}


class ListarVencimientosArgs(BaseModel):
    dias: int = Field(default=30, ge=1, le=120)
    proyecto_id: str | None = None
    slots_libres: int = Field(default=3, ge=0, le=6)


def listar_vencimientos(ctx: ToolContext, a: ListarVencimientosArgs) -> dict:
    hoy = ctx.settings.hoy
    hasta = hoy + timedelta(days=a.dias)
    agenda = ctx.repo.agenda
    eventos = [
        e for e in agenda["eventos"]
        if hoy <= date.fromisoformat(e["fecha"]) <= hasta and (a.proyecto_id in (None, e["proyecto_id"]))
    ]
    eventos.sort(key=lambda e: (e["fecha"], e["hora"]))
    ocupados = {(e["fecha"], e["hora"]) for e in agenda["eventos"]}
    disp = agenda["disponibilidad"]
    libres, d = [], hoy + timedelta(days=1)
    while len(libres) < a.slots_libres and d <= hoy + timedelta(days=60):
        if d.weekday() in disp["dias_semana"]:
            for hora in disp["horarios"]:
                if (d.isoformat(), hora) not in ocupados and len(libres) < a.slots_libres:
                    libres.append({"fecha": d.isoformat(), "hora": hora})
        d += timedelta(days=1)
    return {"desde": hoy.isoformat(), "hasta": hasta.isoformat(), "eventos": eventos, "slots_libres": libres}


TipoProyecto = Literal["vivienda", "reforma", "local_comercial", "oficina", "interiorismo"]
Etapa = Literal["anteproyecto", "proyecto_ejecutivo", "direccion_obra"]


class CalcularHonorariosArgs(BaseModel):
    tipo_proyecto: TipoProyecto
    superficie_m2: float = Field(gt=0, le=20000)
    etapas: list[Etapa] = Field(min_length=1)


def calcular_honorarios(ctx: ToolContext, a: CalcularHonorariosArgs) -> dict:
    t = ctx.repo.tarifario
    base_total = t["honorario_por_m2"][a.tipo_proyecto] * a.superficie_m2
    detalle = [{"etapa": e, "porcentaje": t["etapas"][e], "monto": round(base_total * t["etapas"][e], 2)}
               for e in dict.fromkeys(a.etapas)]
    subtotal = round(sum(x["monto"] for x in detalle), 2)
    aplica_minimo = subtotal < t["honorario_minimo"]
    subtotal = max(subtotal, t["honorario_minimo"])
    iva = round(subtotal * t["iva"], 2)
    return {
        "moneda": t["moneda"], "tarifa_m2": t["honorario_por_m2"][a.tipo_proyecto], "detalle": detalle,
        "subtotal": subtotal, "aplica_minimo": aplica_minimo, "iva": iva, "total": round(subtotal + iva, 2),
        "validez_dias": t["validez_dias"], "fuente": t["fuente"],
    }


# ---------------------------------------------------------------- escrituras / efectos
class RegistrarPresupuestoArgs(BaseModel):
    presupuesto_id: str
    cliente: str
    calculo: dict


def registrar_presupuesto(ctx: ToolContext, a: RegistrarPresupuestoArgs) -> dict:
    path = _append_jsonl(ctx, "presupuestos.jsonl", {**a.model_dump(), "estado": "enviado",
                                                       "registrado_en": datetime.now().isoformat()})
    return {"ok": True, "registro": path}


class CrearEventoArgs(BaseModel):
    fecha: date
    hora: str = Field(pattern=r"^\d{2}:\d{2}$")
    titulo: str = Field(min_length=3, max_length=120)
    invitado: str
    proyecto_id: str | None = None


def crear_evento_agenda(ctx: ToolContext, a: CrearEventoArgs) -> dict:
    path = _append_jsonl(ctx, "agenda_nuevos_eventos.jsonl", a.model_dump(mode="json"))
    return {"ok": True, "registro": path}


class EnviarRespuestaArgs(BaseModel):
    canal: Literal["email", "whatsapp", "web", "interno"]
    destinatario: str
    asunto: str = Field(max_length=200)
    cuerpo: str = Field(min_length=20, max_length=6000)
    en_respuesta_a: str


def enviar_respuesta(ctx: ToolContext, a: EnviarRespuestaArgs) -> dict:
    path = _append_jsonl(ctx, "outbox.jsonl", {**a.model_dump(), "enviado_en": datetime.now().isoformat()})
    return {"ok": True, "registro": path}


class DescuentoArgs(BaseModel):
    presupuesto_id: str
    porcentaje: float = Field(gt=0, lt=1)


def no_delegable(ctx: ToolContext, a: DescuentoArgs) -> dict:  # pragma: no cover - bloqueado por policy
    raise PermissionError("acción no delegable")
