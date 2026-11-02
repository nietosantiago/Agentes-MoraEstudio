"""Agente comercial: calificación y seguimiento de leads."""
from __future__ import annotations

import re

from ..contracts import Operacion
from ..text import norm, parse_monto, tiene
from ..tools.comercial import lead_id_para
from .base import AgenteBase, EntradaAgente

FIRMA = "Mora — Estudio de Interiorismo"
CANALES = [("instagram", ("instagram", "ig", "dm")), ("whatsapp", ("whatsapp", "wsp", "wpp")),
           ("email", ("mail", "correo", "email")), ("web", ("web", "formulario"))]
CIUDADES = ["santa fe", "santo tome", "parana", "rosario", "esperanza", "rafaela", "recreo", "sauce viejo",
            "cordoba", "buenos aires"]
TIPOS = ["cocina", "living", "dormitorio", "bano", "comedor", "oficina", "local", "departamento", "casa"]


def extraer_lead(texto: str) -> dict:
    t = norm(texto)
    m = re.search(r"(?:de|escribi[oó]|consulta de|lead|llam[oó])\s+([A-ZÁÉÍÓÚ][a-záéíóúñ]+(?:\s[A-ZÁÉÍÓÚ][a-záéíóúñ]+)?)",
                  texto)
    citado = re.search(r"[\"“«](.+?)[\"”»]", texto, re.S)
    contacto = re.search(r"(@[\w.]+|[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d\s-]{8,}\d)", texto)
    return {
        "nombre": m.group(1) if m else None,
        "canal": next((c for c, kws in CANALES if tiene(t, *kws)), "otro"),
        "ciudad": next((c.title() for c in CIUDADES if f" {c} " in t), None),
        "tipo_proyecto": next((x for x in TIPOS if tiene(t, x)), None),
        "presupuesto_estimado": parse_monto(texto),
        "mensaje": citado.group(1).strip() if citado else None,
        "contacto": contacto.group(1).strip() if contacto else None,
    }


def borrador(nombre: str, tipo: str | None, calificacion: str) -> str:
    n = nombre.split()[0]
    espacio = f"tu {tipo}" if tipo else "tu espacio"
    if calificacion == "A":
        cuerpo = (f"¡Gracias por escribirme! Me encantaría ayudarte con {espacio}. Para arrancar te propongo una "
                  "asesoría en tu casa: voy, relevo el espacio y te dejo recomendaciones por escrito. "
                  "¿Qué días te quedan cómodos esta semana o la próxima?")
    elif calificacion == "B":
        cuerpo = (f"¡Gracias por tu consulta! Para orientarte mejor con {espacio}, ¿me contás un poco más? "
                  "Medidas aproximadas, un par de fotos y qué te gustaría cambiar. Con eso te propongo la mejor "
                  "forma de trabajar juntos.")
    else:
        cuerpo = (f"¡Gracias por escribirme! Para {espacio} te puede servir una asesoría online: una videollamada "
                  "de una hora y te queda un moodboard con ideas concretas. ¿Te cuento cómo es?")
    return f"Hola {n}! {cuerpo}\n\n{FIRMA}"


def borrador_seguimiento(nombre: str, tipo: str | None) -> str:
    espacio = f"tu {tipo}" if tipo else "tu proyecto"
    return (f"Hola {nombre.split()[0]}! ¿Cómo estás? Te escribo para saber si seguís pensando en {espacio}. "
            f"Si querés, coordinamos una asesoría y lo vemos juntos, sin compromiso.\n\n{FIRMA}")


