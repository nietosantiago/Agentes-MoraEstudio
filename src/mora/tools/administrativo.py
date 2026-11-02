"""Tools del agente administrativo. Frontera: ADMINISTRATIVO = PLATA (presupuesto, factura, cobro)."""
from __future__ import annotations

import json
from datetime import date, timedelta

from pydantic import BaseModel, Field

from ..integrations.facturacion import FacturacionError
from .comercial import guardar_mensaje
from .registry import PolicyError


class PreciosArgs(BaseModel):
    codigo: str | None = None


def consultar_precios(ctx, a: PreciosArgs) -> dict:
    if a.codigo:
        rows = ctx.db.query("SELECT * FROM servicios WHERE codigo=?", (a.codigo,))
        if not rows:
            raise ValueError(f"servicio inexistente: {a.codigo}")
    else:
        rows = ctx.db.query("SELECT * FROM servicios ORDER BY codigo")
    return {"moneda": "ARS", "servicios": rows}


class ItemPresupuesto(BaseModel):
    servicio: str
    cantidad: float = Field(gt=0, le=10000)


class CalcularPresupuestoArgs(BaseModel):
    items: list[ItemPresupuesto] = Field(min_length=1, max_length=10)


def calcular_presupuesto(ctx, a: CalcularPresupuestoArgs) -> dict:
    lineas, total = [], 0.0
    for it in a.items:
        s = ctx.db.one("SELECT * FROM servicios WHERE codigo=?", (it.servicio,))
        if not s:
            raise ValueError(f"servicio inexistente: {it.servicio}")
        cantidad = 1 if s["unidad"] == "fijo" else it.cantidad
        importe = max(s["precio"] * cantidad, s["minimo"] or 0)
        lineas.append({"servicio": s["codigo"], "nombre": s["nombre"], "unidad": s["unidad"], "cantidad": cantidad,
                       "precio_unitario": s["precio"], "importe": round(importe, 2),
                       "aplica_minimo": importe > s["precio"] * cantidad})
        total += importe
    total = round(total, 2)
    return {"moneda": "ARS", "lineas": lineas, "total": total, "sena_50": round(total / 2, 2),
            "saldo_50": round(total - round(total / 2, 2), 2), "validez_dias": 15,
            "nota": "Factura C (monotributo): precios finales, sin IVA discriminado."}


class ResumenFacturacionArgs(BaseModel):
    desde: date
    hasta: date


def resumen_facturacion(ctx, a: ResumenFacturacionArgs) -> dict:
    if a.hasta < a.desde:
        raise ValueError("'hasta' es anterior a 'desde'")
    rows = ctx.db.query("SELECT f.*, c.nombre AS cliente FROM facturas f LEFT JOIN clientes c ON c.id=f.cliente_id "
                        "WHERE f.fecha >= ? AND f.fecha <= ? ORDER BY f.fecha",
                        (a.desde.isoformat(), a.hasta.isoformat()))
    por_cliente: dict[str, float] = {}
    for r in rows:
        por_cliente[r["cliente"] or r["cliente_id"]] = por_cliente.get(r["cliente"] or r["cliente_id"], 0) + r["monto"]
    return {"desde": a.desde.isoformat(), "hasta": a.hasta.isoformat(), "cantidad": len(rows),
            "total": round(sum(r["monto"] for r in rows), 2), "por_cliente": por_cliente, "facturas": rows}


class CobrosPendientesArgs(BaseModel):
    cliente_id: str | None = None


def cobros_pendientes(ctx, a: CobrosPendientesArgs) -> dict:
    sql = ("SELECT b.*, c.nombre AS cliente, c.email, c.telefono, c.canal_preferido FROM cobros b "
           "JOIN clientes c ON c.id=b.cliente_id WHERE b.estado='pendiente'")
    params: tuple = ()
    if a.cliente_id:
        sql += " AND b.cliente_id=?"
        params = (a.cliente_id,)
    rows = ctx.db.query(sql + " ORDER BY b.vencimiento", params)
    for r in rows:
        r["dias_vencido"] = (ctx.hoy - date.fromisoformat(r["vencimiento"])).days
    return {"cobros": rows, "total": round(sum(r["monto"] for r in rows), 2),
            "vencidos": [r["id"] for r in rows if r["dias_vencido"] > 0]}


class EnviarPresupuestoArgs(BaseModel):
    presupuesto_id: str
    cliente_id: str | None = None
    lead_id: str | None = None
    destinatario: str
    canal: str
    items: list[ItemPresupuesto]
    total: float = Field(gt=0)
    cuerpo: str = Field(min_length=20, max_length=3000)


