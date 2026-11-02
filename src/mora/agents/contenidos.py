"""Agente de contenidos: calendario editorial y borradores para redes (brief visual en TEXTO, no imágenes)."""
from __future__ import annotations

import re
from datetime import date, timedelta

from ..contracts import Operacion
from ..text import MESES, fecha_corta, mes_mencionado, norm, tiene
from .base import AgenteBase, EntradaAgente

HASHTAGS = "#interiorismo #diseñodeinteriores #santafe #deco"
FORMATO = {"proyectos": "carrusel", "tips": "reel", "proceso": "historia", "materiales": "foto"}
TEMAS_TIPS = ["cómo elegir la luz cálida correcta", "3 errores al distribuir un living chico",
              "cómo combinar madera clara y verde salvia", "alfombras: la medida justa"]
TEMAS_MATERIALES = ["lino natural", "cerámica artesanal", "madera de paraíso", "piedra en mesadas"]


def pilar_de(t: str) -> str:
    if tiene(t, "tip", "consejo", "error", "como elegir"):
        return "tips"
    if tiene(t, "material", "textura", "madera", "ceramic", "lino"):
        return "materiales"
    if tiene(t, "proceso", "detras", "moodboard", "visita", "muestra"):
        return "proceso"
    return "proyectos"


def copy_post(pilar: str, tema: str, obra: dict | None) -> tuple[str, str]:
    if pilar == "proyectos" and obra:
        texto = (f"{obra['nombre'].split('—')[0].strip()}: así quedó ✨ Buscamos un espacio cálido y funcional, "
                 f"con materiales nobles y mucha luz natural. Deslizá para ver el antes y el después. "
                 "¿Cuál es tu foto favorita?")
        brief = f"Carrusel 5-7 fotos de {obra['nombre']}: portada con el resultado, luego antes/después. Paleta arena/terracota."
    elif pilar == "tips":
        texto = f"Tip de interiorismo: {tema}. Guardalo para cuando lo necesites y contame si te sirvió 💡"
        brief = f"Reel 20-30 s mostrando '{tema}' con ejemplos reales; texto en pantalla corto, tipografía de marca."
    elif pilar == "materiales":
        texto = f"Materiales que amamos: {tema}. Aporta calidez y envejece con nobleza. ¿Lo sumarías a tu casa?"
        brief = f"Foto macro de {tema} con luz natural lateral; fondo neutro arena."
    else:
        texto = f"Detrás de escena: {tema}. Así arranca cada proyecto, eligiendo con calma cada detalle."
        brief = f"Historia + foto del proceso: {tema}. Mostrar manos, muestras y moodboard."
    return texto, brief


class AgenteContenidos(AgenteBase):
    nombre = "contenidos"
    frontera = ("Tu dominio son las REDES: calendario editorial, ideas y borradores de posts con copy, hashtags y "
                "un brief visual en texto para la diseñadora gráfica. No generás imágenes. Solo mostrás obras "
                "con permiso de publicación.")

    def _slots(self, desde: date, hasta: date, ocupadas: set[str], dias_pub: list[int]) -> list[date]:
        out, d = [], desde
        while d <= hasta:
            if d.weekday() in dias_pub and d.isoformat() not in ocupadas:
                out.append(d)
            d += timedelta(days=1)
        return out

    def local(self, e: EntradaAgente):
        t, hoy = norm(e.texto), self.deps.settings.hoy
        mes = mes_mencionado(e.texto, hoy)
        if tiene(t, "que tengo programado", "que hay programado", "que publique", "que publicamos"):
            y, m = mes or (hoy.year, hoy.month)
            r = self.tool("calendario_contenidos", mes=f"{y}-{m:02d}")
            filas = [f"- {fecha_corta(p['fecha'])}: {p['formato']} ({p['pilar']}) — {p['estado']}" for p in r.get("posts", [])]
            return self.resultado(f"Contenidos de {MESES[m - 1]}:\n" + ("\n".join(filas) or "- nada programado"))

        pil = self.tool("pilares_contenido")
        pilares, dias_pub = pil.get("pilares") or ["proyectos", "tips"], pil.get("dias_publicacion", [1, 4])
        obras = self.tool("obras_publicables").get("obras", [])
        mensual = tiene(t, "calendario", "planific", "grilla", "del mes", "mensual") or mes is not None
        if mensual:
            y, m = mes or ((hoy.year, hoy.month + 1) if hoy.month < 12 else (hoy.year + 1, 1))
            inicio = max(date(y, m, 1), hoy + timedelta(days=1))
            fin = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
        else:
            y, m, inicio, fin = hoy.year, hoy.month, hoy + timedelta(days=1), hoy + timedelta(days=21)
        existentes = self.tool("calendario_contenidos", mes=f"{y}-{m:02d}").get("posts", [])
        slots = self._slots(inicio, fin, {p["fecha"] for p in existentes}, dias_pub)
        if not slots:
            return self.resultado("No quedan fechas libres de publicación en ese período.")

        if mensual:
            plan = [(pilares[i % len(pilares)], slot) for i, slot in enumerate(slots)]
        else:
            plan = [(pilar_de(t), slots[0])]
        posts, i_tip, i_mat, i_obra = [], 0, 0, 0
        tema_libre = re.search(r"\bsobre\s+(.+?)(?:[.?!]|$)", e.texto, re.I)
        for pilar, f in plan:
            obra = obras[i_obra % len(obras)] if pilar == "proyectos" and obras else None
            if pilar == "proyectos" and not obra:
                pilar = "tips"
            if pilar == "tips":
                tema = tema_libre.group(1) if (tema_libre and not mensual) else TEMAS_TIPS[i_tip % len(TEMAS_TIPS)]; i_tip += 1
            elif pilar == "materiales":
                tema = tema_libre.group(1) if (tema_libre and not mensual) else TEMAS_MATERIALES[i_mat % len(TEMAS_MATERIALES)]; i_mat += 1
            else:
                tema = tema_libre.group(1) if (tema_libre and not mensual) else "un nuevo proyecto"
            if obra:
                i_obra += 1
            texto, brief = copy_post(pilar, tema, obra)
            posts.append({"fecha": f.isoformat(), "red": "instagram", "formato": FORMATO.get(pilar, "foto"),
                          "pilar": pilar, "texto": texto, "hashtags": HASHTAGS, "brief_visual": brief,
                          "obra_id": obra["id"] if obra else None})
        op = Operacion(tool="programar_posts", args={"posts": posts},
                       descripcion=f"Programar {len(posts)} post(s) en Instagram")
        resumen = (f"Calendario de {MESES[m - 1]}: {len(posts)} posts" if mensual else f"Borrador de post para {fecha_corta(posts[0]['fecha'])}")
        accion = self.proponer(e, resumen, [op], "Frecuencia de marca: martes y viernes, rotando pilares; "
                                                 "solo obras con permiso de publicación.")
        tabla = "\n".join(f"- {fecha_corta(p['fecha'])} · {p['formato']} · {p['pilar']}: {p['texto'][:70]}…" for p in posts)
        return self.resultado(f"{resumen}:\n{tabla}\n\nRevisalos antes de programarlos.", accion)
