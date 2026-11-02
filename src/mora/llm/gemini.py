"""Proveedor Gemini con structured output + validación Pydantic + un retry (C2)."""
from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .base import LLMError

T = TypeVar("T", bound=BaseModel)


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, temperature: float = 0.2, max_retries: int = 1):
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries

    def generate_structured(self, *, system: str, prompt: str, schema: type[T]) -> T:
        from google.genai import types

        last_error: Exception | None = None
        for _ in range(self.max_retries + 1):
            try:
                resp = self._client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        temperature=self.temperature,
                        response_mime_type="application/json",
                        response_schema=schema,
                    ),
                )
                return schema.model_validate_json(resp.text or "")
            except ValidationError as exc:  # salida mal formada: un retry de validación
                last_error = exc
            except Exception as exc:  # error de red / cuota: no reintentar en cascada
                raise LLMError(f"Gemini falló: {type(exc).__name__}") from exc
        raise LLMError(f"Salida inválida de Gemini tras reintento: {last_error}")
