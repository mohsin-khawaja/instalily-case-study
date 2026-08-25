"""Preflight: verify every configured integration before spending a run on it.

    uv run python -m app.preflight

A live run takes minutes and costs credits, so failing fast on a bad key is worth
a dedicated command. Each check makes the smallest real call the provider offers,
reports what it found, and never prints a secret. Exit code is non-zero if
anything a run depends on is broken -- so this also works as a CI smoke test.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from .config import get_settings

Status = Literal["ok", "skip", "warn", "fail"]

ICONS = {"ok": "PASS", "skip": "SKIP", "warn": "WARN", "fail": "FAIL"}


@dataclass(slots=True)
class CheckResult:
    name: str
    status: Status
    detail: str

    @property
    def blocking(self) -> bool:
        return self.status == "fail"


class _Ping(BaseModel):
    industry: str | None
    products: list[str]


def _mask(value: str | None) -> str:
    if not value:
        return "unset"
    return f"set ({len(value)} chars, ends …{value[-4:]})"


async def check_anthropic() -> list[CheckResult]:
    from .services.llm import LLMClient

    settings = get_settings()
    llm = LLMClient()
    if not llm.enabled:
        return [
            CheckResult(
                "anthropic", "skip",
                "ANTHROPIC_API_KEY unset — rationales and outreach fall back to templates",
            )
        ]

    out: list[CheckResult] = []
    for label, model in (
        ("extraction", settings.llm_model_extraction),
        ("reasoning", settings.llm_model_reasoning),
    ):
        try:
            result = await llm.structured(
                _Ping,
                prompt=(
                    "Page text: 'Acme makes cast vinyl wrap film for outdoor signage.'\n"
                    "Extract the fields."
                ),
                system="Extract only what the text states. Return null rather than guess.",
                model=model,
            )
            out.append(
                CheckResult(
                    f"anthropic:{label}", "ok",
                    f"{model} responded, parsed {len(result.products)} product(s)",
                )
            )
        except Exception as exc:  # noqa: BLE001 -- a preflight reports, it does not raise
            out.append(
                CheckResult(
                    f"anthropic:{label}", "fail",
                    f"{model}: {type(exc).__name__}: {exc}"[:200],
                )
            )
    return out


async def check_search() -> list[CheckResult]:
    from .services.http import Fetcher
    from .services.search import build_search_provider

    settings = get_settings()
    async with Fetcher(live=True) as fetcher:
        provider = build_search_provider(fetcher)
        configured = settings.search_provider.lower()
        if provider.name != configured:
            note = (
                f"SEARCH_PROVIDER={configured} but its key is unset; "
                f"fell back to {provider.name}"
            )
            status: Status = "warn"
        else:
            note = f"using {provider.name}"
            status = "ok"
        try:
            results = await provider.search("graphic films manufacturer signage", limit=5)
        except Exception as exc:  # noqa: BLE001
            return [
                CheckResult(
                    f"search:{provider.name}", "fail",
                    f"{type(exc).__name__}: {exc}"[:200],
                )
            ]

    if not results:
        return [
            CheckResult(
                f"search:{provider.name}", "fail",
                f"{note} — returned 0 results; discovery and size lookup will be empty",
            )
        ]
    return [CheckResult(f"search:{provider.name}", status, f"{note}, {len(results)} results")]


async def check_apollo() -> list[CheckResult]:
    from .integrations.contacts.apollo import ApolloProvider, enrich_organization
    from .models.domain import Company
    from .scoring import icp

    settings = get_settings()
    if not settings.apollo_api_key:
        return [CheckResult("apollo", "skip", "APOLLO_API_KEY unset")]

    out: list[CheckResult] = []
    org = await enrich_organization("drytac.com")
    if org and (org.revenue_usd or org.employee_count):
        out.append(
            CheckResult(
                "apollo:organizations", "ok",
                f"firmographics available (sample: revenue={org.revenue_usd}, "
                f"employees={org.employee_count})",
            )
        )
    else:
        out.append(
            CheckResult("apollo:organizations", "fail", "organization enrich returned nothing")
        )

    probe = Company(
        name="Drytac", canonical_name="drytac", domain="drytac.com",
        website="https://www.drytac.com/",
    )
    contacts = await ApolloProvider().find_contacts(probe, icp.TARGET_TITLES, limit=1)
    if contacts:
        out.append(CheckResult("apollo:people", "ok", f"people search returned {len(contacts)}"))
    else:
        out.append(
            CheckResult(
                "apollo:people", "warn",
                "people search unavailable (Apollo gates it behind paid plans); "
                "contacts fall through to the next provider",
            )
        )
    return out


def check_contact_chain() -> list[CheckResult]:
    settings = get_settings()
    chain = settings.contact_provider_chain
    unknown = [n for n in chain if n not in
               {"apollo", "public_web", "clay", "sales_navigator", "mock"}]
    if unknown:
        return [CheckResult("contacts:chain", "fail", f"unknown provider(s): {', '.join(unknown)}")]
    if chain and chain[0] == "mock":
        return [
            CheckResult(
                "contacts:chain", "warn",
                "mock is first — every contact will be placeholder data",
            )
        ]
    return [CheckResult("contacts:chain", "ok", " → ".join(chain))]


def check_cache() -> list[CheckResult]:
    from .services.cache import ResponseCache

    cache = ResponseCache()
    count = len(cache.urls())
    if count == 0:
        return [
            CheckResult(
                "cache", "warn",
                "empty — a --mode cached run will have nothing to replay; run --live first",
            )
        ]
    return [CheckResult("cache", "ok", f"{count} cached responses in {cache.root}")]


async def run_checks() -> list[CheckResult]:
    results: list[CheckResult] = []
    results += check_contact_chain()
    results += check_cache()
    results += await check_anthropic()
    results += await check_search()
    results += await check_apollo()
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify configured integrations.")
    parser.add_argument(
        "--strict", action="store_true",
        help="treat warnings as failures (useful in CI)",
    )
    args = parser.parse_args()

    settings = get_settings()
    print("configuration")
    print(f"  ANTHROPIC_API_KEY   {_mask(settings.anthropic_api_key)}")
    print(f"  SERPER_API_KEY      {_mask(settings.serper_api_key)}")
    print(f"  TAVILY_API_KEY      {_mask(settings.tavily_api_key)}")
    print(f"  APOLLO_API_KEY      {_mask(settings.apollo_api_key)}")
    print(f"  SEARCH_PROVIDER     {settings.search_provider}")
    print(f"  CONTACT_PROVIDERS   {', '.join(settings.contact_provider_chain)}")
    print(f"  models              {settings.llm_model_reasoning} / {settings.llm_model_extraction}")
    print()

    results = asyncio.run(run_checks())
    width = max(len(r.name) for r in results)
    print("checks")
    for result in results:
        print(f"  {ICONS[result.status]}  {result.name:<{width}}  {result.detail}")

    failed = [r for r in results if r.blocking]
    warned = [r for r in results if r.status == "warn"]
    print()
    print(f"{len(results)} checks — {len(failed)} failed, {len(warned)} warnings")
    if failed:
        return 1
    return 1 if (args.strict and warned) else 0


if __name__ == "__main__":
    sys.exit(main())
