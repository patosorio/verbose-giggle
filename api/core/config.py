from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    test_database_url: str = ""
    serpapi_key: str = ""
    anthropic_api_key: str = ""
    jwt_signing_key: str = ""

    serpapi_base_url: str = "https://serpapi.com/search"
    serpapi_max_retries: int = 3
    # NoDecode: pydantic-settings otherwise tries to json.loads() this env var
    # before the field_validator below ever sees it (fields typed as
    # non-str are JSON-decoded by default) — a bare comma-separated string
    # isn't valid JSON, so it would fail before parse_backoff runs.
    serpapi_backoff_seconds: Annotated[tuple[float, ...], NoDecode] = (0.5, 1.0, 2.0)
    booking_source_ttl_seconds: int = 60 * 20

    # Activities research agent (docs/01_architecture.md §5). Model ID is config-only.
    anthropic_activities_model: str = "claude-sonnet-5"
    anthropic_web_search_max_uses: int = 5
    anthropic_activities_max_retries: int = 1
    anthropic_activities_max_tokens: int = 8192

    fx_api_base_url: str = "https://api.frankfurter.app"

    access_token_ttl_seconds: int = 60 * 60 * 24 * 7

    # No /auth prefix: client/app/(auth)/ is a Next.js route group, which is
    # excluded from the URL by convention — the real path is /verify.
    magic_link_base_url: str = "http://localhost:3000/verify"
    magic_link_ttl_seconds: int = 60 * 15

    email_sender: str = "console"

    # Phase 4 — local fire-and-forget vs Cloud Tasks (Phase 7).
    task_queue_backend: str = "local"

    # docs/01_architecture.md §6 — CORS is required regardless of auth transport
    # (bearer JWT here, not cookies), since the frontend (Vercel) and API (Cloud
    # Run) are different origins.
    # NoDecode: same reason as serpapi_backoff_seconds above — this is the
    # field where that latent bug actually surfaced (found live, 2026-08-08,
    # once CORS_ALLOWED_ORIGINS was first set in a real .env and hit
    # pydantic-settings' default JSON-decode path for non-str fields).
    cors_allowed_origins: Annotated[tuple[str, ...], NoDecode] = ("http://localhost:3000",)

    @field_validator("serpapi_backoff_seconds", mode="before")
    @classmethod
    def parse_backoff(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(float(part.strip()) for part in value.split(",") if part.strip())
        return value

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def parse_cors_allowed_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value


settings = Settings()
