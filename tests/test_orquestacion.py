import sqlite3
from datetime import datetime, timedelta

from langgraph.checkpoint.sqlite import SqliteSaver

from mora.agents import workers
from mora.agents.critic import criticar
from mora.contracts import Clasificacion, ConsolidatedAnswer
from mora.memory import MemoryItem
from mora.service import MoraSystem

from .conftest import approve, outbox, solicitud


def test_run_se_detiene_antes_de_cualquier_efecto(system, settings):
    v = system.start(solicitud("01_lead_presupuesto.json"))
    assert v.status == "waiting_for_approval" and v.approval_request
    tools = [a["tool"] for a in v.approval_request["acciones"]]
    assert tools == ["registrar_presupuesto", "enviar_respuesta"]
    assert outbox(settings) == []
    assert system.deps.ledger.count() == 0


def test_presupuesto_aprobado_ejecuta_una_vez_y_recuerda(system, settings):
    v = system.start(solicitud("01_lead_presupuesto.json"))
    assert "4.506,04" in v.approval_request["respuesta"]["answer"]  # 140 m² vivienda, 2 etapas + IVA
    v2 = approve(system, v)
    assert v2.status == "completed"
    assert {r["status"] for r in v2.resultados} == {"executed"}
    assert len(outbox(settings)) == 1
    mem = [m.content for m in system.deps.memory.retrieve("juana.perez@example.com")]
    assert any("PRES-SOL-0001" in m for m in mem)


def test_rechazo_no_produce_efectos(system, settings):
    v = system.start(solicitud("02_cliente_avance.json"))
    v2 = system.decide(v.run_id, {"decision": "reject", "actor": "t",
                                  "proposal_hash": v.approval_request["proposal_hash"]})
    assert v2.status == "rejected" and outbox(settings) == []


def test_aprobacion_desactualizada_no_ejecuta(system, settings):
    v = system.start(solicitud("02_cliente_avance.json"))
    v2 = system.decide(v.run_id, {"decision": "approve", "actor": "t", "proposal_hash": "hash-viejo"})
    assert v2.status == "waiting_for_approval" and v2.approval_request  # vuelve a pedir revisión
    assert outbox(settings) == []


def test_edicion_crea_version_nueva_y_requiere_nueva_aprobacion(system, settings):
    v = system.start(solicitud("02_cliente_avance.json"))
    h1 = v.approval_request["proposal_hash"]
    cuerpo = "Hola Laura, los planos se presentan el 12/11. Te avisamos apenas estén.\n\nEquipo Mora Estudio"
    v2 = system.decide(v.run_id, {"decision": "edit", "actor": "sofia", "proposal_hash": h1,
                                  "edited_answer": cuerpo})
    assert v2.approval_request["version"] == 2 and v2.approval_request["proposal_hash"] != h1
    assert outbox(settings) == []
    v3 = system.decide(v.run_id, {"decision": "approve", "actor": "sofia", "proposal_hash": h1})  # hash viejo
    assert v3.approval_request and outbox(settings) == []
    v4 = approve(system, v3)
    assert v4.status == "completed" and outbox(settings)[0]["cuerpo"] == cuerpo


def test_aprobacion_parcial(system, settings):
    v = system.start(solicitud("04_agenda_reunion.json"))
    v2 = approve(system, v, approved_action_ids=["enviar-respuesta-1"])
    st = {r["action_id"]: r["status"] for r in v2.resultados}
    assert st == {"crear-evento-1": "blocked", "enviar-respuesta-1": "executed"}
    assert not (settings.runtime_dir / "agenda_nuevos_eventos.jsonl").exists()


