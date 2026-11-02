import sqlite3

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from mora.deps import Deps
from mora.integrations.facturacion import MockFacturacion
from mora.service import MoraService

from .conftest import FakeLLM, aprobar, conversar, salientes


def test_informativo_termina_sin_revision(svc, deps):
    th, v = conversar(svc, "¿Cuánto facturé en octubre?")
    assert v["estado"] == "informativo" and v["pendiente"] is None
    assert "$ 1.125.000" in v["mensajes"][-1]["texto"]
    assert v["resumen_turno"]["nodos"] == ["carga_contexto", "router", "administrativo"]
    assert salientes(deps) == []


def test_accion_externa_pausa_antes_del_efecto(svc, deps):
    th, v = conversar(svc, "Facturale el saldo a Martín Gómez")
    a = v["pendiente"]["accion"]
    assert v["estado"] == "esperando_aprobacion" and a["riesgo"] == "alto" and a["efecto_externo"]
    antes = len(deps.db.query("SELECT * FROM facturas"))
    assert deps.db.one("SELECT factura_numero FROM cobros WHERE id='COB-02'")["factura_numero"] is None
    v2 = aprobar(svc, th, v)
    assert v2["estado"] == "ejecutado"
    assert len(deps.db.query("SELECT * FROM facturas")) == antes + 1
    assert deps.db.one("SELECT factura_numero FROM cobros WHERE id='COB-02'")["factura_numero"].startswith("C-0001-")


def test_rechazado_no_produce_efectos(svc, deps):
    th, v = conversar(svc, "Mandale un recordatorio de pago a Gómez")
    v2 = svc.decidir(th, {"decision": "rechazado", "accion_hash": v["pendiente"]["accion_hash"], "comentario": "ya le hablé"})
    assert v2["estado"] == "rechazado" and salientes(deps) == []


def test_modificado_con_cambios_crea_version_nueva(svc, deps):
    th, v = conversar(svc, "Mandale un recordatorio de pago a Gómez")
    h1 = v["pendiente"]["accion_hash"]
    nuevo = "Hola Martín! Te recuerdo el saldo de la obra. Cuando puedas me avisás. Mora — Estudio de Interiorismo"
    v2 = svc.decidir(th, {"decision": "modificado", "accion_hash": h1, "cambios": {"0": {"cuerpo": nuevo}}})
    a2 = v2["pendiente"]["accion"]
    assert a2["version"] == 2 and v2["pendiente"]["accion_hash"] != h1
    assert salientes(deps) == []
    v3 = svc.decidir(th, {"decision": "aprobado", "accion_hash": h1})  # aprobar la versión vieja no vale
    assert v3["pendiente"] and v3["pendiente"]["accion"]["version"] == 2 and salientes(deps) == []
    v4 = aprobar(svc, th, v3)
    assert v4["estado"] == "ejecutado" and salientes(deps)[0]["cuerpo"] == nuevo


def test_modificado_con_correccion_vuelve_al_agente(svc, deps):
    th, v = conversar(svc, "Se atrasaron los muebles de cocina de Gómez, pasalo al 25/11")
    assert v["pendiente"]["accion"]["operaciones"][0]["args"]["fecha"] == "2026-11-25"
    v2 = svc.decidir(th, {"decision": "modificado", "accion_hash": v["pendiente"]["accion_hash"],
                          "correccion": "no, la nueva fecha es el 27/11"})
    op = v2["pendiente"]["accion"]["operaciones"][0]
    assert op["args"]["fecha"] == "2026-11-27" and v2["pendiente"]["accion"]["version"] == 2
    aprobar(svc, th, v2)
    assert deps.db.one("SELECT fecha FROM hitos WHERE id='HIT-07'")["fecha"] == "2026-11-27"


def test_baja_confianza_pregunta_y_continua(svc):
    th, v = conversar(svc, "¿Cuándo?")
    assert v["estado"] == "esperando_aclaracion" and v["pendiente"]["tipo"] == "aclaracion"
    v2 = svc.aclarar(th, "proyectos")
    assert v2["estado"] == "informativo" and v2["router"]["metodo"] == "humano"
    assert "Próximos 7 días" in v2["mensajes"][-1]["texto"]


def test_no_se_puede_mandar_otro_mensaje_con_decision_pendiente(svc):
    th, v = conversar(svc, "Facturale el saldo a Martín Gómez")
    try:
        svc.enviar(th, "otra cosa")
        raise AssertionError("debió fallar")
    except RuntimeError as exc:
        assert "pendiente" in str(exc)


