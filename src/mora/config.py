"""Configuración centralizada (C3): secretos y parámetros fuera del código."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    llm: str = "local"  # "local" (determinístico) | "gemini"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    hoy: date = field(default_factory=date.today)
    data_dir: Path = ROOT / "data"
    skills_dir: Path = ROOT / "skills"
    runtime_dir: Path = ROOT / "data" / "runtime"

    @property
    def estudio_dir(self) -> Path:
        return self.data_dir / "estudio"

    @property
    def docs_dir(self) -> Path:
        return self.data_dir / "docs"


def load_settings(**overrides) -> Settings:
    load_dotenv(ROOT / ".env")
    hoy_raw = os.getenv("MORA_HOY") or ""
    runtime = os.getenv("MORA_RUNTIME_DIR") or "data/runtime"
    values = dict(
        llm=os.getenv("MORA_LLM", "local"),
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        gemini_model=os.getenv("MORA_GEMINI_MODEL", "gemini-2.5-flash"),
        hoy=date.fromisoformat(hoy_raw) if hoy_raw else date.today(),
        runtime_dir=(ROOT / runtime) if not Path(runtime).is_absolute() else Path(runtime),
    )
    values.update(overrides)
    return Settings(**values)
