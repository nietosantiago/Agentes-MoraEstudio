"""Proveedor Gemini: structured output + validación Pydantic + un retry de validación."""
from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ..tracing import report_usage
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

        last: Exception | None = None
        for _ in range(self.max_retries + 1):
            try:
                resp = self._client.models.generate_content(
                    model=self.model, contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system, temperature=self.temperature,
                        response_mime_type="application/json", response_schema=schema),
                )
            except Exception as exc:  # red, cuota, auth: no reintentar en cascada
                raise LLMError(f"Gemini falló: {type(exc).__name__}") from exc
            u = getattr(resp, "usage_metadata", None)
            report_usage(self.model, getattr(u, "prompt_token_count", 0) or 0,
                         getattr(u, "candidates_token_count", 0) or 0)
            try:
                return schema.model_validate_json(resp.text or "")
            except ValidationError as exc:
                last = exc
        raise LLMError(f"Salida inválida de Gemini tras reintento: {last}")
