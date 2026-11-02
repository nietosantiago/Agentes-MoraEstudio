"""Tools del agente comercial: leads, calificación y mensajes."""
from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..text import norm

ZONA_LOCAL = {"santa fe", "santo tome", "sauce viejo", "recreo", "san jose del rincon", "colastine"}
ZONA_CERCANA = {"parana", "esperanza", "rafaela", "rosario"}
TIPOS_ATENDIDOS = {"cocina", "living", "dormitorio", "bano", "comedor", "oficina", "local", "integral",
                   "departamento", "casa"}


class SinArgs(BaseModel):
    pass


class BuscarContactoArgs(BaseModel):
    texto: str = Field(min_length=2, max_length=120)


def buscar_contacto(ctx, a: BuscarContactoArgs) -> dict:
    q = norm(a.texto).strip()
    out = []
    for c in ctx.db.query("SELECT * FROM clientes"):
        if q in norm(c["nombre"]) or q in norm(c.get("email") or "") or norm(c["nombre"]).strip() in norm(a.texto):
            out.append({"tipo": "cliente", **c})
    for l in ctx.db.query("SELECT * FROM leads"):
        if q in norm(l["nombre"]) or q in norm(l.get("contacto") or "") or norm(l["nombre"]).strip() in norm(a.texto):
            out.append({"tipo": "lead", **l})
    return {"resultados": out}


class ListarLeadsArgs(BaseModel):
    estado: str | None = None
    sin_contacto_dias: int | None = Field(default=None, ge=0, le=365)


def listar_leads(ctx, a: ListarLeadsArgs) -> dict:
    leads = []
    for l in ctx.db.query("SELECT * FROM leads ORDER BY creado"):
        ref = l["ultimo_contacto"] or l["creado"]
        l["dias_sin_contacto"] = (ctx.hoy - date.fromisoformat(ref)).days
        if a.estado and l["estado"] != a.estado:
            continue
        if a.sin_contacto_dias is not None and (l["dias_sin_contacto"] < a.sin_contacto_dias
                                                or l["estado"] in ("ganado", "perdido")):
            continue
        leads.append(l)
    return {"leads": leads}


class CalificarLeadArgs(BaseModel):
    ciudad: str | None = None
    tipo_proyecto: str | None = None
    presupuesto_estimado: float | None = Field(default=None, ge=0)


def calificar_lead(ctx, a: CalificarLeadArgs) -> dict:
    puntos, motivos = 0.0, []
    ciudad = norm(a.ciudad or "").strip()
    if ciudad in ZONA_LOCAL:
        puntos += 2; motivos.append("zona de trabajo presencial")
    elif ciudad in ZONA_CERCANA:
        puntos += 1; motivos.append("zona cercana (presencial con viáticos u online)")
    else:
        motivos.append("zona desconocida o lejana: ofrecer servicio online")
    minimo = ctx.db.one("SELECT precio FROM servicios WHERE codigo='PRY-AMB'")["precio"]
    if a.presupuesto_estimado is None:
        puntos += 0.5; motivos.append("sin presupuesto declarado")
    elif a.presupuesto_estimado >= minimo:
        puntos += 2; motivos.append("presupuesto acorde a un proyecto")
    else:
        motivos.append("presupuesto por debajo de un proyecto: ofrecer asesoría")
    if a.tipo_proyecto and norm(a.tipo_proyecto).strip() in TIPOS_ATENDIDOS:
        puntos += 1; motivos.append("tipo de proyecto que el estudio atiende")
    cal = "A" if puntos >= 4 else "B" if puntos >= 2 else "C"
    servicio = {"A": "ASE-DOM", "B": "ASE-DOM" if ciudad in ZONA_LOCAL else "ASE-ONL", "C": "ASE-ONL"}[cal]
    return {"calificacion": cal, "puntos": puntos, "motivos": motivos, "servicio_sugerido": servicio}


def consultar_servicios(ctx, a: SinArgs) -> dict:
    return {"servicios": ctx.db.query("SELECT codigo, nombre, descripcion FROM servicios ORDER BY codigo")}


class RegistrarLeadArgs(BaseModel):
    nombre: str = Field(min_length=2)
    canal: Literal["instagram", "whatsapp", "email", "web", "otro"]
    contacto: str | None = None
    ciudad: str | None = None
    tipo_proyecto: str | None = None
    presupuesto_estimado: float | None = None
    mensaje: str | None = None
    calificacion: Literal["A", "B", "C"] | None = None
    lead_id: str | None = None


def lead_id_para(nombre: str, contacto: str | None) -> str:
    return "LEAD-" + hashlib.sha1(norm(f"{nombre} {contacto or ''}").encode()).hexdigest()[:6].upper()


def registrar_lead(ctx, a: RegistrarLeadArgs) -> dict:
    lid = a.lead_id or lead_id_para(a.nombre, a.contacto)
    if ctx.db.one("SELECT id FROM leads WHERE id=?", (lid,)):
        ctx.db.execute("UPDATE leads SET calificacion=COALESCE(?, calificacion), estado='calificado' WHERE id=?",
                       (a.calificacion, lid))
        return {"lead_id": lid, "accion": "actualizado"}
    ctx.db.insert("leads", {"id": lid, "nombre": a.nombre, "canal": a.canal, "contacto": a.contacto,
                            "ciudad": a.ciudad, "tipo_proyecto": a.tipo_proyecto,
                            "presupuesto_estimado": a.presupuesto_estimado, "mensaje": a.mensaje,
                            "estado": "calificado" if a.calificacion else "nuevo", "calificacion": a.calificacion,
                            "creado": ctx.hoy.isoformat(), "ultimo_contacto": None})
    return {"lead_id": lid, "accion": "creado"}


class EnviarMensajeArgs(BaseModel):
    destinatario: str = Field(min_length=3)
    canal: Literal["instagram", "whatsapp", "email", "web", "otro"]
    asunto: str = Field(default="", max_length=150)
    cuerpo: str = Field(min_length=20, max_length=3000)
    motivo: str = Field(max_length=120)
    lead_id: str | None = None
    cliente_id: str | None = None


def guardar_mensaje(ctx, destinatario, canal, asunto, cuerpo, motivo, key: str) -> str:
    mid = "MSG-" + hashlib.sha1(key.encode()).hexdigest()[:8].upper()
    ctx.db.insert("mensajes_salientes", {"id": mid, "destinatario": destinatario, "canal": canal, "asunto": asunto,
                                         "cuerpo": cuerpo, "motivo": motivo,
                                         "enviado_en": datetime.now().isoformat(timespec="seconds")},
                  on_conflict_nothing=True)
    return mid


def enviar_mensaje(ctx, a: EnviarMensajeArgs) -> dict:
    mid = guardar_mensaje(ctx, a.destinatario, a.canal, a.asunto, a.cuerpo, a.motivo,
                          f"{a.destinatario}|{a.cuerpo}")
    if a.lead_id:
        ctx.db.execute("UPDATE leads SET ultimo_contacto=?, estado=CASE WHEN estado='nuevo' THEN 'contactado' "
                       "ELSE estado END WHERE id=?", (ctx.hoy.isoformat(), a.lead_id))
    return {"mensaje_id": mid, "canal": a.canal, "nota": "envío simulado: queda en mensajes_salientes"}