def test_idempotencia_al_reintentar_el_ejecutor(svc, deps):
    th, v = conversar(svc, "Facturale el saldo a Martín Gómez")
    aprobar(svc, th, v)
    n = len(deps.db.query("SELECT * FROM facturas"))
    cfg = {"configurable": {"thread_id": th}}
    antes = next(sn for sn in svc.graph.get_state_history(cfg) if sn.next == ("ejecutor",))
    svc.graph.invoke(None, antes.config)  # recovery / time travel: re-ejecuta el nodo ejecutor
    assert len(deps.db.query("SELECT * FROM facturas")) == n  # NO hay factura duplicada
    assert svc.vista(th)["resultado_ejecucion"][0]["estado"] == "duplicada_omitida"


def test_regresion_idempotencia_aislada_por_conversacion(svc, deps):
    """Bug real encontrado en desarrollo: la idempotency_key no incluía el thread, así que dos conversaciones
    con el mismo accion_id ('t1-proyectos', operación 0) se pisaban y la segunda quedaba 'duplicada_omitida'."""
    th1, v1 = conversar(svc, "Se atrasaron los muebles de cocina de Gómez, pasalo al 25/11")
    th2, v2 = conversar(svc, "Marcá como cumplida la planta de equipamiento de Valentina")
    assert v1["pendiente"]["accion"]["accion_id"] == v2["pendiente"]["accion"]["accion_id"] == "t1-proyectos"
    assert aprobar(svc, th1, v1)["estado"] == "ejecutado"
    r2 = aprobar(svc, th2, v2)
    assert r2["resultado_ejecucion"][0]["estado"] == "ejecutada"
    assert deps.db.one("SELECT estado FROM hitos WHERE id='HIT-03'")["estado"] == "cumplido"


def test_dos_propuestas_sobre_el_mismo_cobro_no_facturan_dos_veces(svc, deps):
    th1, v1 = conversar(svc, "Facturale el saldo a Martín Gómez")
    th2, v2 = conversar(svc, "Emití la factura del saldo de Martín Gómez")
    assert aprobar(svc, th1, v1)["estado"] == "ejecutado"
    r = aprobar(svc, th2, v2)
    assert r["estado"] == "ejecutado_con_errores" and r["resultado_ejecucion"][0]["estado"] == "bloqueada"


def test_falla_de_facturacion_es_visible_y_no_se_reintenta(settings):
    deps = Deps.build(settings)
    deps.facturacion = MockFacturacion(deps.db, fallar=True)
    svc = MoraService(deps, InMemorySaver())
    th, v = conversar(svc, "Facturale el saldo a Martín Gómez")
    r = aprobar(svc, th, v)
    assert r["estado"] == "ejecutado_con_errores" and r["resultado_ejecucion"][0]["estado"] == "fallida"
    assert "no disponible" in r["mensajes"][-1]["texto"]
    assert deps.db.one("SELECT estado FROM efectos")["estado"] == "fallida"


def test_conversacion_sobrevive_reinicio_de_proceso(settings):
    path = settings.runtime_dir / "ck.sqlite"
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    s1 = MoraService(Deps.build(settings), SqliteSaver(sqlite3.connect(path, check_same_thread=False)))
    th, v = conversar(s1, "Facturale el saldo a Martín Gómez")
    del s1
    s2 = MoraService(Deps.build(settings), SqliteSaver(sqlite3.connect(path, check_same_thread=False)))
    v2 = s2.vista(th)
    assert v2["estado"] == "esperando_aprobacion"
    assert aprobar(s2, th, v2)["estado"] == "ejecutado"


def test_varios_turnos_en_la_misma_conversacion(svc):
    th = svc.nueva_conversacion("CLI-02")
    svc.enviar(th, "¿Cómo va la obra?")
    v = svc.enviar(th, "¿Cuánto me debe?")
    assert v["router"]["agente"] == "administrativo" and "$ 1.340.000" in v["mensajes"][-1]["texto"]
    assert {t["turno"] for t in svc.graph.get_state({"configurable": {"thread_id": th}}).values["trazas"]} == {1, 2}


def test_trazas_registran_tokens_y_costo_con_llm(settings):
    llm = FakeLLM({
        "DecisionRouter": [{"agente": "proyectos", "confianza": 0.95, "justificacion": "pregunta por entregas"}],
        "PasoAgente": [
            {"tipo": "tool", "tool": "proximos_hitos", "args_json": "{\"dias\": 7}"},
            {"tipo": "final", "respuesta": "Esta semana tenés la planta de equipamiento el viernes."},
        ],
    }, tokens=(1200, 80))
    svc = MoraService(Deps.build(settings, llm=llm), InMemorySaver())
    th, v = conversar(svc, "¿Qué entregas tengo esta semana?")
    t = {x["nodo"]: x for x in v["trazas_turno"]}
    assert t["router"]["tokens_in"] == 1200 and t["proyectos"]["llamadas_llm"] == 2
    assert v["resumen_turno"]["costo_usd"] > 0 and v["estado"] == "informativo"
    assert t["proyectos"]["tools"] == ["proximos_hitos"] and t["proyectos"]["modo"] == "llm"
