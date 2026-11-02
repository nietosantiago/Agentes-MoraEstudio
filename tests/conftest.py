import os
from datetime import date
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from mora.config import load_settings
from mora.deps import Deps
from mora.llm.base import LLMError
from mora.service import MoraService
from mora.tracing import report_usage

HOY = date(2026, 11, 2)  # lunes


@pytest.fixture
def settings(tmp_path: Path):
    return load_settings(hoy=HOY, runtime_dir=tmp_path / "runtime", llm="local", database_url="")


@pytest.fixture
def deps(settings):
    return Deps.build(settings)


@pytest.fixture
def svc(deps):
    return MoraService(deps, InMemorySaver())


class FakeLLM:
    """LLM guionado: devuelve respuestas en orden por schema y reporta uso de tokens."""

    name = "fake"

    def __init__(self, guion: dict[str, list], tokens=(100, 20)):
        self.guion = {k: list(v) for k, v in guion.items()}
        self.tokens = tokens
        self.prompts: list[str] = []

    def generate_structured(self, *, system, prompt, schema):
        self.prompts.append(prompt)
        cola = self.guion.get(schema.__name__)
        if not cola:
            raise LLMError("sin guion")
        report_usage("fake-model", *self.tokens)
        return schema.model_validate(cola.pop(0))


def aprobar(svc, th, v, **extra):
    return svc.decidir(th, {"decision": "aprobado", "accion_hash": v["pendiente"]["accion_hash"], **extra})


def conversar(svc, texto, cliente=None):
    th = svc.nueva_conversacion(cliente)
    return th, svc.enviar(th, texto)


def salientes(deps):
    return deps.db.query("SELECT * FROM mensajes_salientes")


PG_URL = os.getenv("MORA_TEST_DATABASE_URL")
