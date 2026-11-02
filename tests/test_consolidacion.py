"""Delegación a varios agentes en paralelo y consolidación de resultados (arquitectura multiagente)."""
from langgraph.checkpoint.memory import InMemorySaver

from mora.agents import registro
from mora.agents.router import rutear_por_reglas
from mora.consolidacion import consolidar
from mora.contracts import AccionPendiente, Operacion, ResultadoAgente
from mora.deps import Deps
from mora.service import MoraService

from .conftest import FakeLLM, aprobar, conversar

PEDIDO = "Facturale el saldo a Martín Gómez y avisale que se atrasan los muebles de cocina"


def test_router_detecta_varias_intenciones_sin_partir_pedidos_simples():
    d = rutear_por_reglas(PEDIDO)
    assert d.es_multiple and [x.agente for x in d.subpedidos] == ["administrativo", "proyectos"]
    for simple in ["Haceme un presupuesto para Sofía de 2 ambientes y 3 renders",
                   "Se atrasaron los muebles de cocina de Gómez, pasalo al 25/11 y avisale",
                   "Terminé la etapa de diseño con Valentina, ¿ya le puedo cobrar el saldo?"]:
        assert not rutear_por_reglas(simple).es_multiple, simple


def test_delega_en_paralelo_y_consolida_una_sola_aprobacion(svc, deps):
    th, v = conversar(svc, PEDIDO)
    assert v["resumen_turno"]["nodos"] == ["carga_contexto", "router", "administrativo", "proyectos", "consolidador"]
    a = v["pendiente"]["accion"]
    assert a["agente"] == "multiagente" and a["agentes"] == ["administrativo", "proyectos"]
    assert [o["tool"] for o in a["operaciones"]] == ["emitir_factura", "actualizar_hito", "enviar_mensaje"]
    assert a["riesgo"] == "alto" and a["efecto_externo"]
    # el agente de proyectos resolvió "avisale" (sin nombre) con el pedido completo
    assert a["operaciones"][2]["args"]["destinatario"] == "martin.gomez@example.com"
    # consolidación ≠ concatenación: cruce plata × tiempo
    assert any("contra entrega" in o for o in a["observaciones"])
    texto = v["mensajes"][-1]["texto"]
    assert "**Administración**" in texto and "**Proyectos**" in texto and "Para revisar" in texto

    r = aprobar(svc, th, v)
    assert r["estado"] == "ejecutado" and [x["estado"] for x in r["resultado_ejecucion"]] == ["ejecutada"] * 3
    assert deps.db.one("SELECT estado FROM hitos WHERE id='HIT-07'")["estado"] == "atrasado"
    assert deps.db.one("SELECT factura_numero FROM cobros WHERE id='COB-02'")["factura_numero"]


def test_multi_informativo_no_pide_aprobacion(svc):
    th, v = conversar(svc, "¿Qué entregas tengo esta semana? Y además decime quién me debe plata")
    assert v["estado"] == "informativo" and v["pendiente"] is None
    assert "Próximos 7 días" in v["mensajes"][-1]["texto"] and "Cobros pendientes" in v["mensajes"][-1]["texto"]


def test_modificado_redespacha_a_todos_los_agentes(svc, deps):
    th, v = conversar(svc, PEDIDO)
    nuevo = "Hola Martín! Te aviso que los muebles de cocina vienen con unos días de demora. Te confirmo fecha. Mora"
    v2 = svc.decidir(th, {"decision": "modificado", "accion_hash": v["pendiente"]["accion_hash"],
                          "correccion": "la nueva fecha de los muebles es el 27/11", "cambios": {"2": {"cuerpo": nuevo}}})
    a2 = v2["pendiente"]["accion"]
    assert a2["version"] == 2 and a2["agentes"] == ["administrativo", "proyectos"]
    assert a2["operaciones"][1]["args"]["fecha"] == "2026-11-27"   # la corrección llegó al agente de proyectos
    assert a2["operaciones"][2]["args"]["cuerpo"] == nuevo          # el cambio estructurado, por índice global
    assert a2["operaciones"][0]["tool"] == "emitir_factura"         # administración también volvió a correr
    nodos = [t["nodo"] for t in v2["trazas_turno"]]
    assert nodos.count("administrativo") == 2 and nodos.count("proyectos") == 2


