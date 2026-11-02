"""Tests contra PostgreSQL real (checkpointer + datos). Se activan con MORA_TEST_DATABASE_URL."""
import pytest

from mora.deps import Deps
from mora.service import MoraService, make_checkpointer

from .conftest import PG_URL, aprobar, conversar

pytestmark = pytest.mark.skipif(not PG_URL, reason="MORA_TEST_DATABASE_URL no definida")


@pytest.fixture
def pg_deps(settings):
    from dataclasses import replace

    s = replace(settings, database_url=PG_URL)
    d = Deps.build(s, seed=False)
    d.db.reset()
    d.db.seed(s.seed_dir)
    return d


def test_flujo_hitl_con_postgres_saver(pg_deps):
    svc = MoraService(pg_deps, make_checkpointer(pg_deps))
    th, v = conversar(svc, "Facturale el saldo a Martín Gómez")
    assert pg_deps.db.kind == "postgres" and v["estado"] == "esperando_aprobacion"
    svc2 = MoraService(pg_deps, make_checkpointer(pg_deps))  # "otro proceso": nuevo saver, misma base
    v2 = aprobar(svc2, th, svc2.vista(th))
    assert v2["estado"] == "ejecutado"
    assert pg_deps.db.one("SELECT factura_numero FROM cobros WHERE id='COB-02'")["factura_numero"]
