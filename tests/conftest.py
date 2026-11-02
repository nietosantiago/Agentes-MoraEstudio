import json
from datetime import date
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from mora.config import ROOT, load_settings
from mora.deps import Deps
from mora.service import MoraSystem

SOL_DIR = ROOT / "data" / "solicitudes"


def solicitud(nombre: str) -> dict:
    return json.loads((SOL_DIR / nombre).read_text(encoding="utf-8"))


@pytest.fixture
def settings(tmp_path: Path):
    return load_settings(hoy=date(2026, 11, 2), runtime_dir=tmp_path / "runtime", llm="local")


@pytest.fixture
def deps(settings):
    return Deps.build(settings)


@pytest.fixture
def system(deps):
    return MoraSystem(deps, InMemorySaver())


def approve(system, view, **extra):
    return system.decide(view.run_id, {"decision": "approve", "actor": "test",
                                       "proposal_hash": view.approval_request["proposal_hash"], **extra})


def outbox(settings) -> list[dict]:
    p = settings.runtime_dir / "outbox.jsonl"
    return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []
