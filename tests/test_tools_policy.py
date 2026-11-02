import pytest
from pytest import approx

from mora.contracts import PendingAction
from mora.tools import PolicyError


def _action(tool, by, args):
    return PendingAction(action_id="a1", tool=tool, args=args, rationale="r", risk_level="high", proposed_by=by)


def test_rol_no_puede_usar_tools_ajenas(deps):
    with pytest.raises(PolicyError):
        deps.policy.call("documental", "calcular_honorarios", deps.tool_ctx,
                         {"tipo_proyecto": "vivienda", "superficie_m2": 10, "etapas": ["anteproyecto"]})


def test_worker_no_puede_ejecutar_efectos(deps):
    with pytest.raises(PolicyError):
        deps.policy.call("agenda", "crear_evento_agenda", deps.tool_ctx, {})


def test_efecto_nivel_3_requiere_aprobacion(deps):
    a = _action("enviar_respuesta", "atencion", {"canal": "email", "destinatario": "x@y.z", "asunto": "a",
                                                 "cuerpo": "x" * 30, "en_respuesta_a": "S"})
    with pytest.raises(PolicyError, match="aprobación"):
        deps.policy.authorize_execution(a, human_approved=False)
    assert deps.policy.authorize_execution(a, human_approved=True).name == "enviar_respuesta"


def test_nivel_4_nunca_se_delega(deps):
    a = _action("comprometer_descuento", "presupuestos", {"presupuesto_id": "P", "porcentaje": 0.1})
    assert not deps.policy.can_propose("presupuestos", "comprometer_descuento")
    with pytest.raises(PolicyError):
        deps.policy.authorize_execution(a, human_approved=True)


def test_rol_no_puede_proponer_tool_ajena(deps):
    a = _action("enviar_respuesta", "agenda", {"canal": "email", "destinatario": "x@y.z", "asunto": "a",
                                               "cuerpo": "x" * 30, "en_respuesta_a": "S"})
    with pytest.raises(PolicyError, match="no está autorizado"):
        deps.policy.authorize_execution(a, human_approved=True)


def test_calculo_honorarios(deps):
    r = deps.policy.call("presupuestos", "calcular_honorarios", deps.tool_ctx,
                         {"tipo_proyecto": "vivienda", "superficie_m2": 140,
                          "etapas": ["anteproyecto", "proyecto_ejecutivo"]})
    assert r["subtotal"] == approx(140 * 38 * 0.70)
    assert r["total"] == round(r["subtotal"] * 1.21, 2)


def test_honorario_minimo(deps):
    r = deps.policy.call("presupuestos", "calcular_honorarios", deps.tool_ctx,
                         {"tipo_proyecto": "interiorismo", "superficie_m2": 20, "etapas": ["anteproyecto"]})
    assert r["aplica_minimo"] and r["subtotal"] == 2500


def test_args_invalidos_se_rechazan_antes_del_handler(deps):
    with pytest.raises(ValueError):
        deps.policy.call("presupuestos", "calcular_honorarios", deps.tool_ctx,
                         {"tipo_proyecto": "castillo", "superficie_m2": -5, "etapas": []})


def test_aislamiento_documentos_entre_clientes(deps):
    """Un cliente nunca recibe fragmentos del informe de otro proyecto."""
    for pid, otro in [("PRJ-2026-014", "PRJ-2026-021"), ("PRJ-2026-021", "PRJ-2026-014"), (None, "PRJ-")]:
        r = deps.policy.call("documental", "buscar_documentos", deps.tool_ctx,
                             {"query": "estado general avance desvios proximos pasos", "proyecto_id": pid})
        assert bool(r["hits"]) == (pid is not None)  # sin proyecto: ningún informe de cliente
        assert not any((h["proyecto_id"] or "").startswith(otro) for h in r["hits"])
