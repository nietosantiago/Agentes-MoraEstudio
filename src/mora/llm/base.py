"""Abstracción de proveedor: el sistema programa contra una interfaz, no contra Gemini."""
from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from ..config import Settings

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class LLMProvider(Protocol):
    name: str

    def generate_structured(self, *, system: str, prompt: str, schema: type[T]) -> T:
        """Devuelve una instancia validada de `schema` o levanta LLMError. Reporta uso con tracing.report_usage."""
        ...


def get_provider(settings: Settings) -> LLMProvider | None:
    """None = modo local (reglas): sin API key, determinístico, base para tests y baseline de evaluación."""
    if settings.llm == "gemini":
        from .gemini import GeminiProvider

        if not settings.gemini_api_key:
            raise LLMError("MORA_LLM=gemini pero falta GEMINI_API_KEY en .env")
        return GeminiProvider(api_key=settings.gemini_api_key, model=settings.gemini_model)
    return None