def test_falla_parcial_de_un_agente_no_tumba_el_resto(svc, monkeypatch):
    class Roto(registro.AGENTES_CLASES["proyectos"]):
        def local(self, e):
            raise TimeoutError("calendario no responde")
    monkeypatch.setitem(registro.AGENTES_CLASES, "proyectos", Roto)
    th, v = conversar(svc, PEDIDO)
    a = v["pendiente"]["accion"]
    assert [o["tool"] for o in a["operaciones"]] == ["emitir_factura"]
    assert any("Proyectos tuvo problemas" in o for o in a["observaciones"])
    assert "No pude completar esta parte" in v["mensajes"][-1]["texto"]


def test_ejecutor_valida_cada_operacion_contra_el_agente_que_la_propuso(svc, deps):
    th, v = conversar(svc, PEDIDO)
    a = v["pendiente"]["accion"]
    op = Operacion.model_validate({**a["operaciones"][0], "agente": "contenidos"})  # factura "propuesta" por contenidos
    accion = AccionPendiente.model_validate(a)
    try:
        deps.policy.autorizar(accion, op, deps.tool_ctx, aprobada=True)
        raise AssertionError("debió bloquearse")
    except PermissionError as exc:
        assert "contenidos" in str(exc)


def test_consolidador_elimina_duplicados_y_avisa_destinatario_repetido(deps):
    msg = {"destinatario": "x@y.z", "canal": "email", "asunto": "a", "cuerpo": "c" * 30, "motivo": "m"}
    def res(agente, ops):
        acc = AccionPendiente(accion_id="t1-" + agente, agente=agente, resumen=agente, riesgo="medio",
                              efecto_externo=True,
                              operaciones=[Operacion(tool=t, args=a, descripcion=t, agente=agente) for t, a in ops])
        return agente, ResultadoAgente(respuesta=agente, accion=acc)
    _, accion, meta = consolidar([
        res("comercial", [("enviar_mensaje", msg)]),
        res("proyectos", [("enviar_mensaje", msg), ("enviar_mensaje", {**msg, "cuerpo": "d" * 30})]),
    ], turno=1, version=1, db=deps.db)
    assert len(accion.operaciones) == 2
    assert any("duplicada" in o for o in accion.observaciones)
    assert any("2 mensajes a x@y.z" in o for o in accion.observaciones)


def test_router_llm_con_subpedidos(settings):
    llm = FakeLLM({"DecisionRouter": [
        {"agente": "administrativo", "confianza": 0.9, "justificacion": "dos tareas",
         "subpedidos": [{"agente": "administrativo", "pedido": "facturale el saldo a Martín Gómez"},
                        {"agente": "proyectos", "pedido": "avisale a Martín Gómez que se atrasan los muebles"}]},
        {"agente": "proyectos", "confianza": 0.9, "justificacion": "una sola área",
         "subpedidos": [{"agente": "proyectos", "pedido": "entregas de la semana"}, {"agente": "proyectos", "pedido": "hitos atrasados"}]},
    ]})
    svc = MoraService(Deps.build(settings, llm=llm), InMemorySaver())  # agentes sin guion -> fallback local
    th, v = conversar(svc, PEDIDO)
    assert v["router"]["metodo"] == "llm" and v["pendiente"]["accion"]["agentes"] == ["administrativo", "proyectos"]
    th2, v2 = conversar(svc, "¿Qué entregas tengo esta semana?")  # subpedidos de un solo agente: no es multi
    assert v2["resumen_turno"]["nodos"].count("proyectos") == 1
