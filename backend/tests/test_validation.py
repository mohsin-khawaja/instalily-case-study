from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from app.models.domain import Evidence, ScoreBreakdown, SourceRef
from app.services.llm.client import LLMClient, LLMOutputError, LLMUnavailable, _json_schema


class Extracted(BaseModel):
    industry: str | None
    products: list[str]


class _StubLLM(LLMClient):
    """Feeds canned payloads so the repair path is exercised without a network."""

    def __init__(self, replies: list[str]) -> None:
        super().__init__(api_key="test-key")
        self.replies = replies
        self.prompts: list[str] = []

    def _complete_json(self, *, model, system, prompt, schema):
        self.prompts.append(prompt)
        self.usage.record(model, 100, 20)
        return self.replies[min(self.calls - 1, len(self.replies) - 1)]


def test_source_ref_rejects_non_http_urls():
    with pytest.raises(ValidationError):
        SourceRef(url="ftp://example.com/file")
    assert SourceRef(url="https://example.com").url == "https://example.com"


def test_evidence_requires_a_real_source_url():
    with pytest.raises(ValidationError):
        Evidence(claim="big company", source_url="hearsay")


def test_score_breakdown_total_is_the_sum():
    b = ScoreBreakdown(industry_fit=30, product_fit=25, size=15, event_engagement=15,
                       pain_alignment=15)
    assert b.total == 100.0
    assert b.as_dict()["total"] == 100.0


def test_json_schema_is_closed_for_structured_output():
    schema = _json_schema(Extracted)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"industry", "products"}


async def test_valid_output_parses_on_first_call():
    llm = _StubLLM(['{"industry": "Graphic films", "products": ["vinyl"]}'])
    result = await llm.structured(Extracted, prompt="p", system="s")
    assert result.industry == "Graphic films"
    assert llm.calls == 1


async def test_malformed_json_triggers_exactly_one_repair():
    llm = _StubLLM(["not json at all", '{"industry": null, "products": []}'])
    result = await llm.structured(Extracted, prompt="p", system="s")
    assert result.industry is None
    assert llm.calls == 2
    assert "Validation error" in llm.prompts[1]


async def test_schema_violation_after_repair_raises_recoverable_error():
    llm = _StubLLM(['{"products": "not-a-list"}', '{"products": "still-not-a-list"}'])
    with pytest.raises(LLMOutputError):
        await llm.structured(Extracted, prompt="p", system="s")
    assert llm.calls == 2


async def test_missing_api_key_raises_unavailable_not_a_crash():
    llm = LLMClient(api_key=None)
    assert llm.enabled is False
    with pytest.raises(LLMUnavailable):
        await llm.structured(Extracted, prompt="p", system="s")


def test_usage_tracks_tokens_and_prices_them_per_model():
    from app.services.llm.client import Usage

    usage = Usage()
    usage.record("claude-haiku-4-5", 1_000_000, 200_000)   # $1.00 + $1.00
    usage.record("claude-sonnet-5", 1_000_000, 100_000)    # $3.00 + $1.50
    assert usage.calls == 2
    assert usage.input_tokens == 2_000_000
    assert usage.estimated_usd == 6.5
    assert usage.by_model["claude-haiku-4-5"]["calls"] == 1


def test_usage_ignores_models_it_has_no_price_for():
    from app.services.llm.client import Usage

    usage = Usage()
    usage.record("some-future-model", 1_000_000, 1_000_000)
    assert usage.estimated_usd == 0.0
    assert usage.calls == 1


async def test_repair_round_trip_is_counted_as_two_calls():
    llm = _StubLLM(["not json", '{"industry": null, "products": []}'])
    await llm.structured(Extracted, prompt="p", system="s")
    assert llm.usage.calls == 2
    assert llm.usage.input_tokens == 200
