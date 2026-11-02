from pathlib import Path

import pytest

from mora.agents.router import rutear, rutear_por_reglas
from mora.config import ROOT
from mora.evaluation.router_eval import cargar_dataset, evaluar, reporte_markdown

from .conftest import FakeLLM


@pytest.mark.parametrize("texto,agente", [
    ("¿Cuándo me paga Gómez el saldo?", "administrativo"),          # 'cuándo' pero es plata
    ("¿Para cuándo tengo que tener los renders de Valentina?", "proyectos"),  # 'render' pero es tiempo
    ("Facturale el saldo a Martín Gómez", "administrativo"),
    ("Se atrasaron los muebles de cocina de Gómez", "proyectos"),
    ("Armame el calendario de posts de diciembre", "contenidos"),
    ("Haceme el seguimiento de los leads que no contestaron", "comercial"),
])
def test_frontera_plata_vs_tiempo(texto, agente):
    d = rutear_por_reglas(texto)
    assert d.agente == agente and d.confianza >= 0.6, d


def test_pedido_ambiguo_tiene_baja_confianza():
    assert rutear_por_reglas("¿Cuándo?").confianza < 0.6
    assert rutear_por_reglas("hola").confianza == 0


def test_router_llm_y_fallback():
    llm = FakeLLM({"DecisionRouter": [{"agente": "proyectos", "confianza": 0.9, "justificacion": "fechas"}]})
    d = rutear("algo", llm)
    assert d.metodo == "llm" and d.agente == "proyectos"
    d2 = rutear("Facturale a Gómez", llm)  # el guion se agotó -> LLMError -> reglas
    assert d2.metodo == "reglas" and d2.agente == "administrativo"


def test_evaluacion_produce_metricas(settings):
    ds = cargar_dataset(ROOT / "eval" / "dataset_router.jsonl")
    assert len(ds) >= 30 and sum(c.get("limitrofe", False) for c in ds) >= 10
    r = evaluar(ds, settings)
    assert r["n"] == len(ds)
    assert abs(r["accuracy"] + r["tasa_aclaracion"] + r["tasa_error_confiado"] - 1) < 1e-6
    assert r["tasa_error_confiado"] <= 0.10  # baseline por reglas: casi nunca deriva mal con seguridad
    assert "Matriz de confusión" in reporte_markdown(r)


def test_evaluacion_mide_tokens_y_costo(settings):
    llm = FakeLLM({"DecisionRouter": [{"agente": "comercial", "confianza": 0.9, "justificacion": "x"}] * 2},
                  tokens=(1000, 100))
    r = evaluar([{"id": "a", "texto": "x", "esperado": "comercial"},
                 {"id": "b", "texto": "y", "esperado": "proyectos"}], settings, llm)
    assert r["tokens"] == {"in": 2000, "out": 200}
    assert r["costo_usd"]["total"] > 0 and r["tasa_error_confiado"] == 0.5
