from fastapi.testclient import TestClient

from mora.api import create_app


def test_flujo_completo_por_api(svc):
    c = TestClient(create_app(svc))
    assert c.get("/api/salud").json()["ok"]
    assert "Mora Estudio" in c.get("/").text
    th = c.post("/api/conversaciones", json={"cliente_id": "CLI-02"}).json()["thread_id"]
    v = c.post(f"/api/conversaciones/{th}/mensajes", json={"texto": "Mandale un recordatorio de pago"}).json()
    assert v["estado"] == "esperando_aprobacion"
    assert c.post(f"/api/conversaciones/{th}/mensajes", json={"texto": "otra"}).status_code == 409
    v2 = c.post(f"/api/conversaciones/{th}/decision",
                json={"decision": "aprobado", "accion_hash": v["pendiente"]["accion_hash"]}).json()
    assert v2["estado"] == "ejecutado"
    assert len(c.get("/api/salientes").json()) == 1
    assert c.get("/api/conversaciones").json()[0]["estado"] == "ejecutado"


def test_aclaracion_por_api(svc):
    c = TestClient(create_app(svc))
    th = c.post("/api/conversaciones", json={}).json()["thread_id"]
    v = c.post(f"/api/conversaciones/{th}/mensajes", json={"texto": "Fijate lo de Gómez"}).json()
    assert v["estado"] == "esperando_aclaracion"
    v2 = c.post(f"/api/conversaciones/{th}/aclaracion", json={"agente": "administrativo"}).json()
    assert v2["router"]["agente"] == "administrativo"


def test_conversacion_inexistente(svc):
    c = TestClient(create_app(svc))
    assert c.post("/api/conversaciones/nope/mensajes", json={"texto": "x"}).status_code == 404
