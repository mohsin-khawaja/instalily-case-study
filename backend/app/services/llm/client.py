"""Anthropic wrapper with schema-validated output and one repair round-trip.

The pipeline only lets the LLM do fuzzy work (normalise messy entities, write
prose over facts we already hold). Everything it returns is parsed into a
Pydantic model before it is allowed near the database, and a model that cannot
produce a valid payload twice in a row degrades the record instead of the run.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ...config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

MAX_TOKENS = 4096

# USD per million tokens, input / output. Used only to put a number on a run --
# billing is Anthropic's. Update alongside any model change.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-opus-5": (5.00, 25.00),
}


@dataclass
class Usage:
    """Token and cost accounting for one run."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    by_model: dict[str, dict[str, int]] = field(default_factory=dict)

    def record(self, model: str, input_tokens: int, output_tokens: int) -> None:
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        bucket = self.by_model.setdefault(
            model, {"calls": 0, "input_tokens": 0, "output_tokens": 0}
        )
        bucket["calls"] += 1
        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens

    @property
    def estimated_usd(self) -> float:
        total = 0.0
        for model, bucket in self.by_model.items():
            price_in, price_out = MODEL_PRICING.get(model, (0.0, 0.0))
            total += bucket["input_tokens"] / 1_000_000 * price_in
            total += bucket["output_tokens"] / 1_000_000 * price_out
        return round(total, 4)

    def as_dict(self) -> dict:
        return {
            "llm_calls": self.calls,
            "llm_input_tokens": self.input_tokens,
            "llm_output_tokens": self.output_tokens,
            "llm_estimated_usd": self.estimated_usd,
        }


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
        self.usage = Usage()

    @property
    def calls(self) -> int:
        return self.usage.calls

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
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        usage = getattr(response, "usage", None)
        self.usage.record(
            model,
            getattr(usage, "input_tokens", 0) or 0,
            getattr(usage, "output_tokens", 0) or 0,
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

        model = model or self.model_extraction
        schema = _json_schema(schema_model)

        def _call(text_prompt: str) -> str:
            return self._complete_json(
                model=model, system=system, prompt=text_prompt, schema=schema
            )

        raw = await _guarded(_call, prompt)
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
            repaired = await _guarded(_call, repair_prompt)
            try:
                return _parse(schema_model, repaired)
            except (ValidationError, ValueError) as second_error:
                raise LLMOutputError(
                    f"{schema_model.__name__} invalid after repair: {second_error}"
                ) from second_error


async def _guarded(call, prompt: str) -> str:
    """Run one provider call, converting transport-level failures into LLMUnavailable.

    An exhausted credit balance, a revoked key or a rate limit arrives as an
    SDK exception the pipeline has never heard of. Left unwrapped it escapes
    `RunContext.attempt` and takes down a whole stage — which is exactly what
    happened when the account ran out of credit mid-run: enrichment degraded
    per-record as designed, while qualification failed outright. Provider
    problems are an availability condition, not a bug, so they degrade the
    record and let the deterministic path take over.
    """
    import asyncio

    try:
        return await asyncio.to_thread(call, prompt)
    except Exception as exc:  # noqa: BLE001 -- re-raised as a typed failure below
        if _is_provider_error(exc):
            raise LLMUnavailable(f"{type(exc).__name__}: {exc}"[:300]) from exc
        raise


def _is_provider_error(exc: BaseException) -> bool:
    """True for anything raised by the Anthropic SDK itself."""
    module = type(exc).__module__ or ""
    return module.startswith("anthropic") or module.startswith("httpx")


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
