"""Trazas por nodo: latencia, tokens, costo estimado y modelo (rúbrica: evaluación y trazabilidad).

Cada nodo del grafo se envuelve con `traced(...)`. Los proveedores LLM reportan su uso al
`UsageMeter` del contexto actual, así el nodo sabe cuántos tokens consumió sin acoplarse al proveedor.
"""
from __future__ import annotations

import contextvars
import functools
import time
from dataclasses import dataclass, field
from datetime import datetime

from .config import Settings


@dataclass
class UsageMeter:
    tokens_in: int = 0
    tokens_out: int = 0
    llamadas: int = 0
    modelos: set[str] = field(default_factory=set)

    def add(self, modelo: str, tokens_in: int, tokens_out: int) -> None:
        self.tokens_in += tokens_in or 0
        self.tokens_out += tokens_out or 0
        self.llamadas += 1
        self.modelos.add(modelo)


_meter: contextvars.ContextVar[UsageMeter | None] = contextvars.ContextVar("mora_meter", default=None)


def report_usage(modelo: str, tokens_in: int, tokens_out: int) -> None:
    m = _meter.get()
    if m is not None:
        m.add(modelo, tokens_in, tokens_out)


def costo_usd(settings: Settings, tokens_in: int, tokens_out: int) -> float:
    return round(tokens_in / 1e6 * settings.precio_input_1m_usd + tokens_out / 1e6 * settings.precio_output_1m_usd, 6)


def traced(nodo: str, settings: Settings):
    """Decora un nodo: agrega una entrada a `trazas`. Las interrupciones (HITL) se propagan sin traza."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(state, *args, **kwargs):
            meter, token = UsageMeter(), None
            token = _meter.set(meter)
            t0 = time.perf_counter()
            try:
                update = fn(state, *args, **kwargs) or {}
            finally:
                _meter.reset(token)
            traza = {
                "turno": update.get("turno", state.get("turno", 0)),
                "nodo": nodo,
                "latencia_ms": round((time.perf_counter() - t0) * 1000, 2),
                "llamadas_llm": meter.llamadas,
                "tokens_in": meter.tokens_in,
                "tokens_out": meter.tokens_out,
                "costo_usd": costo_usd(settings, meter.tokens_in, meter.tokens_out),
                "modelo": ",".join(sorted(meter.modelos)) or "-",
                "at": datetime.now().isoformat(timespec="seconds"),
            }
            extra = update.pop("_traza_extra", None)
            if extra:
                traza.update(extra)
            update["trazas"] = list(update.get("trazas", [])) + [traza]
            return update

        return wrapper

    return deco


def resumen_trazas(trazas: list[dict], turno: int | None = None) -> dict:
    ts = [t for t in trazas if turno is None or t.get("turno") == turno]
    return {
        "nodos": [t["nodo"] for t in ts],
        "latencia_ms": round(sum(t["latencia_ms"] for t in ts), 2),
        "tokens_in": sum(t["tokens_in"] for t in ts),
        "tokens_out": sum(t["tokens_out"] for t in ts),
        "costo_usd": round(sum(t["costo_usd"] for t in ts), 6),
        "llamadas_llm": sum(t["llamadas_llm"] for t in ts),
    }
