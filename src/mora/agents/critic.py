"""Revisor — patrón 07 Generator–Critic con rúbrica verificable y máximo de iteraciones (C12)."""
from __future__ import annotations

import re

from ..contracts import Clasificacion, ConsolidatedAnswer, Critique, WorkerOutput
from .atencion import money

PROHIBIDO = [
    (r"\bdescuento\b(?!.*direcci[oó]n)", "Menciona descuentos (nivel 4: solo la dirección)"),
    (r"\bgarantiz", "Promete plazos/resultados garantizados"),
    (r"\bte aseguro\b|\bseguro que\b", "Afirmación no respaldada"),
]


def criticar(ans: ConsolidatedAnswer, c: Clasificacion, outputs: list[WorkerOutput]) -> Critique:
    issues, scores = [], {}
    txt = ans.answer

    scores["firma"] = 1.0 if "Equipo Mora Estudio" in txt else 0.0
    if not scores["firma"]:
        issues.append("Falta la firma 'Equipo Mora Estudio'")

    hits = [msg for pat, msg in PROHIBIDO if re.search(pat, txt, re.IGNORECASE)]
    scores["politicas"] = 0.0 if hits else 1.0
    issues += hits

    pres = next((o for o in outputs if o.role == "presupuestos" and o.status == "success"), None)
    if pres:
        total = money(pres.data["calculo"]["total"])
        scores["montos"] = 1.0 if total in txt else 0.0
        if not scores["montos"]:
            issues.append(f"El total {total} del cálculo no aparece textual en la respuesta")

    faltantes = [q for o in outputs for q in o.open_questions]
    scores["faltantes_declarados"] = 1.0 if all(q in txt for q in faltantes) or ans.missing_information else 0.0
    if faltantes and not scores["faltantes_declarados"]:
        issues.append("Hay información faltante que no se le pide al cliente")

    if c.intencion == "reclamo" and not ans.escalar_a_humano:
        issues.append("Un reclamo debe escalar a la dirección")
    scores["longitud"] = 1.0 if len(txt) <= 2500 else 0.0
    if not scores["longitud"]:
        issues.append("Respuesta demasiado larga (>2500 caracteres)")

    return Critique(passed=not issues, critical_issues=issues, rubric_scores=scores,
                    suggested_changes=[f"Corregir: {i}" for i in issues])
