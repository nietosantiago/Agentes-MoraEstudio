"""API FastAPI + UI mínima (contexto TFI §5: FastAPI, no WhatsApp, para el TFI).

    uvicorn mora.api:app --reload      ->  http://localhost:8000
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .contracts import AGENTES, DecisionHumana
from .service import MoraService

STATIC = Path(__file__).with_name("static")


class NuevaConversacion(BaseModel):
    cliente_id: str | None = None
    titulo: str = ""


class Mensaje(BaseModel):
    texto: str


class Aclaracion(BaseModel):
    agente: str | None = None


def create_app(service: MoraService | None = None) -> FastAPI:
    app = FastAPI(title="Mora Estudio — sistema multiagente", version="0.2.0")
    svc = service or MoraService()
    app.state.svc = svc

    def _err(exc: Exception):
        code = 404 if isinstance(exc, KeyError) else 409
        raise HTTPException(status_code=code, detail=str(exc).strip("'"))

    @app.get("/", include_in_schema=False)
    def ui():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/salud")
    def salud():
        s = svc.deps.settings
        return {"ok": True, "llm": s.llm, "db": svc.deps.db.kind, "umbral_router": s.umbral_router,
                "marca": f"{svc.deps.marca.name}@{svc.deps.marca.version}", "agentes": list(AGENTES),
                "facturacion": svc.deps.facturacion.name}

    @app.get("/api/clientes")
    def clientes():
        return svc.deps.db.query("SELECT id, nombre, ciudad FROM clientes ORDER BY nombre")

    @app.get("/api/conversaciones")
    def conversaciones():
        return svc.listar_conversaciones()

    @app.post("/api/conversaciones")
    def crear(body: NuevaConversacion):
        return {"thread_id": svc.nueva_conversacion(body.cliente_id, body.titulo)}

    @app.get("/api/conversaciones/{thread_id}")
    def ver(thread_id: str):
        return svc.vista(thread_id)

    @app.post("/api/conversaciones/{thread_id}/mensajes")
    def mensaje(thread_id: str, body: Mensaje):
        try:
            return svc.enviar(thread_id, body.texto)
        except (KeyError, RuntimeError) as exc:
            _err(exc)

    @app.post("/api/conversaciones/{thread_id}/decision")
    def decision(thread_id: str, body: DecisionHumana):
        try:
            return svc.decidir(thread_id, body)
        except RuntimeError as exc:
            _err(exc)

    @app.post("/api/conversaciones/{thread_id}/aclaracion")
    def aclaracion(thread_id: str, body: Aclaracion):
        try:
            return svc.aclarar(thread_id, body.agente)
        except RuntimeError as exc:
            _err(exc)

    @app.get("/api/salientes")
    def salientes():
        """Lo que efectivamente salió del estudio (mensajes simulados)."""
        return svc.deps.db.query("SELECT * FROM mensajes_salientes ORDER BY enviado_en DESC")

    return app


def __getattr__(name: str):  # `uvicorn mora.api:app` crea la app recién al importarla
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
