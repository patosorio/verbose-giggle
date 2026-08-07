from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import create_session_token, require_user
from db.models import User
from db.session import get_session
from schemas.auth import (
    MagicLinkRequestIn,
    MagicLinkRequestOut,
    MagicLinkVerifyIn,
    MagicLinkVerifyOut,
    UserOut,
)
from services import auth as auth_service
from services.email import EmailSender, get_email_sender

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/magic-link/request", status_code=202, response_model=MagicLinkRequestOut)
async def request_magic_link(
    body: MagicLinkRequestIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    email_sender: Annotated[EmailSender, Depends(get_email_sender)],
) -> MagicLinkRequestOut:
    await auth_service.request_magic_link(session, body.email, email_sender)
    return MagicLinkRequestOut(message="If that email can receive mail, a magic link is on its way.")


@router.post("/magic-link/verify", response_model=MagicLinkVerifyOut)
async def verify_magic_link(
    body: MagicLinkVerifyIn,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MagicLinkVerifyOut:
    user = await auth_service.verify_magic_link(session, body.token)
    session_token = create_session_token(user.id)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_token,
        max_age=settings.session_cookie_max_age_seconds,
        httponly=settings.session_cookie_httponly,
        samesite=settings.session_cookie_samesite,
        secure=settings.session_cookie_secure,
        domain=settings.session_cookie_domain,
    )
    return MagicLinkVerifyOut(user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(current_user: Annotated[User, Depends(require_user)]) -> UserOut:
    return UserOut.model_validate(current_user)
