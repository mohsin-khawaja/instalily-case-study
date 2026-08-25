from __future__ import annotations

import json

import httpx
import pytest

from app.config import get_settings
from app.integrations.contacts import build_contact_chain
from app.integrations.contacts.base import (
    classify_seniority,
    sales_navigator_url,
    title_relevance,
)
from app.integrations.contacts.clay import ClayProvider
from app.integrations.contacts.mock import MockContactProvider
from app.integrations.contacts.public_web import PublicWebContactProvider
from app.integrations.contacts.sales_navigator import SalesNavigatorProvider
from app.models.enums import Seniority
from app.scoring import icp
from app.services.cache import ResponseCache
from app.services.http import Fetcher


@pytest.fixture
def cache(tmp_path):
    return ResponseCache(root=tmp_path / "raw")


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Chief Technology Officer", Seniority.C_LEVEL),
        ("Vice President of Product Development", Seniority.VP),
        ("VP, Innovation", Seniority.VP),
        ("Director of R&D", Seniority.DIRECTOR),
        ("Head of Materials Science", Seniority.DIRECTOR),
        ("Product Manager, Films", Seniority.MANAGER),
        ("Warehouse Associate", Seniority.OTHER),
        (None, Seniority.OTHER),
    ],
)
def test_classify_seniority(title, expected):
    assert classify_seniority(title) is expected


def test_title_relevance_ranks_target_titles_above_noise():
    targets = ["Director of R&D", "VP Product"]
    assert title_relevance("Director of R&D", targets) == 1.0
    assert title_relevance("Facilities Coordinator", targets) == 0.0
    assert title_relevance("VP Product Development", targets) > 0.5


def test_sales_navigator_url_is_a_real_search_link():
    url = sales_navigator_url("Laura Noll", "Avery Dennison")
    assert url.startswith("https://www.linkedin.com/sales/search/people?query=")
    assert "Laura" in url and "Avery" in url


def test_unconfigured_providers_report_it_and_return_nothing():
    assert ClayProvider(api_key=None, webhook_url=None).is_configured() is False
    assert SalesNavigatorProvider(token=None).is_configured() is False
    assert MockContactProvider().is_configured() is True


async def test_unconfigured_provider_returns_empty_rather_than_raising(avery):
    contacts = await ClayProvider(api_key=None, webhook_url=None).find_contacts(avery, ["VP"])
    assert contacts == []
    contacts = await SalesNavigatorProvider(token=None).find_contacts(avery, ["VP"])
    assert contacts == []


def test_chain_skips_unconfigured_providers(cache):
    chain = build_contact_chain(
        Fetcher(cache=cache), None, names=["clay", "sales_navigator", "public_web", "mock"]
    )
    assert [p.name for p in chain] == ["public_web", "mock"]


def test_chain_ignores_unknown_provider_names(cache):
    chain = build_contact_chain(Fetcher(cache=cache), None, names=["nope", "mock"])
    assert [p.name for p in chain] == ["mock"]


async def test_mock_provider_is_deterministic_and_marked_as_placeholder(avery):
    provider = MockContactProvider()
    first = await provider.find_contacts(avery, icp.TARGET_TITLES)
    second = await provider.find_contacts(avery, icp.TARGET_TITLES)
    assert first[0].full_name == second[0].full_name
    assert first[0].provider == "mock"
    assert first[0].confidence == 0.0  # never mistakable for sourced data


