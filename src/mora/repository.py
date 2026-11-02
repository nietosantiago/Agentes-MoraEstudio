"""Acceso a los sistemas autoritativos del estudio (hoy JSON; mañana Drive/Sheets/CRM vía MCP)."""
from __future__ import annotations

import json
from functools import cached_property
from pathlib import Path


class EstudioRepo:
    def __init__(self, estudio_dir: Path):
        self.dir = estudio_dir

    def _load(self, name: str) -> dict:
        return json.loads((self.dir / name).read_text(encoding="utf-8"))

    @cached_property
    def _clientes(self) -> dict:
        return self._load("clientes.json")

    @cached_property
    def tarifario(self) -> dict:
        return self._load("tarifario.json")

    @cached_property
    def agenda(self) -> dict:
        return self._load("agenda.json")

    def cliente_por_contacto(self, contacto: str) -> dict | None:
        contacto = contacto.strip().lower()
        for c in self._clientes["clientes"]:
            if contacto in (c["email"].lower(), c["telefono"]):
                return c
        return None

    def cliente(self, cliente_id: str) -> dict | None:
        return next((c for c in self._clientes["clientes"] if c["id"] == cliente_id), None)

    def proyectos_de(self, cliente_id: str) -> list[dict]:
        return [p for p in self._clientes["proyectos"] if p["cliente_id"] == cliente_id]

    def proyecto(self, proyecto_id: str) -> dict | None:
        return next((p for p in self._clientes["proyectos"] if p["id"] == proyecto_id), None)
