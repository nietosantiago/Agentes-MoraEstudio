"""Abstracción de proveedor (C3/C4): los agentes programan contra una interfaz, no contra Gemini."""
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
        """Devuelve una instancia validada de `schema` o levanta LLMError."""
        ...


def get_provider(settings: Settings) -> LLMProvider | None:
    """None = modo local determinístico (los agentes usan reglas/plantillas)."""
    if settings.llm == "gemini":
        from .gemini import GeminiProvider

        if not settings.gemini_api_key:
            raise LLMError("MORA_LLM=gemini pero falta GEMINI_API_KEY en .env")
        return GeminiProvider(api_key=settings.gemini_api_key, model=settings.gemini_model)
    return None
