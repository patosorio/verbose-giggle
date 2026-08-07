from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    test_database_url: str = ""
    serpapi_key: str = ""
    anthropic_api_key: str = ""
    jwt_signing_key: str = ""

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


settings = Settings()
