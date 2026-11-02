"""Agente administrativo. FRONTERA: ADMINISTRATIVO = PLATA (presupuesto, factura, cobro)."""
from __future__ import annotations

import calendar
import re
from datetime import date

from ..contracts import Operacion
from ..text import MESES, ars, mes_mencionado, norm, parse_monto, tiene
from .base import AgenteBase, EntradaAgente
from .comercial import FIRMA

AMBIENTES = ["cocina", "living", "dormitorio", "bano", "comedor", "escritorio", "toilette", "lavadero"]


def extraer_items(texto: str) -> list[dict]:
    t, low = norm(texto), texto.lower()
    items = []
    if tiene(t, "asesoria online", "asesoria virtual"):
        items.append({"servicio": "ASE-ONL", "cantidad": 1})
    elif tiene(t, "asesoria"):
        items.append({"servicio": "ASE-DOM", "cantidad": 1})
    m2 = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:m2|m²|metros)", low)
    if tiene(t, "integral") or (m2 and not tiene(t, "ambiente")):
        if m2:
            items.append({"servicio": "PRY-INT", "cantidad": float(m2.group(1).replace(",", "."))})
    else:
        n = re.search(r"(\d+)\s*ambientes?", low)
        cant = int(n.group(1)) if n else sum(1 for a in AMBIENTES if tiene(t, a))
        if cant or tiene(t, "proyecto"):
            items.append({"servicio": "PRY-AMB", "cantidad": max(cant, 1)})
    r = re.search(r"(\d+)\s*renders?", low)
    if r:
        items.append({"servicio": "REN-ADI", "cantidad": int(r.group(1))})
    s = re.search(r"seguimiento(?: de obra)?(?: (?:de|por))?\s*(\d+)\s*mes", low)
    if s:
        items.append({"servicio": "DIR-OBR", "cantidad": int(s.group(1))})
    return items


