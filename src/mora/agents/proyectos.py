"""Agente de gestión de proyectos. FRONTERA: PROYECTOS = TIEMPO (fecha, hito, entregable)."""
from __future__ import annotations

from ..contracts import Operacion
from ..text import fecha_corta, norm, parse_fecha, parse_hora, tiene
from .base import AgenteBase, EntradaAgente
from .comercial import FIRMA

PALABRAS_HITO = ["mueble", "cocina", "render", "planta", "equipamiento", "revestimiento", "entrega", "moodboard",
                 "relevamiento", "medida", "lista de compras", "instalacion", "documentacion"]


class AgenteProyectos(AgenteBase):
    nombre = "proyectos"
    frontera = ("Tu dominio es el TIEMPO de las obras: fechas, hitos, entregables, plazos, atrasos, visitas y "
                "proveedores. NO tocás presupuestos, facturas ni cobros (eso es del agente administrativo).")

    def _obra(self, e) -> dict | None:
        cliente = self.cliente_en_texto(e)
        obras = self.tool("listar_obras", solo_activas=False).get("obras", [])
        if cliente:
            activas = [o for o in obras if o["cliente_id"] == cliente["id"]]
            return next((o for o in activas if o["etapa"] != "finalizada"), activas[0] if activas else None)
        t = norm(e.texto)
        return next((o for o in obras if any(f" {p} " in t for p in norm(o["nombre"]).split() if len(p) > 4)), None)

    def _hito(self, hitos: list[dict], t: str) -> dict | None:
        candidatos = [h for h in hitos if h["estado"] != "cumplido"]
        for p in PALABRAS_HITO:
            if tiene(t, p):
                match = [h for h in candidatos if norm(p).strip() in norm(h["nombre"])]
                if match:
                    return match[0]
        return candidatos[0] if len(candidatos) == 1 else None

    def local(self, e: EntradaAgente):
        t, hoy = norm(e.texto), self.deps.settings.hoy
        obra = self._obra(e)
        cambio = tiene(t, "atras", "demor", "reprogram", "mover", "pasa al", "pasala", "cambia la fecha", "posterg", "corre")
        cumplido = tiene(t, "cumplid", "termine", "terminado", "ya entregue", "listo el", "lista la", "completad", "marca como hecho")
        agenda = tiene(t, "agenda", "agendame", "agendar", "coordina una visita", "programa una visita", "reunion con")
        if (cambio or cumplido) and obra:
            return self._actualizar(e, obra, cambio, cumplido)
        if agenda and obra:
            return self._agendar(e, obra)
        if obra and tiene(t, "como va", "estado", "avance", "como viene", "situacion"):
            r = self.tool("consultar_obra", obra_id=obra["id"])
            hitos = "\n".join(f"- {fecha_corta(h['fecha'])}: {h['nombre']} — {h['estado']}"
                              + (" ⚠ atrasado" if h["atrasado"] else "") for h in r.get("hitos", []))
            return self.resultado(f"**{obra['nombre']}** (etapa: {obra['etapa']}, entrega prevista "
                                  f"{fecha_corta(obra['entrega_prevista'])}):\n{hitos}", obra=r)
        dias = 30 if tiene(t, "mes") else 15 if tiene(t, "quincena", "dos semanas") else 7
        r = self.tool("proximos_hitos", dias=dias, obra_id=obra["id"] if obra and tiene(t, "de") else None)
        at = [f"- ⚠ {fecha_corta(h['fecha'])}: {h['nombre']} ({h['obra']}) — atrasado" for h in r.get("atrasados", [])]
        px = [f"- {fecha_corta(h['fecha'])}: {h['nombre']} ({h['obra']}, {h['tipo']})" for h in r.get("proximos", [])]
        ev = [f"- {fecha_corta(v['fecha'])} {v['hora']}: {v['titulo']}" for v in r.get("eventos", [])]
        partes = [f"Próximos {dias} días:"] + (at + px or ["- sin hitos ni entregables"])
        if ev:
            partes += ["", "Agenda:"] + ev
        return self.resultado("\n".join(partes), hitos=r)

    def _actualizar(self, e, obra, cambio, cumplido):
        r = self.tool("consultar_obra", obra_id=obra["id"])
        hito = self._hito(r.get("hitos", []), norm(e.texto))
        if not hito:
            nombres = ", ".join(h["nombre"] for h in r.get("hitos", []) if h["estado"] != "cumplido")
            return self.resultado(f"¿Qué hito de {obra['nombre']}? Pendientes: {nombres}.")
        hoy = self.deps.settings.hoy
        nueva = parse_fecha(e.texto, hoy) if cambio else None
        args = {"hito_id": hito["id"]}
        if cumplido:
            args["estado"] = "cumplido"
            desc = f"Marcar '{hito['nombre']}' como cumplido"
        else:
            args["estado"] = "pendiente" if nueva else "atrasado"
            if nueva:
                args["fecha"] = nueva.isoformat()
            args["notas"] = f"Reprogramado desde {hito['fecha']}" if nueva else "Atrasado: falta nueva fecha"
            desc = (f"Mover '{hito['nombre']}' del {fecha_corta(hito['fecha'])} al {fecha_corta(nueva.isoformat())}"
                    if nueva else f"Marcar '{hito['nombre']}' como atrasado")
        ops = [Operacion(tool="actualizar_hito", args=args, descripcion=desc)]
        if tiene(norm(e.texto), "avisa", "avisale", "contale", "informa") and r["obra"].get("cliente"):
            o = r["obra"]
            dest = o["email"] if o["canal_preferido"] == "email" else o["telefono"]
            detalle = (f"la fecha de {hito['nombre'].lower()} pasa al {fecha_corta(nueva.isoformat())}" if nueva
                       else f"{hito['nombre'].lower()} viene con demora; te confirmo la nueva fecha apenas la tenga")
            cuerpo = (f"Hola {o['cliente'].split()[0]}! Te cuento una novedad de la obra: {detalle}. "
                      f"El resto del cronograma sigue en marcha. Cualquier duda, escribime.\n\n{FIRMA}")
            ops.append(Operacion(tool="enviar_mensaje", descripcion=f"Avisar a {o['cliente']} por {o['canal_preferido']}",
                                 args={"destinatario": dest, "canal": o["canal_preferido"], "asunto": "Novedad de tu obra",
                                       "cuerpo": cuerpo, "motivo": "aviso_obra", "cliente_id": o["cliente_id"]}))
        falta = "" if (nueva or cumplido) else " No me dijiste la nueva fecha: lo marco como atrasado."
        return self.resultado(f"{desc}.{falta}", self.proponer(e, desc, ops, f"Obra {obra['nombre']}."))

    def _agendar(self, e, obra):
        hoy = self.deps.settings.hoy
        f, h = parse_fecha(e.texto, hoy), parse_hora(e.texto)
        if not f or not h:
            return self.resultado("¿Para qué día y hora la agendo? (por ejemplo: 'el jueves a las 10 hs').")
        r = self.tool("consultar_obra", obra_id=obra["id"])
        invitado = r.get("obra", {}).get("email")
        titulo = f"Visita de obra {obra['nombre'].split('—')[0].strip()}"
        op = Operacion(tool="agendar_evento", descripcion=f"{titulo} — {fecha_corta(f.isoformat())} {h}",
                       args={"fecha": f.isoformat(), "hora": h, "titulo": titulo, "obra_id": obra["id"],
                             "invitado": invitado})
        return self.resultado(f"Agendo {titulo} el {fecha_corta(f.isoformat())} a las {h} e invito a "
                              f"{invitado or 'nadie'}.", self.proponer(e, f"Agendar {titulo}", [op]))
