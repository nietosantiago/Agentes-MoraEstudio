"""Configuración centralizada: secretos y parámetros fuera del código."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    llm: str = "local"                       # "local" (reglas, sin API key) | "gemini"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    # Precios por 1M tokens para estimar costo (configurables: verificar la lista vigente de Google)
    precio_input_1m_usd: float = 0.30
    precio_output_1m_usd: float = 2.50
    umbral_router: float = 0.60              # debajo de esto el router pregunta en vez de adivinar
    database_url: str = ""                   # vacío = SQLite local; postgresql://... = Postgres/Supabase
    hoy: date = field(default_factory=date.today)
    runtime_dir: Path = ROOT / "data" / "runtime"
    seed_dir: Path = ROOT / "data" / "seed"
    skills_dir: Path = ROOT / "skills"

    @property
    def es_postgres(self) -> bool:
        return self.database_url.startswith(("postgres://", "postgresql://"))

    @property
    def sqlite_path(self) -> Path:
        return self.runtime_dir / "estudio.sqlite"


def load_settings(**overrides) -> Settings:
    load_dotenv(ROOT / ".env")
    hoy = os.getenv("MORA_HOY") or ""
    runtime = os.getenv("MORA_RUNTIME_DIR") or "data/runtime"
    values = dict(
        llm=os.getenv("MORA_LLM", "local"),
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        gemini_model=os.getenv("MORA_GEMINI_MODEL", "gemini-2.5-flash"),
        precio_input_1m_usd=float(os.getenv("MORA_PRECIO_INPUT_1M_USD", "0.30")),
        precio_output_1m_usd=float(os.getenv("MORA_PRECIO_OUTPUT_1M_USD", "2.50")),
        umbral_router=float(os.getenv("MORA_UMBRAL_ROUTER", "0.60")),
        database_url=os.getenv("MORA_DATABASE_URL", ""),
        hoy=date.fromisoformat(hoy) if hoy else date.today(),
        runtime_dir=Path(runtime) if Path(runtime).is_absolute() else ROOT / runtime,
    )
    values.update(overrides)
    return Settings(**values)
