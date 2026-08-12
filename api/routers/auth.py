from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import create_session_token, require_user
from db.models import User
from db.session import get_session
from schemas.auth import (
    MagicLinkRequestIn,
    MagicLinkRequestOut,
    MagicLinkVerifyIn,
    MagicLinkVerifyOut,
    UserOut,
    UserPatchIn,
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
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MagicLinkVerifyOut:
    user = await auth_service.verify_magic_link(session, body.token)
    session_token = create_session_token(user.id)
    return MagicLinkVerifyOut(
        access_token=session_token,
        token_type="bearer",
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
async def me(current_user: Annotated[User, Depends(require_user)]) -> UserOut:
    return UserOut.model_validate(current_user)


@router.patch("/me", response_model=UserOut)
async def patch_me(
    body: UserPatchIn,
    current_user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserOut:
    user = await auth_service.update_display_name(
        session, current_user, body.display_name
    )
    return UserOut.model_validate(user)