def enviar_presupuesto(ctx, a: EnviarPresupuestoArgs) -> dict:
    ctx.db.insert("presupuestos", {"id": a.presupuesto_id, "cliente_id": a.cliente_id, "lead_id": a.lead_id,
                                   "fecha": ctx.hoy.isoformat(), "items": [i.model_dump() for i in a.items],
                                   "total": a.total, "estado": "enviado", "validez_dias": 15},
                  on_conflict_nothing=True)
    mid = guardar_mensaje(ctx, a.destinatario, a.canal, f"Presupuesto {a.presupuesto_id}", a.cuerpo,
                          "envio_presupuesto", f"pres|{a.presupuesto_id}")
    if a.lead_id:
        ctx.db.execute("UPDATE leads SET estado='presupuestado', ultimo_contacto=? WHERE id=?",
                       (ctx.hoy.isoformat(), a.lead_id))
    return {"presupuesto_id": a.presupuesto_id, "mensaje_id": mid}


class EmitirFacturaArgs(BaseModel):
    cliente_id: str
    concepto: str = Field(min_length=3, max_length=200)
    monto: float = Field(gt=0)
    cobro_id: str | None = None
    presupuesto_id: str | None = None


def pre_emitir_factura(ctx, a: EmitirFacturaArgs) -> None:
    """Regla de negocio re-validada al ejecutar: no facturar dos veces el mismo cobro ni de más."""
    if not ctx.db.one("SELECT id FROM clientes WHERE id=?", (a.cliente_id,)):
        raise PolicyError(f"cliente inexistente: {a.cliente_id}")
    if a.cobro_id:
        c = ctx.db.one("SELECT * FROM cobros WHERE id=?", (a.cobro_id,))
        if not c:
            raise PolicyError(f"cobro inexistente: {a.cobro_id}")
        if c["factura_numero"]:
            raise PolicyError(f"el cobro {a.cobro_id} ya tiene factura {c['factura_numero']}")
        if a.monto > c["monto"] + 0.01:
            raise PolicyError(f"monto {a.monto} supera el cobro {c['monto']}")


def emitir_factura(ctx, a: EmitirFacturaArgs) -> dict:
    cli = ctx.db.one("SELECT * FROM clientes WHERE id=?", (a.cliente_id,))
    try:
        comp = ctx.facturacion.emitir(cuit_receptor=cli.get("cuit"), concepto=a.concepto, monto=a.monto,
                                      idempotency_key=f"{a.cliente_id}|{a.cobro_id}|{a.monto}")
    except FacturacionError as exc:
        raise RuntimeError(f"facturación: {exc}") from exc
    ctx.db.insert("facturas", {"numero": comp.numero, "cliente_id": a.cliente_id, "fecha": ctx.hoy.isoformat(),
                               "concepto": a.concepto, "monto": a.monto, "tipo": comp.tipo, "cae": comp.cae,
                               "proveedor": comp.proveedor, "presupuesto_id": a.presupuesto_id})
    if a.cobro_id:
        ctx.db.execute("UPDATE cobros SET factura_numero=? WHERE id=?", (comp.numero, a.cobro_id))
    return comp.model_dump()


class RecordatorioArgs(BaseModel):
    cobro_id: str
    destinatario: str
    canal: str
    cuerpo: str = Field(min_length=20, max_length=2000)


def pre_recordatorio(ctx, a: RecordatorioArgs) -> None:
    c = ctx.db.one("SELECT * FROM cobros WHERE id=?", (a.cobro_id,))
    if not c or c["estado"] != "pendiente":
        raise PolicyError(f"el cobro {a.cobro_id} no está pendiente")
    if c["ultimo_recordatorio"] and ctx.hoy - date.fromisoformat(c["ultimo_recordatorio"]) < timedelta(days=7):
        raise PolicyError(f"ya se envió un recordatorio el {c['ultimo_recordatorio']} (mínimo 7 días)")


def enviar_recordatorio_cobro(ctx, a: RecordatorioArgs) -> dict:
    mid = guardar_mensaje(ctx, a.destinatario, a.canal, "Recordatorio de pago", a.cuerpo, "recordatorio_cobro",
                          f"rec|{a.cobro_id}|{ctx.hoy.isoformat()}")
    ctx.db.execute("UPDATE cobros SET ultimo_recordatorio=? WHERE id=?", (ctx.hoy.isoformat(), a.cobro_id))
    return {"mensaje_id": mid}


class RegistrarCobroArgs(BaseModel):
    cobro_id: str
    fecha: date


def registrar_cobro(ctx, a: RegistrarCobroArgs) -> dict:
    n = ctx.db.execute("UPDATE cobros SET estado='cobrado', cobrado_en=? WHERE id=? AND estado='pendiente'",
                       (a.fecha.isoformat(), a.cobro_id))
    if not n:
        raise ValueError(f"el cobro {a.cobro_id} no existe o ya estaba cobrado")
    return {"cobro_id": a.cobro_id, "estado": "cobrado"}


class DescuentoArgs(BaseModel):
    presupuesto_id: str
    porcentaje: float = Field(gt=0, lt=1)


def no_delegable(ctx, a) -> dict:  # pragma: no cover - la policy lo bloquea antes
    raise PolicyError("acción no delegable")


def items_json(items: str | list) -> list:
    return json.loads(items) if isinstance(items, str) else items