class AgenteComercial(AgenteBase):
    nombre = "comercial"
    frontera = ("Tu dominio son los LEADS: calificar consultas nuevas, responderlas y hacer seguimiento. "
                "NO das precios ni presupuestos (eso es del agente administrativo) ni manejás obras en curso.")

    def local(self, e: EntradaAgente):
        t = norm(e.texto)
        if tiene(t, "seguimiento", "sin respuesta", "no contest", "no respond", "pendiente") and tiene(t, "lead"):
            return self._seguimiento(e)
        if tiene(t, "cuantos lead", "listame", "mostrame", "que leads", "lista de leads"):
            r = self.tool("listar_leads")
            filas = [f"- {l['nombre']} ({l['canal']}, {l['estado']}, calif. {l['calificacion'] or '—'}, "
                     f"{l['dias_sin_contacto']} días sin contacto)" for l in r.get("leads", [])]
            return self.resultado(f"Tenés {len(filas)} leads:\n" + "\n".join(filas), leads=r.get("leads", []))
        return self._nueva_consulta(e)

    def _seguimiento(self, e):
        r = self.tool("listar_leads", sin_contacto_dias=5)
        leads = [l for l in r.get("leads", []) if l["estado"] in ("nuevo", "contactado", "calificado", "presupuestado")]
        if not leads:
            return self.resultado("No hay leads con más de 5 días sin contacto. 🎉")
        ops = [Operacion(tool="enviar_mensaje", descripcion=f"Seguimiento a {l['nombre']} por {l['canal']}",
                         args={"destinatario": l["contacto"] or l["nombre"], "canal": l["canal"],
                               "asunto": "Seguimiento", "cuerpo": borrador_seguimiento(l["nombre"], l["tipo_proyecto"]),
                               "motivo": "seguimiento_lead", "lead_id": l["id"]})
               for l in leads]
        lista = "\n".join(f"- {l['nombre']}: {l['dias_sin_contacto']} días sin contacto ({l['estado']})" for l in leads)
        accion = self.proponer(e, f"Seguimiento a {len(ops)} lead(s)", ops,
                               "Leads con más de 5 días sin contacto: el seguimiento a tiempo sube la conversión.")
        return self.resultado(f"Encontré {len(ops)} lead(s) para hacer seguimiento:\n{lista}\n\n"
                              "Te dejo los mensajes listos para que los revises.", accion)

    def _nueva_consulta(self, e):
        d = extraer_lead(e.texto)
        if not d["nombre"]:
            return self.resultado("¿De quién es la consulta? Pasame el nombre y, si podés, el mensaje que te mandó "
                                  "entre comillas, la ciudad y el canal.")
        previo = [x for x in self.tool("buscar_contacto", texto=d["nombre"]).get("resultados", [])
                  if x["tipo"] == "lead"]
        lead = previo[0] if previo else None
        if lead:
            d = {**{k: lead.get(k) for k in d}, **{k: v for k, v in d.items() if v and v != "otro"}}
        cal = self.tool("calificar_lead", ciudad=d["ciudad"], tipo_proyecto=d["tipo_proyecto"],
                        presupuesto_estimado=d["presupuesto_estimado"])
        if "error" in cal:
            return self.resultado(f"No pude calificar el lead: {cal['error']}")
        lead_id = lead["id"] if lead else lead_id_para(d["nombre"], d["contacto"])
        canal = d["canal"] if d["canal"] != "otro" else "instagram"
        ops = [
            Operacion(tool="registrar_lead", descripcion=f"Registrar a {d['nombre']} como lead {cal['calificacion']}",
                      args={"nombre": d["nombre"], "canal": canal, "contacto": d["contacto"], "ciudad": d["ciudad"],
                            "tipo_proyecto": d["tipo_proyecto"], "presupuesto_estimado": d["presupuesto_estimado"],
                            "mensaje": d["mensaje"], "calificacion": cal["calificacion"], "lead_id": lead_id}),
            Operacion(tool="enviar_mensaje", descripcion=f"Responder a {d['nombre']} por {canal}",
                      args={"destinatario": d["contacto"] or d["nombre"], "canal": canal, "asunto": "Tu consulta",
                            "cuerpo": borrador(d["nombre"], d["tipo_proyecto"], cal["calificacion"]),
                            "motivo": "respuesta_lead", "lead_id": lead_id}),
        ]
        motivos = "; ".join(cal["motivos"])
        accion = self.proponer(e, f"Registrar y responder a {d['nombre']} (lead {cal['calificacion']})", ops,
                               f"Calificación {cal['calificacion']}: {motivos}.")
        faltan = [k for k in ("ciudad", "tipo_proyecto", "presupuesto_estimado") if not d[k]]
        nota = f"\nMe faltó saber: {', '.join(faltan).replace('_', ' ')}." if faltan else ""
        return self.resultado(f"{d['nombre']} califica como lead **{cal['calificacion']}** ({motivos}).{nota}\n"
                              "Te preparé el registro y una respuesta para que la revises.", accion,
                              calificacion=cal)
