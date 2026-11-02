import pytest

from mora.agents.supervisor import PlanError, plan_por_reglas, validate_plan
from mora.agents.triage import clasificar, extraer_datos
from mora.contracts import Clasificacion, RunBudget, SolicitudEntrante, WorkerTask
from mora.llm.base import LLMError

from .conftest import solicitud


@pytest.mark.parametrize("archivo,intencion,cliente,proyecto", [
    ("01_lead_presupuesto.json", "presupuesto", None, None),
    ("02_cliente_avance.json", "consulta_proyecto", "CLI-001", "PRJ-2026-014"),
    ("03_reclamo_obra.json", "reclamo", "CLI-002", "PRJ-2026-021"),
    ("04_agenda_reunion.json", "agenda", "CLI-003", None),
])
def test_clasificacion_por_reglas(deps, archivo, intencion, cliente, proyecto):
    c = clasificar(SolicitudEntrante.model_validate(solicitud(archivo)), deps.repo)
    assert (c.intencion, c.cliente_id, c.proyecto_id) == (intencion, cliente, proyecto)


def test_reclamo_es_urgente(deps):
    c = clasificar(SolicitudEntrante.model_validate(solicitud("03_reclamo_obra.json")), deps.repo)
    assert c.urgencia == "alta"


def test_extraccion_respeta_bordes_de_palabra():
    d = extraer_datos("Compré un lote en Escobar, quiero una casa de 140 m2 con anteproyecto")
    assert d.tipo_proyecto == "vivienda"  # 'Escobar' no debe disparar 'bar' -> local_comercial
    assert d.superficie_m2 == 140
    assert d.etapas == ["anteproyecto"]


class FakeLLM:
    name = "fake"

    def __init__(self, respuestas):
        self.respuestas = respuestas

    def generate_structured(self, *, system, prompt, schema):
        r = self.respuestas.get(schema.__name__)
        if r is None:
            raise LLMError("sin respuesta")
        return schema.model_validate(r)


def test_llm_no_puede_inventar_identidad(deps):
    """Aunque el LLM (o un prompt injection) diga otro cliente, la identidad sale del repo."""
    llm = FakeLLM({"Clasificacion": {"intencion": "consulta_proyecto", "resumen": "x",
                                     "cliente_id": "CLI-002", "proyecto_id": "PRJ-2026-021"}})
    c = clasificar(SolicitudEntrante.model_validate(solicitud("02_cliente_avance.json")), deps.repo, llm)
    assert c.metodo == "llm" and c.cliente_id == "CLI-001" and c.proyecto_id == "PRJ-2026-014"


def test_llm_caido_usa_reglas(deps):
    c = clasificar(SolicitudEntrante.model_validate(solicitud("03_reclamo_obra.json")), deps.repo, FakeLLM({}))
    assert c.metodo == "reglas" and c.intencion == "reclamo"


def _t(tid, role="documental", deps=()):
    return WorkerTask(task_id=tid, role=role, objective="x", success_criteria=["ok"], depends_on=list(deps))


@pytest.mark.parametrize("tasks,msg", [
    ([_t("a"), _t("b"), _t("c"), _t("d")], "max_workers"),
    ([_t("a"), _t("a")], "duplicados"),
    ([_t("a", deps=["z"])], "inexistente"),
    ([_t("a", deps=["b"]), _t("b", deps=["a"])], "ciclo"),
])
def test_validate_plan_rechaza_planes_invalidos(tasks, msg):
    with pytest.raises(PlanError, match=msg):
        validate_plan(tasks, RunBudget())


def test_plan_por_intencion_es_valido():
    sol = SolicitudEntrante(id="x", remitente="a@b.c", cuerpo="hola")
    for intent in ["nuevo_lead", "consulta_proyecto", "presupuesto", "agenda", "documentacion", "reclamo", "otro"]:
        tasks = validate_plan(plan_por_reglas(sol, Clasificacion(intencion=intent, resumen="x")), RunBudget())
        assert 1 <= len(tasks) <= 3
