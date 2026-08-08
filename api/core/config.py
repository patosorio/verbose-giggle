from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    test_database_url: str = ""
    serpapi_key: str = ""
    anthropic_api_key: str = ""
    jwt_signing_key: str = ""

    serpapi_base_url: str = "https://serpapi.com/search"
    serpapi_max_retries: int = 3
    serpapi_backoff_seconds: tuple[float, ...] = (0.5, 1.0, 2.0)
    booking_source_ttl_seconds: int = 60 * 20

    session_cookie_name: str = "session"
    session_cookie_max_age_seconds: int = 60 * 60 * 24 * 7
    session_cookie_httponly: bool = True
    session_cookie_samesite: str = "lax"
    session_cookie_secure: bool = False
    session_cookie_domain: str | None = None

    magic_link_base_url: str = "http://localhost:3000/auth/verify"
    magic_link_ttl_seconds: int = 60 * 15

    email_sender: str = "console"

    @field_validator("session_cookie_domain", mode="before")
    @classmethod
    def empty_domain_as_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @field_validator("serpapi_backoff_seconds", mode="before")
    @classmethod
    def parse_backoff(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(float(part.strip()) for part in value.split(",") if part.strip())
        return value


settings = Settings()