async def test_public_web_reads_names_and_titles_off_a_leadership_page(cache, avery):
    page = """
    <html><body>
      <h2>Leadership</h2>
      <p>Dana Whitfield, Vice President of Product Development</p>
      <p>Sam Ortega - Director of Research and Development</p>
      <p>Chris Lane, Warehouse Associate</p>
    </body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/about/leadership":
            return httpx.Response(200, text=page)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    async with Fetcher(live=True, cache=cache, client=client) as fetcher:
        provider = PublicWebContactProvider(fetcher)
        contacts = await provider.find_contacts(avery, icp.TARGET_TITLES, limit=3)

    names = {c.full_name for c in contacts}
    assert "Dana Whitfield" in names
    assert "Chris Lane" not in names  # not a target title
    assert all(c.sales_nav_url for c in contacts)
    assert all(c.sources for c in contacts)


async def test_public_web_returns_nothing_rather_than_guessing(cache, avery):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body><p>We make films.</p></body></html>")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    async with Fetcher(live=True, cache=cache, client=client) as fetcher:
        contacts = await PublicWebContactProvider(fetcher).find_contacts(
            avery, icp.TARGET_TITLES
        )
    assert contacts == []


# --- Apollo ---------------------------------------------------------------


def _apollo_person(**overrides) -> dict:
    base = {
        "name": "Dana Whitfield",
        "title": "Vice President, Product Development",
        "linkedin_url": "https://www.linkedin.com/in/dana-whitfield",
        "email": "dana@acme.test",
    }
    return {**base, **overrides}


# Captured before any monkeypatching: the fakes below replace
# httpx.AsyncClient globally, so building one through the patched name would
# recurse into itself.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _apollo_client(handler) -> httpx.AsyncClient:
    return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler))


async def test_apollo_is_skipped_without_a_key(avery):
    from app.integrations.contacts.apollo import ApolloProvider

    provider = ApolloProvider(api_key=None)
    assert provider.is_configured() is False
    assert await provider.find_contacts(avery, icp.TARGET_TITLES) == []


async def test_apollo_refuses_to_match_a_company_with_no_domain(monkeypatch, avery):
    from app.integrations.contacts import apollo

    avery.domain = None
    called = {"n": 0}

    def handler(request):
        called["n"] += 1
        return httpx.Response(200, json={"people": []})

    monkeypatch.setattr(
        apollo.httpx, "AsyncClient", lambda **kw: _apollo_client(handler)
    )
    provider = apollo.ApolloProvider(api_key="k")
    assert await provider.find_contacts(avery, icp.TARGET_TITLES) == []
    assert called["n"] == 0  # never spends a credit on an ambiguous match


async def test_apollo_maps_a_person_into_a_contact(monkeypatch, avery):
    from app.integrations.contacts import apollo

    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        captured["key"] = request.headers.get("x-api-key")
        return httpx.Response(200, json={"people": [_apollo_person()]})

    monkeypatch.setattr(
        apollo.httpx, "AsyncClient", lambda **kw: _apollo_client(handler)
    )
    contacts = await apollo.ApolloProvider(api_key="secret").find_contacts(
        avery, icp.TARGET_TITLES, limit=2
    )

    assert captured["key"] == "secret"
    assert captured["body"]["q_organization_domains_list"] == ["averydennison.com"]
    contact = contacts[0]
    assert contact.full_name == "Dana Whitfield"
    assert contact.seniority is Seniority.VP
    assert contact.linkedin_url.endswith("dana-whitfield")
    assert contact.provider == "apollo"
    assert contact.sources


async def test_apollo_drops_locked_email_placeholders(monkeypatch, avery):
    from app.integrations.contacts import apollo

    def handler(request):
        return httpx.Response(
            200,
            json={"people": [_apollo_person(email="email_not_unlocked@domain.com")]},
        )

    monkeypatch.setattr(
        apollo.httpx, "AsyncClient", lambda **kw: _apollo_client(handler)
    )
    contacts = await apollo.ApolloProvider(api_key="k").find_contacts(avery, icp.TARGET_TITLES)
    assert contacts[0].email is None


async def test_apollo_ranks_the_best_title_first(monkeypatch, avery):
    from app.integrations.contacts import apollo

    def handler(request):
        return httpx.Response(
            200,
            json={
                "people": [
                    _apollo_person(name="Sam Rep", title="Regional Sales Representative"),
                    _apollo_person(name="Dana Whitfield", title="Director of R&D"),
                ]
            },
        )

    monkeypatch.setattr(
        apollo.httpx, "AsyncClient", lambda **kw: _apollo_client(handler)
    )
    contacts = await apollo.ApolloProvider(api_key="k").find_contacts(avery, ["Director of R&D"])
    assert contacts[0].full_name == "Dana Whitfield"


async def test_apollo_surfaces_a_rate_limit_as_no_results_not_a_crash(monkeypatch, avery):
    from app.integrations.contacts import apollo

    def handler(request):
        return httpx.Response(429, json={"error": "out of credits"})

    monkeypatch.setattr(
        apollo.httpx, "AsyncClient", lambda **kw: _apollo_client(handler)
    )
    assert await apollo.ApolloProvider(api_key="k").find_contacts(avery, icp.TARGET_TITLES) == []


def test_apollo_joins_the_chain_when_configured(cache, monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "k")
    get_settings.cache_clear()
    chain = build_contact_chain(
        Fetcher(cache=cache), None, names=["apollo", "clay", "public_web"]
    )
    assert [p.name for p in chain] == ["apollo", "public_web"]


async def test_apollo_free_plan_403_is_explained_not_retried(monkeypatch, avery, caplog):
    """A 403 here means the plan, not the key. The log has to say so."""
    from app.integrations.contacts import apollo

    def handler(request):
        return httpx.Response(
            403,
            json={"error": "not included in your Free plan", "error_code": "API_INACCESSIBLE"},
        )

    monkeypatch.setattr(apollo.httpx, "AsyncClient", lambda **kw: _apollo_client(handler))
    with caplog.at_level("WARNING"):
        assert await apollo.ApolloProvider(api_key="k").find_contacts(
            avery, icp.TARGET_TITLES
        ) == []
    assert "not available on this plan" in caplog.text


async def test_apollo_org_enrich_maps_firmographics(monkeypatch):
    from app.integrations.contacts import apollo

    def handler(request):
        assert request.url.params["domain"] == "drytac.com"
        return httpx.Response(200, json={"organization": {
            "id": "abc123", "name": "Drytac", "annual_revenue": 40000000.0,
            "estimated_num_employees": 64, "industry": "chemicals",
            "keywords": ["pressure sensitive adhesives", "laminates", 7],
            "short_description": "Adhesive-coated products.",
            "city": "Brampton", "country": "Canada",
            "linkedin_url": "http://www.linkedin.com/company/drytac",
        }})

    monkeypatch.setattr(apollo.httpx, "AsyncClient", lambda **kw: _apollo_client(handler))
    org = await apollo.enrich_organization("drytac.com", api_key="k")
    assert org.revenue_usd == 40000000.0
    assert org.employee_count == 64
    assert org.hq_location == "Brampton, Canada"
    assert org.keywords == ["pressure sensitive adhesives", "laminates"]  # non-strings dropped
    assert org.source_url == "https://app.apollo.io/#/organizations/abc123"


async def test_apollo_org_enrich_rejects_zero_and_missing_values(monkeypatch):
    from app.integrations.contacts import apollo

    def handler(request):
        return httpx.Response(200, json={"organization": {
            "id": "x", "annual_revenue": 0, "estimated_num_employees": None,
        }})

    monkeypatch.setattr(apollo.httpx, "AsyncClient", lambda **kw: _apollo_client(handler))
    org = await apollo.enrich_organization("x.com", api_key="k")
    assert org.revenue_usd is None and org.employee_count is None


async def test_apollo_org_enrich_returns_none_without_a_key():
    from app.integrations.contacts.apollo import enrich_organization

    assert await enrich_organization("drytac.com", api_key=None) is None


# --- LinkedIn search contact discovery ------------------------------------


@pytest.mark.parametrize(
    ("full", "expected"),
    [
        ("Avery Dennison Graphics Solutions", "Avery Dennison"),
        ("ORAFOL Europe", "ORAFOL"),
        ("General Formulations", "General Formulations"),
        ("Drytac", "Drytac"),
    ],
)
def test_short_name_keeps_the_brand(full, expected):
    from app.integrations.contacts.public_web import _short_name

    assert _short_name(full) == expected


def test_stale_roles_are_rejected():
    from app.integrations.contacts.public_web import _is_stale_role

    assert _is_stale_role("Retired VP of Operations") is True
    assert _is_stale_role("Former Director of R&D") is True
    assert _is_stale_role("Director of Product Development") is False


class _FakeSearch:
    name = "fake"

    def __init__(self, results):
        self._results = results

    def is_configured(self) -> bool:
        return True

    async def search(self, query, *, limit=10):
        return self._results


async def test_linkedin_search_keeps_decision_makers_and_drops_noise(cache, avery):
    from app.integrations.contacts.public_web import PublicWebContactProvider
    from app.services.search.base import SearchResult

    results = [
        SearchResult(url="https://www.linkedin.com/in/bruce-lessard-1",
                     title="Bruce Lessard - Director of Global Product Management",
                     snippet="Avery Dennison"),
        SearchResult(url="https://www.linkedin.com/in/retiree-2",
                     title="Pat Vanderweide - Retired VP of Operations",
                     snippet="Avery Dennison"),
        SearchResult(url="https://www.linkedin.com/jobs/view/director-somewhere",
                     title="Director, Product Development", snippet="Avery Dennison"),
        SearchResult(url="https://www.linkedin.com/in/other-co-3",
                     title="Sam Rivera - Director of Sales", snippet="A different company"),
    ]

    def handler(request):
        return httpx.Response(404)

    client = _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler), follow_redirects=True)
    async with Fetcher(live=True, cache=cache, client=client) as fetcher:
        provider = PublicWebContactProvider(fetcher, _FakeSearch(results))
        contacts = await provider.find_contacts(avery, icp.TARGET_TITLES, limit=3)

    names = [c.full_name for c in contacts]
    assert "Bruce Lessard" in names          # real decision-maker
    assert "Pat Vanderweide" not in names    # retired
    assert not any("jobs" in (c.linkedin_url or "") for c in contacts)  # job posting
    assert "Sam Rivera" not in names         # different company


# --- Apollo rate limiting -------------------------------------------------


async def test_apollo_org_enrich_signals_rate_limiting_distinctly(monkeypatch):
    from app.integrations.contacts import apollo

    def handler(request):
        return httpx.Response(429, json={"error": "rate limit"})

    monkeypatch.setattr(apollo.httpx, "AsyncClient", lambda **kw: _apollo_client(handler))
    with pytest.raises(apollo.ApolloRateLimited):
        await apollo.enrich_organization("drytac.com", api_key="k")


async def test_apollo_org_enrich_swallows_other_http_errors(monkeypatch):
    from app.integrations.contacts import apollo

    def handler(request):
        return httpx.Response(404, json={})

    monkeypatch.setattr(apollo.httpx, "AsyncClient", lambda **kw: _apollo_client(handler))
    assert await apollo.enrich_organization("nope.test", api_key="k") is None


def test_breaker_opens_once_and_resets_on_success():
    from app.integrations.contacts.apollo import RateLimitBreaker

    breaker = RateLimitBreaker(threshold=3)
    assert breaker.record_rate_limit() is False
    assert breaker.record_rate_limit() is False
    assert breaker.record_rate_limit() is True   # opens, and says so exactly once
    assert breaker.record_rate_limit() is False  # already open: no repeat report
    assert breaker.is_open() is True

    fresh = RateLimitBreaker(threshold=2)
    fresh.record_rate_limit()
    fresh.record_success()
    assert fresh.consecutive == 0
    assert fresh.is_open() is False


async def test_apollo_people_search_retires_after_a_plan_403(monkeypatch, avery):
    """A plan restriction is permanent for the run; asking again per company is waste."""
    from app.integrations.contacts import apollo

    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(403, json={"error_code": "API_INACCESSIBLE"})

    monkeypatch.setattr(apollo.httpx, "AsyncClient", lambda **kw: _apollo_client(handler))
    provider = apollo.ApolloProvider(api_key="k")

    for _ in range(5):
        assert await provider.find_contacts(avery, icp.TARGET_TITLES) == []

    assert calls["n"] == 1
    assert provider.is_configured() is False  # drops out of the chain afterwards


async def test_apollo_people_search_retires_on_quota_exhaustion(monkeypatch, avery):
    from app.integrations.contacts import apollo

    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(429, json={"error": "rate limit"})

    monkeypatch.setattr(apollo.httpx, "AsyncClient", lambda **kw: _apollo_client(handler))
    provider = apollo.ApolloProvider(api_key="k")
    for _ in range(3):
        await provider.find_contacts(avery, icp.TARGET_TITLES)
    assert calls["n"] == 1
