"""Utilidades de texto y formato compartidas."""
from __future__ import annotations

import re
import unicodedata
from datetime import date

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def norm(texto: str) -> str:
    """minúsculas, sin acentos, solo [a-z0-9 ] con espacios simples y bordes."""
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " " + " ".join(re.findall(r"[a-z0-9]+", t)) + " "


def tiene(texto_norm: str, *frases: str) -> bool:
    """Prefijo de palabra: 'factur' matchea 'facturé'; 'bar' no matchea 'escobar'."""
    return any(f" {norm(f).strip()}" in texto_norm for f in frases)


def ars(x: float) -> str:
    s = f"{x:,.0f}".replace(",", ".")
    return f"$ {s}"


def fecha_corta(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{DIAS[d.weekday()]} {d.day}/{d.month}"


def mes_mencionado(texto: str, hoy: date) -> tuple[int, int] | None:
    t = norm(texto)
    pasado = tiene(t, "facture", "facturado", "facturacion", "cobre", "cobrado", "pasado", "gane")
    for i, m in enumerate(MESES, start=1):
        if f" {m} " in t:
            if pasado:
                return (hoy.year - 1 if i > hoy.month else hoy.year), i
            return (hoy.year + 1 if i < hoy.month else hoy.year), i  # planificación: hacia adelante
    if tiene(t, "mes pasado"):
        return (hoy.year, hoy.month - 1) if hoy.month > 1 else (hoy.year - 1, 12)
    if tiene(t, "proximo mes", "mes que viene"):
        return (hoy.year, hoy.month + 1) if hoy.month < 12 else (hoy.year + 1, 1)
    if tiene(t, "este mes"):
        return hoy.year, hoy.month
    return None


def parse_fecha(texto: str, hoy: date) -> date | None:
    """'25/11', '25-11-2026', 'el 25', 'mañana', 'el jueves'. Siempre hacia adelante."""
    from datetime import timedelta

    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", texto)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        y = int(m.group(3)) if m.group(3) else hoy.year
        y = y + 2000 if y < 100 else y
        try:
            f = date(y, mo, d)
        except ValueError:
            return None
        return f if m.group(3) or f >= hoy else date(y + 1, mo, d)
    t = norm(texto)
    if " manana " in t:
        return hoy + timedelta(days=1)
    for i, dia in enumerate(["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]):
        if f" {dia} " in t:
            delta = (i - hoy.weekday()) % 7 or 7
            return hoy + timedelta(days=delta)
    m = re.search(r"\b(?:al|el|para el|hasta el)\s+(\d{1,2})\b(?!\s*(?:m2|m²|ambiente|render|mes|hs|h\b|:))", texto.lower())
    if m:
        d = int(m.group(1))
        try:
            f = date(hoy.year, hoy.month, d)
        except ValueError:
            return None
        if f < hoy:
            f = date(hoy.year + (hoy.month == 12), hoy.month % 12 + 1, d)
        return f
    return None


def parse_hora(texto: str) -> str | None:
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(?:hs|h)\b", texto.lower()) or re.search(r"\b(\d{1,2}):(\d{2})\b", texto)
    if not m:
        return None
    return f"{int(m.group(1)):02d}:{(m.group(2) or '00')}"


def parse_monto(texto: str) -> float | None:
    t = texto.lower().replace("$", " $ ")
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(millones|millon|palos|mil|k)\b", t)
    if m:
        n = float(m.group(1).replace(".", "").replace(",", ".")) if m.group(2) == "mil" else float(m.group(1).replace(",", "."))
        return n * (1_000_000 if m.group(2).startswith(("millon", "palo")) else 1000)
    m = re.search(r"\$\s*(\d{1,3}(?:\.\d{3})+|\d{4,})", t)
    if m:
        return float(m.group(1).replace(".", ""))
    return None
