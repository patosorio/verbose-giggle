from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine

from core.config import settings
from db.base import Base
from db.session import get_session
from main import app
from services.email import EmailSender, get_email_sender

_PG_ENUM_TYPE_NAMES = (
    "budget_band",
    "trip_status",
    "trip_member_role",
    "age_category",
    "leg_status",
)


async def _reset_schema(conn: AsyncConnection) -> None:
    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
    await conn.run_sync(Base.metadata.drop_all)
    for enum_name in _PG_ENUM_TYPE_NAMES:
        await conn.execute(text(f"DROP TYPE IF EXISTS {enum_name} CASCADE"))
    await conn.run_sync(Base.metadata.create_all)


class CapturingEmailSender:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def send_magic_link(self, to_email: str, magic_link_url: str) -> None:
        self.urls.append(magic_link_url)

    @property
    def last_token(self) -> str:
        if not self.urls:
            raise AssertionError("No magic-link email was sent")
        query = parse_qs(urlparse(self.urls[-1]).query)
        token_values = query.get("token")
        if not token_values:
            raise AssertionError("Magic-link URL did not contain a token")
        return token_values[0]


@pytest.fixture(scope="session")
async def test_engine() -> AsyncIterator[AsyncEngine]:
    if not settings.test_database_url:
        pytest.fail(
            "TEST_DATABASE_URL is not configured. "
            "Create the travelagency_test database and set TEST_DATABASE_URL in api/.env "
            "(see api/.env.example)."
        )

    engine = create_async_engine(settings.test_database_url, echo=False)
    async with engine.begin() as conn:
        await _reset_schema(conn)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        for enum_name in _PG_ENUM_TYPE_NAMES:
            await conn.execute(text(f"DROP TYPE IF EXISTS {enum_name} CASCADE"))
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with test_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
async def email_sender() -> CapturingEmailSender:
    return CapturingEmailSender()


@pytest.fixture
async def client(
    db_session: AsyncSession,
    email_sender: CapturingEmailSender,
) -> AsyncIterator[AsyncClient]:
    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    def override_get_email_sender() -> EmailSender:
        return email_sender

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_email_sender] = override_get_email_sender

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client

    app.dependency_overrides.clear()
