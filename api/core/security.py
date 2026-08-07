from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.errors import AppError
from db.models import Trip, TripMember, User
from db.session import get_session

_JWT_ALGORITHM = "HS256"


async def _get_trip_or_404(session: AsyncSession, trip_id: UUID) -> Trip:
    result = await session.execute(select(Trip).where(Trip.id == trip_id))
    trip = result.scalar_one_or_none()
    if trip is None:
        raise AppError(404, "not_found", "Trip not found")
    return trip


async def _ensure_member(session: AsyncSession, trip_id: UUID, user: User) -> None:
    result = await session.execute(
        select(TripMember).where(
            TripMember.trip_id == trip_id,
            (TripMember.user_id == user.id) | (TripMember.invited_email == user.email),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise AppError(403, "forbidden", "Trip membership required")


def create_session_token(user_id: UUID) -> str:
    if not settings.jwt_signing_key:
        raise RuntimeError("JWT_SIGNING_KEY is not configured")
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(seconds=settings.session_cookie_max_age_seconds),
    }
    return jwt.encode(payload, settings.jwt_signing_key, algorithm=_JWT_ALGORITHM)


def decode_session_token(token: str) -> UUID:
    if not settings.jwt_signing_key:
        raise RuntimeError("JWT_SIGNING_KEY is not configured")
    try:
        payload = jwt.decode(
            token,
            settings.jwt_signing_key,
            algorithms=[_JWT_ALGORITHM],
        )
    except jwt.PyJWTError as exc:
        raise AppError(401, "unauthorized", "Authentication required") from exc

    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise AppError(401, "unauthorized", "Authentication required")
    try:
        return UUID(subject)
    except ValueError as exc:
        raise AppError(401, "unauthorized", "Authentication required") from exc


async def require_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    raw_token = request.cookies.get(settings.session_cookie_name)
    if raw_token is None:
        raise AppError(401, "unauthorized", "Authentication required")

    user_id = decode_session_token(raw_token)
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise AppError(401, "unauthorized", "Authentication required")
    return user


async def require_member(
    trip_id: UUID,
    current_user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    await _get_trip_or_404(session, trip_id)
    await _ensure_member(session, trip_id, current_user)
    return current_user


async def require_organizer(
    trip_id: UUID,
    current_user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    trip = await _get_trip_or_404(session, trip_id)
    if trip.organizer_id != current_user.id:
        raise AppError(403, "forbidden", "Organizer access required")
    return current_user
