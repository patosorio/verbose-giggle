import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from core import security
from core.config import settings
from core.errors import AppError
from db.models import BudgetBand, Trip, TripMember, TripMemberRole, TripStatus, User


def _bearer_credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _user(*, user_id: uuid.UUID | None = None, email: str = "Pat@Example.com") -> User:
    return User(
        id=user_id or uuid.uuid4(),
        email=email,
        display_name=email.partition("@")[0],
        created_at=datetime.now(UTC),
    )


def _trip(*, organizer_id: uuid.UUID, trip_id: uuid.UUID | None = None) -> Trip:
    return Trip(
        id=trip_id or uuid.uuid4(),
        name="Thailand 2026",
        organizer_id=organizer_id,
        home_currency="USD",
        budget_band=BudgetBand.comfort,
        budget_target_amount=Decimal("5000.00"),
        status=TripStatus.planning,
        created_at=datetime.now(UTC),
    )


def _session_returning(value: object) -> AsyncMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _session_with_side_effects(*values: object) -> AsyncMock:
    results: list[MagicMock] = []
    for value in values:
        result = MagicMock()
        result.scalar_one_or_none.return_value = value
        results.append(result)
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=results)
    return session


def _member(*, trip_id: uuid.UUID, user: User) -> TripMember:
    return TripMember(
        id=uuid.uuid4(),
        trip_id=trip_id,
        user_id=user.id,
        invited_email=user.email,
        role=TripMemberRole.member,
        joined_at=datetime.now(UTC),
    )


@pytest.fixture
def signing_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = "test-signing-key"
    monkeypatch.setattr(settings, "jwt_signing_key", key)
    monkeypatch.setattr(security.settings, "jwt_signing_key", key)
    return key


@pytest.mark.asyncio
async def test_require_user_missing_authorization() -> None:
    session = AsyncMock()

    with pytest.raises(AppError) as exc_info:
        await security.require_user(None, session)

    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "unauthorized"
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_require_user_invalid_token(signing_key: str) -> None:
    credentials = _bearer_credentials("not-a-jwt")
    session = AsyncMock()

    with pytest.raises(AppError) as exc_info:
        await security.require_user(credentials, session)

    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "unauthorized"
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_require_user_unknown_user(signing_key: str) -> None:
    user_id = uuid.uuid4()
    token = security.create_session_token(user_id)
    credentials = _bearer_credentials(token)
    session = _session_returning(None)

    with pytest.raises(AppError) as exc_info:
        await security.require_user(credentials, session)

    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "unauthorized"


@pytest.mark.asyncio
async def test_require_user_success(signing_key: str) -> None:
    user = _user()
    token = security.create_session_token(user.id)
    credentials = _bearer_credentials(token)
    session = _session_returning(user)

    resolved = await security.require_user(credentials, session)

    assert resolved.id == user.id
    assert resolved.email == user.email


@pytest.mark.asyncio
async def test_require_organizer_trip_not_found(signing_key: str) -> None:
    user = _user()
    trip_id = uuid.uuid4()
    session = _session_returning(None)

    with pytest.raises(AppError) as exc_info:
        await security.require_organizer(trip_id, user, session)

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "not_found"


@pytest.mark.asyncio
async def test_require_organizer_forbidden(signing_key: str) -> None:
    user = _user()
    other_organizer_id = uuid.uuid4()
    trip = _trip(organizer_id=other_organizer_id)
    session = _session_returning(trip)

    with pytest.raises(AppError) as exc_info:
        await security.require_organizer(trip.id, user, session)

    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "forbidden"


@pytest.mark.asyncio
async def test_require_organizer_success(signing_key: str) -> None:
    user = _user()
    trip = _trip(organizer_id=user.id)
    session = _session_returning(trip)

    resolved = await security.require_organizer(trip.id, user, session)

    assert resolved.id == user.id


@pytest.mark.asyncio
async def test_require_member_trip_not_found(signing_key: str) -> None:
    user = _user()
    trip_id = uuid.uuid4()
    session = _session_returning(None)

    with pytest.raises(AppError) as exc_info:
        await security.require_member(trip_id, user, session)

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "not_found"


@pytest.mark.asyncio
async def test_require_member_forbidden(signing_key: str) -> None:
    user = _user()
    trip = _trip(organizer_id=uuid.uuid4())
    session = _session_with_side_effects(trip, None)

    with pytest.raises(AppError) as exc_info:
        await security.require_member(trip.id, user, session)

    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "forbidden"


@pytest.mark.asyncio
async def test_require_member_success(signing_key: str) -> None:
    user = _user()
    trip = _trip(organizer_id=uuid.uuid4())
    member = _member(trip_id=trip.id, user=user)
    session = _session_with_side_effects(trip, member)

    resolved = await security.require_member(trip.id, user, session)

    assert resolved.id == user.id
