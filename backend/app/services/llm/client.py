"""Anthropic wrapper with schema-validated output and one repair round-trip.

The pipeline only lets the LLM do fuzzy work (normalise messy entities, write
prose over facts we already hold). Everything it returns is parsed into a
Pydantic model before it is allowed near the database, and a model that cannot
produce a valid payload twice in a row degrades the record instead of the run.
"""

from __future__ import annotations

import json
import logging
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ...config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

MAX_TOKENS = 4096


class LLMUnavailable(RuntimeError):
    """No API key configured. Callers fall back to deterministic behaviour."""


class LLMOutputError(RuntimeError):
    """The model could not produce a payload matching the schema."""


class LLMClient:
    """Thin, synchronous-under-async wrapper. One instance per run."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        settings = get_settings()
        self._api_key = api_key or settings.anthropic_api_key
        self._base_url = base_url or settings.anthropic_base_url
        self.model_reasoning = settings.llm_model_reasoning
        self.model_extraction = settings.llm_model_extraction
        self._client = None
        self.calls = 0

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    def _anthropic(self):
        if self._client is None:
            if not self._api_key:
                raise LLMUnavailable("ANTHROPIC_API_KEY is not set")
            import anthropic  # imported lazily so offline runs never need the SDK wired

            kwargs: dict[str, object] = {"api_key": self._api_key, "max_retries": 3}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = anthropic.Anthropic(**kwargs)
        return self._client

    # -- transport -------------------------------------------------------

    def _complete_json(self, *, model: str, system: str, prompt: str, schema: dict) -> str:
        """One API call constrained to `schema`. Overridden in tests."""
        client = self._anthropic()
        self.calls += 1
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        return next((b.text for b in response.content if b.type == "text"), "")

    # -- public API ------------------------------------------------------

    async def structured(
        self,
        schema_model: type[T],
        *,
        prompt: str,
        system: str,
        model: str | None = None,
    ) -> T:
        """Return a validated `schema_model`, repairing once on invalid output."""
        import asyncio

        model = model or self.model_extraction
        schema = _json_schema(schema_model)

        def _call(text_prompt: str) -> str:
            return self._complete_json(
                model=model, system=system, prompt=text_prompt, schema=schema
            )

        raw = await asyncio.to_thread(_call, prompt)
        try:
            return _parse(schema_model, raw)
        except (ValidationError, ValueError) as first_error:
            logger.info("llm output invalid, attempting one repair: %s", first_error)
            repair_prompt = (
                f"{prompt}\n\n---\nYour previous reply did not satisfy the schema.\n"
                f"Previous reply:\n{raw[:2000]}\n\nValidation error:\n{first_error}\n\n"
                "Reply again with JSON that satisfies the schema exactly. "
                "Use null for anything you cannot support with the supplied text."
            )
            repaired = await asyncio.to_thread(_call, repair_prompt)
            try:
                return _parse(schema_model, repaired)
            except (ValidationError, ValueError) as second_error:
                raise LLMOutputError(
                    f"{schema_model.__name__} invalid after repair: {second_error}"
                ) from second_error


def _parse(schema_model: type[T], raw: str) -> T:
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty model response")
    if text.startswith("```"):  # defensive: strip a fenced block if one slips through
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    return schema_model.model_validate(json.loads(text))


def _json_schema(schema_model: type[BaseModel]) -> dict:
    """Pydantic JSON schema, flattened and closed for the structured-output API."""
    schema = schema_model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: object) -> object:
        if isinstance(node, dict):
            if "$ref" in node:
                ref = node["$ref"].rsplit("/", 1)[-1]
                return resolve(dict(defs.get(ref, {})))
            out = {k: resolve(v) for k, v in node.items()}
            if out.get("type") == "object":
                out["additionalProperties"] = False
                out.setdefault("required", list(out.get("properties", {}).keys()))
            return out
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)  # type: ignore[return-value]
