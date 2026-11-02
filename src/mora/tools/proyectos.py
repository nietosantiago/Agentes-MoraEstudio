"""Tools del agente de proyectos. Frontera: PROYECTOS = TIEMPO (fecha, hito, entregable)."""
from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field


class ListarObrasArgs(BaseModel):
    solo_activas: bool = True


def listar_obras(ctx, a: ListarObrasArgs) -> dict:
    sql = "SELECT o.*, c.nombre AS cliente FROM obras o LEFT JOIN clientes c ON c.id=o.cliente_id"
    if a.solo_activas:
        sql += " WHERE o.etapa <> 'finalizada'"
    return {"obras": ctx.db.query(sql + " ORDER BY o.entrega_prevista")}


class ConsultarObraArgs(BaseModel):
    obra_id: str = Field(pattern=r"^OBR-\d+$")


def consultar_obra(ctx, a: ConsultarObraArgs) -> dict:
    obra = ctx.db.one("SELECT o.*, c.nombre AS cliente, c.email, c.telefono, c.canal_preferido FROM obras o "
                      "LEFT JOIN clientes c ON c.id=o.cliente_id WHERE o.id=?", (a.obra_id,))
    if not obra:
        raise ValueError(f"obra inexistente: {a.obra_id}")
    hitos = ctx.db.query("SELECT * FROM hitos WHERE obra_id=? ORDER BY fecha", (a.obra_id,))
    for h in hitos:
        h["atrasado"] = h["estado"] != "cumplido" and date.fromisoformat(h["fecha"]) < ctx.hoy
    eventos = ctx.db.query("SELECT * FROM eventos WHERE obra_id=? AND fecha >= ? ORDER BY fecha, hora",
                           (a.obra_id, ctx.hoy.isoformat()))
    return {"obra": obra, "hitos": hitos, "eventos": eventos}


class ProximosHitosArgs(BaseModel):
    dias: int = Field(default=7, ge=1, le=90)
    obra_id: str | None = None


def proximos_hitos(ctx, a: ProximosHitosArgs) -> dict:
    hasta = (ctx.hoy + timedelta(days=a.dias)).isoformat()
    sql = ("SELECT h.*, o.nombre AS obra, o.cliente_id FROM hitos h JOIN obras o ON o.id=h.obra_id "
           "WHERE h.estado <> 'cumplido' AND h.fecha <= ?")
    params: list = [hasta]
    if a.obra_id:
        sql += " AND h.obra_id=?"
        params.append(a.obra_id)
    rows = ctx.db.query(sql + " ORDER BY h.fecha", params)
    hoy = ctx.hoy.isoformat()
    eventos = ctx.db.query("SELECT * FROM eventos WHERE fecha >= ? AND fecha <= ? ORDER BY fecha, hora", (hoy, hasta))
    return {"desde": hoy, "hasta": hasta,
            "atrasados": [r for r in rows if r["fecha"] < hoy],
            "proximos": [r for r in rows if r["fecha"] >= hoy], "eventos": eventos}


class ActualizarHitoArgs(BaseModel):
    hito_id: str = Field(pattern=r"^HIT-\d+$")
    estado: Literal["pendiente", "en_curso", "cumplido", "atrasado"] | None = None
    fecha: date | None = None
    notas: str | None = Field(default=None, max_length=300)


def actualizar_hito(ctx, a: ActualizarHitoArgs) -> dict:
    h = ctx.db.one("SELECT * FROM hitos WHERE id=?", (a.hito_id,))
    if not h:
        raise ValueError(f"hito inexistente: {a.hito_id}")
    ctx.db.execute("UPDATE hitos SET estado=?, fecha=?, notas=? WHERE id=?",
                   (a.estado or h["estado"], (a.fecha.isoformat() if a.fecha else h["fecha"]),
                    a.notas if a.notas is not None else h["notas"], a.hito_id))
    return {"hito_id": a.hito_id, "antes": {"estado": h["estado"], "fecha": h["fecha"]},
            "despues": {"estado": a.estado or h["estado"], "fecha": a.fecha.isoformat() if a.fecha else h["fecha"]}}


class AgendarEventoArgs(BaseModel):
    fecha: date
    hora: str = Field(pattern=r"^\d{2}:\d{2}$")
    titulo: str = Field(min_length=3, max_length=120)
    obra_id: str | None = None
    invitado: str | None = None


def agendar_evento(ctx, a: AgendarEventoArgs) -> dict:
    eid = "EV-" + hashlib.sha1(f"{a.fecha}{a.hora}{a.titulo}".encode()).hexdigest()[:6].upper()
    ctx.db.insert("eventos", {"id": eid, "fecha": a.fecha.isoformat(), "hora": a.hora, "titulo": a.titulo,
                              "obra_id": a.obra_id, "invitado": a.invitado, "origen": "agente_proyectos"},
                  on_conflict_nothing=True)
    return {"evento_id": eid, "nota": "calendario simulado: tabla eventos"}
