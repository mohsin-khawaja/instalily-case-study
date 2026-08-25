from __future__ import annotations

import pytest

from app.models.domain import Contact, Qualification
from app.models.enums import Tier
from app.pipeline.stages.draft_outreach import (
    MAX_BODY_WORDS,
    OutreachOut,
    OutreachRejected,
    _template_draft,
    _value_props_for,
    validate,
)
from app.scoring import icp

ALLOWED = {"https://graphics.averydennison.com/", "https://www.signexpo.org/"}


def _draft(**overrides) -> OutreachOut:
    base = {
        "subject": "Tedlar overlaminate for your wrap films",
        "body": (
            "Hi Dana, your cast wrap line is warranted for seven years outdoors, "
            "which is exactly where PVF overlaminates earn their keep. Tedlar holds "
            "gloss and colour through sustained UV exposure, so the warranty math "
            "gets easier. Worth a short call, or I can send the weathering data."
        ),
        "hook_fact": "Cast wrap film carries a seven-year outdoor warranty",
        "hook_source_url": "https://graphics.averydennison.com/",
        "tedlar_value_prop": "uv resistance",
    }
    return OutreachOut(**{**base, **overrides})


def test_a_grounded_draft_passes():
    validate(_draft(), ALLOWED)


def test_hook_citing_a_url_outside_the_evidence_set_is_rejected():
    with pytest.raises(OutreachRejected, match="not in the supplied evidence"):
        validate(_draft(hook_source_url="https://example.com/made-up"), ALLOWED)


def test_overlong_body_is_rejected():
    with pytest.raises(OutreachRejected, match="max"):
        validate(_draft(body=" ".join(["word"] * (MAX_BODY_WORDS + 1))), ALLOWED)


def test_empty_body_is_rejected():
    with pytest.raises(OutreachRejected, match="empty body"):
        validate(_draft(body="   "), ALLOWED)


def test_overlong_subject_is_rejected():
    with pytest.raises(OutreachRejected, match="subject"):
        validate(_draft(subject=" ".join(["word"] * 11)), ALLOWED)


@pytest.mark.parametrize(
    "phrase",
    ["I hope this finds you well.", "Quick question for you.", "Let's touch base soon."],
)
def test_spam_filler_is_rejected(phrase):
    with pytest.raises(OutreachRejected, match="banned filler"):
        validate(_draft(body=f"Hi Dana. {phrase} Tedlar resists UV."), ALLOWED)


def test_value_props_prefer_themes_the_company_already_markets_on():
    qualification = Qualification(
        company_id="c1",
        tier=Tier.A,
        evidence=[
            {
                "claim": "Markets on durability themes Tedlar addresses: uv resistance",
                "source_url": "https://graphics.averydennison.com/",
            }
        ],
    )
    props = _value_props_for(qualification)
    assert set(props) == {"uv resistance"}


def test_value_props_fall_back_to_the_full_list_when_nothing_matches():
    qualification = Qualification(company_id="c1", tier=Tier.A, evidence=[])
    assert _value_props_for(qualification) == icp.TEDLAR_VALUE_PROPS


def test_template_fallback_only_cites_supplied_evidence(avery):
    contact = Contact(company_id=avery.id, full_name="Dana Whitfield", title="VP Product")
    evidence = [
        {
            "claim": "Serves Tedlar application areas: vehicle wrap",
            "source_url": "https://graphics.averydennison.com/",
        }
    ]
    subject, body, hook, hook_url, prop = _template_draft(
        contact, avery, evidence, icp.TEDLAR_VALUE_PROPS
    )
    assert hook_url in {e["source_url"] for e in evidence}
    assert "Dana" in body
    assert prop in icp.TEDLAR_VALUE_PROPS
    assert len(body.split()) <= MAX_BODY_WORDS
    assert subject
    # The fallback must clear the same style bar the LLM draft has to clear.
    validate(
        OutreachOut(
            subject=subject, body=body, hook_fact=hook,
            hook_source_url=hook_url, tedlar_value_prop=prop,
        ),
        {e["source_url"] for e in evidence},
    )
