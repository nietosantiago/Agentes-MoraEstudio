"""Memoria persistente por cliente (C10): scope, provenance, TTL y dos gates (write / retrieve).

No es estado de workflow (eso es el checkpointer) ni ground truth: datos autoritativos
(proyectos, tarifario, agenda) se consultan siempre en su sistema de origen.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["preferencia", "hecho", "interaccion"]


class MemoryItem(BaseModel):
    cliente_key: str              # cliente_id o contacto normalizado (scope)
    kind: Kind
    content: str = Field(max_length=300)
    source: str                   # provenance: run_id / "confirmado_por_humano"
    confidence: float = Field(ge=0, le=1)
    created_at: datetime = Field(default_factory=datetime.now)
    expires_at: datetime | None = None


class MemoryStore:
    MIN_CONFIDENCE = 0.6

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS memory(id INTEGER PRIMARY KEY, cliente_key TEXT, kind TEXT, content TEXT,"
            " source TEXT, confidence REAL, created_at TEXT, expires_at TEXT, UNIQUE(cliente_key, content))"
        )

    # write gate --------------------------------------------------------
    def write(self, item: MemoryItem) -> bool:
        if item.confidence < self.MIN_CONFIDENCE or not item.content.strip():
            return False
        with self._db:
            self._db.execute(
                "INSERT INTO memory(cliente_key, kind, content, source, confidence, created_at, expires_at)"
                " VALUES(?,?,?,?,?,?,?) ON CONFLICT(cliente_key, content) DO UPDATE SET"
                " source=excluded.source, created_at=excluded.created_at, expires_at=excluded.expires_at",
                (item.cliente_key, item.kind, item.content, item.source, item.confidence,
                 item.created_at.isoformat(), item.expires_at.isoformat() if item.expires_at else None),
            )
        return True

    # retrieve gate -----------------------------------------------------
    def retrieve(self, cliente_key: str, k: int = 5, now: datetime | None = None) -> list[MemoryItem]:
        now = now or datetime.now()
        rows = self._db.execute(
            "SELECT cliente_key, kind, content, source, confidence, created_at, expires_at FROM memory"
            " WHERE cliente_key=? AND (expires_at IS NULL OR expires_at > ?) ORDER BY created_at DESC LIMIT ?",
            (cliente_key, now.isoformat(), k),
        ).fetchall()
        cols = ["cliente_key", "kind", "content", "source", "confidence", "created_at", "expires_at"]
        return [MemoryItem(**dict(zip(cols, r))) for r in rows]

    @staticmethod
    def ttl(days: int) -> datetime:
        return datetime.now() + timedelta(days=days)
