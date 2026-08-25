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
    try:
        chain = build_contact_chain(
            Fetcher(cache=cache), None, names=["apollo", "clay", "public_web"]
        )
        assert [p.name for p in chain] == ["apollo", "public_web"]
    finally:
        get_settings.cache_clear()
