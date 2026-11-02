"""Evaluación del router sobre un dataset etiquetado (rúbrica: evaluación y trazabilidad, 20%).

Cada caso termina en uno de tres resultados:
- correcto:        derivó al agente esperado con confianza >= umbral (o preguntó cuando se esperaba aclaración)
- aclaracion:      la confianza no llegó al umbral y el sistema preguntó (costo: un paso más para la usuaria)
- error_confiado:  derivó a otro agente con confianza >= umbral. ES EL PEOR CASO: el pedido termina mal.

Casos multi-intención (`esperado: "multi"` + `agentes_esperados`): son correctos si el router delega
exactamente a ese conjunto de agentes. Partir un pedido simple en varios cuenta como error con confianza.
"""
from __future__ import annotations

import json
import statistics
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from ..agents.router import rutear
from ..config import Settings
from ..contracts import AGENTES
from ..llm.base import LLMProvider
from ..tracing import UsageMeter, _meter, costo_usd

ETIQUETAS = list(AGENTES) + ["aclaracion", "multi"]


def cargar_dataset(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = min(len(xs) - 1, max(0, round(p / 100 * (len(xs) - 1))))
    return round(xs[k], 2)


def evaluar(dataset: list[dict], settings: Settings, llm: LLMProvider | None = None) -> dict:
    filas = []
    for caso in dataset:
        meter = UsageMeter()
        tok = _meter.set(meter)
        t0 = time.perf_counter()
        try:
            d = rutear(caso["texto"], llm)
        finally:
            _meter.reset(tok)
        lat = (time.perf_counter() - t0) * 1000
        if d.confianza < settings.umbral_router:
            pred = "aclaracion"
        elif d.es_multiple:
            pred = "multi"
        else:
            pred = d.agente
        esperado = caso["esperado"]
        delegados = sorted({x.agente for x in d.subpedidos}) if d.es_multiple else [d.agente]
        if esperado == "multi" and pred == "multi":
            resultado = "correcto" if delegados == sorted(caso.get("agentes_esperados", [])) else "error_confiado"
        elif pred == esperado:
            resultado = "correcto"
        elif pred == "aclaracion":
            resultado = "aclaracion"
        else:
            resultado = "error_confiado"
        filas.append({**caso, "predicho": pred, "agente_router": d.agente, "confianza": d.confianza,
                      "justificacion": d.justificacion, "metodo": d.metodo, "resultado": resultado, "delegados": delegados,
                      "latencia_ms": round(lat, 2), "tokens_in": meter.tokens_in, "tokens_out": meter.tokens_out,
                      "costo_usd": costo_usd(settings, meter.tokens_in, meter.tokens_out)})

    n = len(filas)
    cuenta = Counter(f["resultado"] for f in filas)
    lim = [f for f in filas if f.get("limitrofe")]
    matriz = {e: {p: 0 for p in ETIQUETAS} for e in ETIQUETAS}
    for f in filas:
        matriz[f["esperado"]][f["predicho"]] += 1
    por_clase = {}
    for c in ETIQUETAS:
        tp = matriz[c][c]
        pred_c = sum(matriz[e][c] for e in ETIQUETAS)
        real_c = sum(matriz[c].values())
        por_clase[c] = {"soporte": real_c, "precision": round(tp / pred_c, 3) if pred_c else None,
                        "recall": round(tp / real_c, 3) if real_c else None}
    frontera = [f for f in filas if {f["esperado"], f["predicho"]} == {"administrativo", "proyectos"}]
    multi = [f for f in filas if f["esperado"] == "multi"]
    lats = [f["latencia_ms"] for f in filas]
    return {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "modo": "llm" if llm else "reglas", "umbral": settings.umbral_router, "n": n,
        "accuracy": round(cuenta["correcto"] / n, 3) if n else 0,
        "tasa_aclaracion": round(cuenta["aclaracion"] / n, 3) if n else 0,
        "tasa_error_confiado": round(cuenta["error_confiado"] / n, 3) if n else 0,
        "accuracy_limitrofes": round(sum(f["resultado"] == "correcto" for f in lim) / len(lim), 3) if lim else None,
        "confusiones_admin_proyectos": len(frontera),
        "accuracy_multi": (round(sum(f["resultado"] == "correcto" for f in multi) / len(multi), 3) if multi else None),
        "pedidos_simples_partidos": sum(1 for f in filas if f["esperado"] != "multi" and f["predicho"] == "multi"),
        "por_clase": por_clase, "matriz_confusion": matriz,
        "latencia_ms": {"p50": _pct(lats, 50), "p95": _pct(lats, 95), "media": round(statistics.mean(lats), 2) if lats else 0},
        "tokens": {"in": sum(f["tokens_in"] for f in filas), "out": sum(f["tokens_out"] for f in filas)},
        "costo_usd": {"total": round(sum(f["costo_usd"] for f in filas), 6),
                      "por_consulta": round(sum(f["costo_usd"] for f in filas) / n, 6) if n else 0},
        "casos": filas,
    }


def reporte_markdown(r: dict) -> str:
    L = [f"# Evaluación del router — modo {r['modo']} ({r['fecha']})", "",
         f"Dataset: {r['n']} casos · umbral de confianza {r['umbral']}", "",
         "| Métrica | Valor |", "|---|---|",
         f"| Accuracy | {r['accuracy']:.1%} |",
         f"| Tasa de aclaración (preguntó) | {r['tasa_aclaracion']:.1%} |",
         f"| **Error con confianza** (derivó mal sin preguntar) | **{r['tasa_error_confiado']:.1%}** |",
         f"| Accuracy en casos limítrofes | {r['accuracy_limitrofes']:.1%} |" if r["accuracy_limitrofes"] is not None else "",
         f"| Confusiones administrativo ↔ proyectos | {r['confusiones_admin_proyectos']} |",
         f"| Multi-intención: delegó al conjunto correcto | {r['accuracy_multi']:.1%} |" if r.get("accuracy_multi") is not None else "",
         f"| Pedidos simples partidos por error | {r.get('pedidos_simples_partidos', 0)} |",
         f"| Latencia p50 / p95 | {r['latencia_ms']['p50']} / {r['latencia_ms']['p95']} ms |",
         f"| Tokens in / out | {r['tokens']['in']} / {r['tokens']['out']} |",
         f"| Costo total / por consulta | US$ {r['costo_usd']['total']} / {r['costo_usd']['por_consulta']} |",
         "", "## Por clase", "", "| Clase | Soporte | Precision | Recall |", "|---|---|---|---|"]
    for c, m in r["por_clase"].items():
        L.append(f"| {c} | {m['soporte']} | {m['precision'] if m['precision'] is not None else '—'} | "
                 f"{m['recall'] if m['recall'] is not None else '—'} |")
    L += ["", "## Matriz de confusión (filas = esperado, columnas = predicho)", "",
          "| | " + " | ".join(ETIQUETAS) + " |", "|---" * (len(ETIQUETAS) + 1) + "|"]
    for e in ETIQUETAS:
        L.append(f"| **{e}** | " + " | ".join(str(r["matriz_confusion"][e][p]) for p in ETIQUETAS) + " |")
    malos = [f for f in r["casos"] if f["resultado"] != "correcto"]
    L += ["", "## Casos no correctos (para revisión manual con la justificación del router)", ""]
    if not malos:
        L.append("Ninguno.")
    else:
        L += ["| id | texto | esperado | predicho | conf. | resultado | justificación |", "|---|---|---|---|---|---|---|"]
        for f in malos:
            L.append(f"| {f['id']} | {f['texto']} | {f['esperado']} | {f['predicho']} | {f['confianza']} | "
                     f"{f['resultado']} | {f['justificacion']} |")
    return "\n".join(l for l in L if l is not None)


def guardar(r: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"router_{r['modo']}_{r['fecha'][:10]}"
    pj, pm = out_dir / f"{stem}.json", out_dir / f"{stem}.md"
    pj.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    pm.write_text(reporte_markdown(r), encoding="utf-8")
    return pj, pm