def test_reanudar_desde_otro_proceso_y_recovery_idempotente(deps, settings):
    db = settings.runtime_dir / "ck.sqlite"
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    s1 = MoraSystem(deps, SqliteSaver(sqlite3.connect(db, check_same_thread=False)))
    v = s1.start(solicitud("03_reclamo_obra.json"))
    assert v.approval_request["escalar_a_humano"] is True
    del s1  # "reinicio" del proceso

    s2 = MoraSystem(deps, SqliteSaver(sqlite3.connect(db, check_same_thread=False)))
    v2 = approve(s2, s2.get(v.run_id))
    assert v2.status == "completed" and len(outbox(settings)) == 1

    # Recovery: re-ejecutar desde el checkpoint previo a `execute` (p.ej. crash tras el efecto)
    cfg = {"configurable": {"thread_id": v.run_id}}
    antes = next(sn for sn in s2.graph.get_state_history(cfg) if sn.next == ("execute",))
    s2.graph.invoke(None, antes.config)
    final = s2.get(v.run_id)
    assert {r["status"] for r in final.resultados} == {"skipped_duplicate"}
    assert len(outbox(settings)) == 1  # el mail NO se envió dos veces


def test_presupuesto_sin_datos_pide_informacion(system):
    sol = {"id": "SOL-9", "remitente": "nuevo@example.com", "asunto": "Presupuesto",
           "cuerpo": "Hola, ¿me pasan un presupuesto de honorarios?"}
    v = system.start(sol)
    r = v.approval_request["respuesta"]
    assert r["status"] == "partial"
    assert "¿Cuántos m² aproximados" in r["answer"]
    assert [a["tool"] for a in v.approval_request["acciones"]] == ["enviar_respuesta"]


def test_falla_de_worker_es_visible_y_no_rompe_el_grafo(system, monkeypatch):
    def roto(*a, **k):
        raise TimeoutError("simulado")
    monkeypatch.setitem(workers.WORKERS, "documental", roto)
    v = system.start(solicitud("02_cliente_avance.json"))
    r = v.approval_request["respuesta"]
    assert v.status == "waiting_for_approval" and r["status"] == "partial"
    assert any("documental" in m for m in r["missing_information"])


def test_fan_out_en_paralelo_registra_todos_los_workers(system):
    v = system.start(solicitud("03_reclamo_obra.json"))
    roles = sorted(o["role"] for o in v.state["worker_outputs"])
    assert roles == ["agenda", "documental"]
    assert v.approval_request["respuesta"]["contributing_agents"] == ["agenda", "documental", "atencion"]


def test_critic_detecta_descuentos_y_montos(deps):
    c = Clasificacion(intencion="presupuesto", resumen="x")
    ans = ConsolidatedAnswer(asunto="a", answer="Te hacemos un descuento del 10%. Total USD 1", status="complete")
    crit = criticar(ans, c, [])
    assert not crit.passed and any("descuento" in i.lower() for i in crit.critical_issues)
    assert any("firma" in i for i in crit.critical_issues)


def test_memoria_respeta_scope_y_ttl(deps):
    m = deps.memory
    m.write(MemoryItem(cliente_key="CLI-001", kind="hecho", content="vigente", source="t", confidence=0.9))
    m.write(MemoryItem(cliente_key="CLI-001", kind="hecho", content="vencido", source="t", confidence=0.9,
                       expires_at=datetime.now() - timedelta(days=1)))
    m.write(MemoryItem(cliente_key="CLI-002", kind="hecho", content="otro cliente", source="t", confidence=0.9))
    assert not m.write(MemoryItem(cliente_key="CLI-001", kind="hecho", content="dudoso", source="t",
                                  confidence=0.3))
    assert [i.content for i in m.retrieve("CLI-001")] == ["vigente"]


def test_skills_progressive_disclosure(deps):
    names = {s.name for s in deps.skills.catalog}
    assert names == {"respuesta-cliente", "presupuesto-honorarios", "gestion-reclamos", "coordinar-reunion"}
    meta = deps.skills.select("presupuesto")
    skill = deps.skills.load(meta)
    assert "calcular_honorarios" in skill.body
    assert "dirección" in skill.reference("politica_descuentos.md")
