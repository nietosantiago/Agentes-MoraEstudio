"""Integración de facturación electrónica detrás de una interfaz.

Pendiente (contexto TFI §9): elegir la API real. Candidatas para monotributo / Factura C en ARCA:
AFIP SDK (homologación gratuita), TusFacturasAPP, Facturante. Hasta entonces se usa MockFacturacion,
que respeta el mismo contrato y marca cada comprobante como MOCK (no tiene validez fiscal).
"""
from __future__ import annotations

import hashlib
from typing import Protocol

from pydantic import BaseModel


class FacturacionError(RuntimeError):
    pass


class Comprobante(BaseModel):
    numero: str
    tipo: str
    cae: str
    proveedor: str


class FacturacionProvider(Protocol):
    name: str

    def emitir(self, *, cuit_receptor: str | None, concepto: str, monto: float, idempotency_key: str) -> Comprobante:
        ...


class MockFacturacion:
    """Simula la API: numeración correlativa y CAE ficticio. `fallar=True` simula caída del servicio."""

    name = "mock"

    def __init__(self, db, punto_venta: str = "0001", fallar: bool = False):
        self.db, self.pv, self.fallar = db, punto_venta, fallar

    def emitir(self, *, cuit_receptor, concepto, monto, idempotency_key) -> Comprobante:
        if self.fallar:
            raise FacturacionError("servicio de facturación no disponible (simulado)")
        if monto <= 0:
            raise FacturacionError("monto inválido")
        nums = [int(r["numero"].split("-")[-1]) for r in self.db.query("SELECT numero FROM facturas")]
        numero = f"C-{self.pv}-{(max(nums, default=0) + 1):08d}"
        cae = "MOCK-" + hashlib.sha1(idempotency_key.encode()).hexdigest()[:10].upper()
        return Comprobante(numero=numero, tipo="C", cae=cae, proveedor=self.name)
