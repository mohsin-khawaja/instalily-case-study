"""Runtime configuration. All knobs are env-overridable; every default is safe offline."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_ROOT / "data"
RAW_CACHE_DIR = DATA_DIR / "raw"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_ROOT.parent / ".env", BACKEND_ROOT / ".env"),
        extra="ignore",
    )

    # LLM
    anthropic_api_key: str | None = None
    anthropic_base_url: str | None = None
    llm_model_reasoning: str = "claude-sonnet-5"
    llm_model_extraction: str = "claude-haiku-4-5"

    # Search
    search_provider: str = "duckduckgo"
    tavily_api_key: str | None = None
    serper_api_key: str | None = None

    # Contacts
    contact_providers: str = "public_web,mock"
    apollo_api_key: str | None = None
    clay_api_key: str | None = None
    clay_webhook_url: str | None = None
    sales_nav_token: str | None = None

    # Pipeline / HTTP
    pipeline_mode: str = "cached"
    http_concurrency: int = 8
    http_timeout_s: float = 20.0
    http_per_host_delay_s: float = 1.0
    user_agent: str = (
        "TedlarLeadAgent/0.1 (+https://github.com/; case-study prototype; contact via repo)"
    )

    database_url: str = f"sqlite:///{DATA_DIR / 'leads.db'}"

    @property
    def contact_provider_chain(self) -> list[str]:
        return [p.strip() for p in self.contact_providers.split(",") if p.strip()]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