class AgenteAdministrativo(AgenteBase):
    nombre = "administrativo"
    frontera = ("Tu dominio es la PLATA: presupuestos, precios, facturas, cobros, señas y saldos. "
                "NO cambiás fechas ni hitos de obra (eso es del agente de proyectos). Los precios salen SOLO de "
                "la tabla de servicios; nunca ofrecés descuentos.")

    def marca_breve(self) -> str:  # progressive disclosure: este agente necesita los criterios de presupuesto
        return self.deps.marca.body + "\n\n" + self.deps.marca.reference("criterios_presupuesto.md")

    def local(self, e: EntradaAgente):
        t = norm(e.texto)
        cliente = self.cliente_en_texto(e)
        emitir = tiene(t, "facturale", "facturar", "factura a", "emiti", "emitir", "hace la factura", "hacele la factura")
        if tiene(t, "cuanto facture", "facturacion", "facture", "facturado", "cuanto gane", "ingrese") and not emitir:
            return self._resumen(e)
        if tiene(t, "recordatorio", "recordale", "reclamale", "recorda", "mandale un aviso de pago"):
            return self._recordatorio(e, cliente)
        if emitir or (tiene(t, "factura") and cliente and not tiene(t, "cuanto")):
            return self._factura(e, cliente)
        if tiene(t, "me pago", "pago el", "cobre", "registra el pago", "registra el cobro", "transfirio", "me transfirio"):
            return self._registrar_cobro(e, cliente)
        if tiene(t, "me debe", "me deben", "cobros pendientes", "pendientes de cobro", "deuda", "quien me debe",
                 "cuando me paga", "cuando cobro", "saldo"):
            return self._pendientes(cliente)
        if tiene(t, "presupuest", "cotiz"):
            return self._presupuesto(e, cliente)
        if tiene(t, "precio", "cuanto cobro", "cuanto sale", "lista de precios", "honorario"):
            r = self.tool("consultar_precios")
            filas = [f"- {s['nombre']}: {ars(s['precio'])} por {s['unidad']}" for s in r.get("servicios", [])]
            return self.resultado("Lista de precios vigente:\n" + "\n".join(filas))
        return self.resultado("¿Qué necesitás de administración? Puedo armar un presupuesto, emitir una factura, "
                              "ver cobros pendientes, mandar un recordatorio o decirte cuánto facturaste.")

    def _resumen(self, e):
        hoy = self.deps.settings.hoy
        y, m = mes_mencionado(e.texto, hoy) or (hoy.year, hoy.month)
        desde, hasta = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
        r = self.tool("resumen_facturacion", desde=desde.isoformat(), hasta=hasta.isoformat())
        if "error" in r:
            return self.resultado(f"No pude calcular la facturación: {r['error']}")
        detalle = "\n".join(f"- {c}: {ars(v)}" for c, v in r["por_cliente"].items()) or "- sin facturas"
        return self.resultado(f"En {MESES[m - 1]} {y} facturaste **{ars(r['total'])}** en {r['cantidad']} "
                              f"factura(s):\n{detalle}", resumen=r)

    def _pendientes(self, cliente):
        r = self.tool("cobros_pendientes", cliente_id=cliente["id"] if cliente else None)
        filas = [f"- {c['cliente']}: {c['concepto']} — {ars(c['monto'])}, vence {c['vencimiento']}"
                 + (f" (**vencido hace {c['dias_vencido']} días**)" if c["dias_vencido"] > 0 else "")
                 for c in r.get("cobros", [])]
        return self.resultado(f"Cobros pendientes: {ars(r.get('total', 0))}\n" + ("\n".join(filas) or "- ninguno"),
                              cobros=r.get("cobros", []))

    def _recordatorio(self, e, cliente):
        r = self.tool("cobros_pendientes", cliente_id=cliente["id"] if cliente else None)
        cobros = r.get("cobros", [])
        if not cliente:
            cobros = [c for c in cobros if c["dias_vencido"] > 0]
        if not cobros:
            return self.resultado("No encontré cobros pendientes" + (f" de {cliente['nombre']}." if cliente else " vencidos."))
        ops, omitidos = [], []
        for c in cobros:
            ult = c.get("ultimo_recordatorio")
            if ult and (self.deps.settings.hoy - date.fromisoformat(ult)).days < 7:
                omitidos.append(f"{c['cliente']} (recordatorio enviado el {ult})")
                continue
            dest = c["email"] if c["canal_preferido"] == "email" else c["telefono"]
            estado = (f"venció el {c['vencimiento']}" if c["dias_vencido"] > 0 else f"vence el {c['vencimiento']}")
            cuerpo = (f"Hola {c['cliente'].split()[0]}! ¿Cómo estás? Te escribo para recordarte el pago de "
                      f"{c['concepto'].lower()} por {ars(c['monto'])}, que {estado}. Cualquier cosa me avisás. "
                      f"¡Gracias!\n\n{FIRMA}")
            ops.append(Operacion(tool="enviar_recordatorio_cobro", descripcion=f"Recordar a {c['cliente']} {ars(c['monto'])}",
                                 args={"cobro_id": c["id"], "destinatario": dest, "canal": c["canal_preferido"],
                                       "cuerpo": cuerpo}))
        nota = f"\nNo incluí: {', '.join(omitidos)} — regla de 7 días entre recordatorios." if omitidos else ""
        if not ops:
            return self.resultado("Todos los cobros tienen un recordatorio reciente." + nota)
        accion = self.proponer(e, f"Enviar {len(ops)} recordatorio(s) de pago", ops, "Cobros pendientes según la base.")
        return self.resultado(f"Preparé {len(ops)} recordatorio(s) de pago con tono amable.{nota}", accion)

    def _factura(self, e, cliente):
        if not cliente:
            return self.resultado("¿A qué cliente le facturo? Decime el nombre.")
        r = self.tool("cobros_pendientes", cliente_id=cliente["id"])
        sin_factura = [c for c in r.get("cobros", []) if not c["factura_numero"]]
        monto = parse_monto(e.texto)
        cobro = sin_factura[0] if sin_factura else None
        if cobro is None and monto is None:
            return self.resultado(f"{cliente['nombre']} no tiene cobros pendientes sin facturar. "
                                  "Si querés facturar otro concepto, decime monto y concepto.")
        args = {"cliente_id": cliente["id"], "monto": monto or cobro["monto"],
                "concepto": f"{cobro['concepto']} — {cobro['presupuesto_id'] or 'servicios de interiorismo'}" if cobro
                else "Servicios de interiorismo", "cobro_id": cobro["id"] if cobro else None,
                "presupuesto_id": cobro["presupuesto_id"] if cobro else None}
        op = Operacion(tool="emitir_factura", args=args, descripcion=f"Factura C a {cliente['nombre']} por {ars(args['monto'])}")
        accion = self.proponer(e, f"Emitir factura C a {cliente['nombre']} por {ars(args['monto'])}", [op],
                               "Factura vinculada al cobro pendiente." if cobro else "Factura por monto indicado.")
        return self.resultado(f"Te preparé la factura C para {cliente['nombre']}: {args['concepto']}, "
                              f"{ars(args['monto'])}. Es irreversible: revisala bien antes de aprobar.", accion)

    def _registrar_cobro(self, e, cliente):
        if not cliente:
            return self.resultado("¿Quién te pagó? Decime el nombre del cliente.")
        r = self.tool("cobros_pendientes", cliente_id=cliente["id"])
        if not r.get("cobros"):
            return self.resultado(f"{cliente['nombre']} no tiene cobros pendientes.")
        c = r["cobros"][0]
        op = Operacion(tool="registrar_cobro", args={"cobro_id": c["id"], "fecha": self.deps.settings.hoy.isoformat()},
                       descripcion=f"Marcar cobrado: {c['concepto']} de {cliente['nombre']} ({ars(c['monto'])})")
        extra = "" if c["factura_numero"] else " Ojo: todavía no tiene factura; pedime que la emita."
        return self.resultado(f"Registro el cobro de {ars(c['monto'])} ({c['concepto']}).{extra}",
                              self.proponer(e, f"Registrar cobro de {cliente['nombre']}", [op]))

    def _presupuesto(self, e, cliente):
        items = extraer_items(e.texto)
        if not items:
            return self.resultado("¿Qué incluyo en el presupuesto? Por ejemplo: '2 ambientes', 'proyecto integral "
                                  "de 80 m2', 'asesoría', '3 renders', 'seguimiento de obra 2 meses'.")
        calc = self.tool("calcular_presupuesto", items=items)
        if "error" in calc:
            return self.resultado(f"No pude calcular el presupuesto: {calc['error']}")
        lineas = "\n".join(f"- {l['nombre']} × {l['cantidad']:g}: {ars(l['importe'])}" for l in calc["lineas"])
        detalle = (f"{lineas}\nTotal: **{ars(calc['total'])}** (seña 50%: {ars(calc['sena_50'])}, "
                   f"saldo: {ars(calc['saldo_50'])}). Validez {calc['validez_dias']} días.")
        destino, lead = None, None
        if cliente:
            destino = (cliente["email"] if cliente["canal_preferido"] == "email" else cliente["telefono"],
                       cliente["canal_preferido"], cliente["nombre"])
        else:
            m = re.search(r"(?:a|para)\s+([A-ZÁÉÍÓÚ][a-záéíóúñ]+(?:\s[A-ZÁÉÍÓÚ][a-záéíóúñ]+)?)", e.texto)
            if m:
                res = self.tool("buscar_contacto", texto=m.group(1)).get("resultados", [])
                lead = next((x for x in res if x["tipo"] == "lead"), None)
                if lead:
                    destino = (lead["contacto"], lead["canal"], lead["nombre"])
        if not destino:
            return self.resultado(f"Presupuesto calculado:\n{detalle}\n\n¿A quién se lo envío?", calculo=calc)
        n = len(self.deps.db.query("SELECT id FROM presupuestos")) + 1
        pid = f"PRE-{self.deps.settings.hoy.year}-{40 + n:03d}"
        cuerpo = (f"Hola {destino[2].split()[0]}! Te comparto el presupuesto {pid}:\n{lineas}\n"
                  f"Total: {ars(calc['total'])}. Forma de pago: 50% de seña al aprobar y 50% contra entrega. "
                  f"Validez: {calc['validez_dias']} días. ¿Lo charlamos?\n\n{FIRMA}")
        op = Operacion(tool="enviar_presupuesto", descripcion=f"Enviar {pid} a {destino[2]} por {destino[1]}",
                       args={"presupuesto_id": pid, "cliente_id": cliente["id"] if cliente else None,
                             "lead_id": lead["id"] if lead else None, "destinatario": destino[0], "canal": destino[1],
                             "items": items, "total": calc["total"], "cuerpo": cuerpo})
        accion = self.proponer(e, f"Enviar presupuesto {pid} a {destino[2]} ({ars(calc['total'])})", [op],
                               "Montos calculados con la tabla de precios vigente.")
        return self.resultado(f"Presupuesto para {destino[2]}:\n{detalle}", accion, calculo=calc)
