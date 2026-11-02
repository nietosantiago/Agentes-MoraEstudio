"""Agent loop en modo LLM con un modelo guionado: valida que el runtime controle cada paso."""
from langgraph.checkpoint.memory import InMemorySaver

from mora.agents.administrativo import AgenteAdministrativo
from mora.agents.base import EntradaAgente
from mora.deps import Deps
from mora.service import MoraService

from .conftest import FakeLLM, conversar


def _agente(settings, pasos):
    return AgenteAdministrativo(Deps.build(settings, llm=FakeLLM({"PasoAgente": pasos})))


def test_loop_usa_tools_y_propone(settings):
    ag = _agente(settings, [
        {"tipo": "tool", "tool": "cobros_pendientes", "args_json": "{\"cliente_id\": \"CLI-02\"}"},
        {"tipo": "final", "respuesta": "Te preparo la factura del saldo.", "resumen_accion": "Factura saldo Gómez",
         "operaciones": [{"tool": "emitir_factura", "descripcion": "Factura C",
                          "args_json": "{\"cliente_id\": \"CLI-02\", \"concepto\": \"Saldo\", \"monto\": 1340000, \"cobro_id\": \"COB-02\"}"}]},
    ])
    r = ag.ejecutar(EntradaAgente(texto="facturale el saldo a gomez", turno=1, thread_id="t"))
    assert r.modo == "llm" and r.tools_usadas == ["cobros_pendientes"]
    assert r.accion and r.accion.riesgo == "alto" and r.accion.efecto_externo  # riesgo lo pone el registry


def test_loop_rechaza_tool_ajena_y_operacion_prohibida(settings):
    ag = _agente(settings, [
        {"tipo": "tool", "tool": "proximos_hitos", "args_json": "{}"},              # de otro agente
        {"tipo": "final", "respuesta": "x", "operaciones": [
            {"tool": "aplicar_descuento", "descripcion": "10%", "args_json": "{\"presupuesto_id\": \"P\", \"porcentaje\": 0.1}"}]},
        {"tipo": "final", "respuesta": "No puedo aplicar descuentos; lo decidís vos."},
    ])
    r = ag.ejecutar(EntradaAgente(texto="hacele 10% de descuento", turno=1, thread_id="t"))
    assert r.accion is None
    assert any("no puede ejecutar" in e for e in r.errores) and any("aplicar_descuento" in e for e in r.errores)


def test_args_json_invalido_no_rompe(settings):
    ag = _agente(settings, [
        {"tipo": "tool", "tool": "cobros_pendientes", "args_json": "{no es json"},
        {"tipo": "final", "respuesta": "listo"},
    ])
    assert ag.ejecutar(EntradaAgente(texto="x", turno=1, thread_id="t")).respuesta == "listo"


def test_limite_de_pasos(settings):
    ag = _agente(settings, [{"tipo": "tool", "tool": "consultar_precios", "args_json": "{}"}] * 6)
    r = ag.ejecutar(EntradaAgente(texto="x", turno=1, thread_id="t"))
    assert "límite de pasos" in r.respuesta and r.accion is None


def test_llm_caido_cae_a_modo_local(settings):
    svc = MoraService(Deps.build(settings, llm=FakeLLM({})), InMemorySaver())
    th, v = conversar(svc, "¿Cuánto facturé en octubre?")
    assert v["router"]["metodo"] == "reglas" and "$ 1.125.000" in v["mensajes"][-1]["texto"]
    t = {x["nodo"]: x for x in v["trazas_turno"]}
    assert t["administrativo"]["modo"] == "llm_fallback_local"
