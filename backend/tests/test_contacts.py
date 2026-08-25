from __future__ import annotations

import httpx
import pytest

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
