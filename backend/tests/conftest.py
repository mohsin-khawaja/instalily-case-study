from __future__ import annotations

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models import errors as _errors  # noqa: F401  (registers run/error tables)
from app.models.domain import Company, Event
from app.models.enums import EventType

# Credentials that must never leak into a test run: a populated .env would make
# "unconfigured provider" tests pass for the wrong reason, and could spend real
# API credits from the suite.
_CREDENTIAL_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "APOLLO_API_KEY",
    "CLAY_API_KEY",
    "CLAY_WEBHOOK_URL",
    "SALES_NAV_TOKEN",
    "SERPER_API_KEY",
    "TAVILY_API_KEY",
)


@pytest.fixture(autouse=True)
def _hermetic_settings(monkeypatch):
    """Run every test against empty credentials, whatever the developer's .env says.

    Env vars outrank the .env file in pydantic-settings, so blanking them here is
    enough; the cache is cleared on both sides so no test inherits another's view.
    """
    from app.config import get_settings

    get_settings.cache_clear()
    for var in _CREDENTIAL_VARS:
        monkeypatch.setenv(var, "")
    monkeypatch.setenv("SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setenv("CONTACT_PROVIDERS", "public_web,mock")
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _no_real_backoff(monkeypatch):
    """Retry/throttle sleeps are behaviour under test, not wall-clock we should pay."""
    import asyncio

    async def _instant(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", _instant)


@pytest.fixture
def engine():
    # StaticPool keeps every connection pointed at the same in-memory database.
    # Without it, TestClient's worker thread opens a second, empty one.
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def isa_expo() -> Event:
    return Event(
        id="evt-isa",
        slug="isa-sign-expo-2026",
        name="ISA Sign Expo 2026",
        url="https://www.signexpo.org/",
        exhibitor_list_url="https://www.signexpo.org/exhibitor-list",
        event_type=EventType.TRADE_SHOW,
        tier1=True,
    )


@pytest.fixture
def printing_united() -> Event:
    return Event(
        id="evt-pu",
        slug="printing-united-expo-2026",
        name="PRINTING United Expo 2026",
        url="https://www.printingunited.com/",
        exhibitor_list_url="https://www.printingunited.com/exhibitors",
        event_type=EventType.TRADE_SHOW,
        tier1=True,
    )


@pytest.fixture
def avery(isa_expo, printing_united) -> Company:
    """A company that should unambiguously qualify as tier A."""
    return Company(
        id="cmp-avery",
        name="Avery Dennison Graphics Solutions",
        canonical_name="avery dennison graphics solutions",
        domain="averydennison.com",
        website="https://graphics.averydennison.com/",
        industry="Graphic films and signage materials",
        sub_industries=["vehicle wrap", "architectural graphics", "large format printing"],
        description=(
            "Global manufacturer of self-adhesive vinyl, graphic films and overlaminate "
            "for signage, vehicle wrap and architectural graphics."
        ),
        products=["cast vinyl", "overlaminate", "vehicle wrap film"],
        site_text=(
            "Our films are UV resistant and weather resistant with a 10 year warranty "
            "for outdoor signage and fleet graphic applications."
        ),
        revenue_est_usd=8_800_000_000,
        employee_count_est=35000,
        event_ids=[isa_expo.id, printing_united.id],
        enriched=True,
    )
