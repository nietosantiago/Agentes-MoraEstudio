"""Acceso a datos con un único esquema para SQLite (desarrollo/tests) y PostgreSQL (Supabase).

Las consultas se escriben con placeholders `?`; el adaptador los traduce a `%s` para psycopg.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .config import Settings

SCHEMA = Path(__file__).with_name("schema.sql")
TABLAS_SEED = ["clientes", "leads", "servicios", "presupuestos", "facturas", "cobros", "obras", "hitos",
               "eventos", "posts"]


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.RLock()
        if settings.es_postgres:
            import psycopg
            from psycopg.rows import dict_row

            self.kind = "postgres"
            self._conn = psycopg.connect(settings.database_url, autocommit=True, row_factory=dict_row)
        else:
            self.kind = "sqlite"
            settings.runtime_dir.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(settings.sqlite_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.kind == "postgres" else sql

    def query(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(self._sql(sql), tuple(params))
            return [dict(r) for r in cur.fetchall()]

    def one(self, sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: tuple | list = ()) -> int:
        with self._lock:
            cur = self._conn.execute(self._sql(sql), tuple(params))
            if self.kind == "sqlite":
                self._conn.commit()
            return cur.rowcount

    def insert(self, tabla: str, fila: dict[str, Any], on_conflict_nothing: bool = False) -> int:
        cols = list(fila)
        vals = [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in fila.values()]
        sql = f"INSERT INTO {tabla} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
        if on_conflict_nothing:
            sql += " ON CONFLICT DO NOTHING"
        return self.execute(sql, vals)

    def init_schema(self) -> None:
        for stmt in SCHEMA.read_text(encoding="utf-8").split(";"):
            stmt = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip()
            if stmt:
                self.execute(stmt)

    def seed(self, seed_dir: Path) -> None:
        """Carga datos de ejemplo solo si las tablas están vacías (idempotente)."""
        for tabla in TABLAS_SEED:
            path = seed_dir / f"{tabla}.json"
            if not path.exists() or self.one(f"SELECT COUNT(*) AS n FROM {tabla}")["n"]:
                continue
            for fila in json.loads(path.read_text(encoding="utf-8")):
                self.insert(tabla, fila, on_conflict_nothing=True)

    def reset(self) -> None:
        for tabla in TABLAS_SEED + ["mensajes_salientes", "efectos", "conversaciones"]:
            self.execute(f"DELETE FROM {tabla}")
