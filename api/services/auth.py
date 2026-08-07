import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.errors import AppError
from db.models import MagicLinkToken, User
from services.email import EmailSender

_INVALID_TOKEN_MESSAGE = "Invalid or expired magic-link token"


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def display_name_from_email(email: str) -> str:
    local_part, _, _ = email.partition("@")
    return local_part


async def request_magic_link(
    session: AsyncSession,
    email: str,
    email_sender: EmailSender,
) -> None:
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_token(raw_token)
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.magic_link_ttl_seconds)

    async with session.begin():
        session.add(
            MagicLinkToken(
                email=str(email),
                token_hash=token_hash,
                expires_at=expires_at,
            )
        )

    magic_link_url = f"{settings.magic_link_base_url}?token={raw_token}"
    await email_sender.send_magic_link(str(email), magic_link_url)


async def verify_magic_link(session: AsyncSession, raw_token: str) -> User:
    token_hash = hash_token(raw_token)
    now = datetime.now(UTC)

    async with session.begin():
        result = await session.execute(
            select(MagicLinkToken).where(MagicLinkToken.token_hash == token_hash)
        )
        magic_link = result.scalar_one_or_none()
        if magic_link is None:
            raise AppError(400, "validation_error", _INVALID_TOKEN_MESSAGE)
        if magic_link.consumed_at is not None:
            raise AppError(400, "validation_error", _INVALID_TOKEN_MESSAGE)
        if magic_link.expires_at <= now:
            raise AppError(400, "validation_error", _INVALID_TOKEN_MESSAGE)

        magic_link.consumed_at = now

        user_result = await session.execute(select(User).where(User.email == magic_link.email))
        user = user_result.scalar_one_or_none()
        if user is None:
            user = User(
                email=magic_link.email,
                display_name=display_name_from_email(magic_link.email),
            )
            session.add(user)
            await session.flush()

        await session.refresh(user)
        return user
