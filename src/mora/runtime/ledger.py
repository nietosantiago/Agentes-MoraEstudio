"""Ledger de efectos (idempotencia) + event log (C11/C12).

checkpoint -> permite continuar · event log -> permite reconstruir · ledger -> evita repetir el efecto.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path


class ActionLedger:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS effects(
              idempotency_key TEXT PRIMARY KEY, run_id TEXT, tool TEXT, status TEXT,
              result TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS events(
              id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, actor TEXT, event TEXT,
              data TEXT, created_at TEXT);
            """
        )

    def get(self, key: str) -> dict | None:
        row = self._db.execute("SELECT status, result FROM effects WHERE idempotency_key=?", (key,)).fetchone()
        return {"status": row[0], "result": json.loads(row[1])} if row else None

    def reserve(self, key: str, run_id: str, tool: str) -> bool:
        """Marca 'in_progress' antes del efecto. False si ya existía (duplicado)."""
        try:
            with self._db:
                self._db.execute("INSERT INTO effects VALUES(?,?,?,?,?,?)",
                                 (key, run_id, tool, "in_progress", "null", datetime.now().isoformat()))
            return True
        except sqlite3.IntegrityError:
            return False

    def complete(self, key: str, status: str, result: dict) -> None:
        with self._db:
            self._db.execute("UPDATE effects SET status=?, result=? WHERE idempotency_key=?",
                             (status, json.dumps(result, default=str), key))

    def count(self, run_id: str | None = None) -> int:
        q, p = "SELECT COUNT(*) FROM effects WHERE status='executed'", ()
        if run_id:
            q, p = q + " AND run_id=?", (run_id,)
        return self._db.execute(q, p).fetchone()[0]

    def log(self, run_id: str, actor: str, event: str, **data) -> None:
        with self._db:
            self._db.execute("INSERT INTO events(run_id, actor, event, data, created_at) VALUES(?,?,?,?,?)",
                             (run_id, actor, event, json.dumps(data, default=str), datetime.now().isoformat()))

    def events(self, run_id: str) -> list[dict]:
        rows = self._db.execute("SELECT actor, event, data, created_at FROM events WHERE run_id=? ORDER BY id",
                                (run_id,)).fetchall()
        return [{"actor": a, "event": e, **json.loads(d), "at": t} for a, e, d, t in rows]
