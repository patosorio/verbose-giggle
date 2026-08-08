from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import require_option_member
from db.models import User
from db.session import get_session
from schemas.options import (
    BookingSourceOut,
    CitationOut,
    ReactionIn,
    ReactionSummaryOut,
)
from services import options as options_service

router = APIRouter(prefix="/options", tags=["options"])


@router.post("/{option_id}/reactions", response_model=ReactionSummaryOut)
async def upsert_reaction(
    option_id: UUID,
    body: ReactionIn,
    current_user: Annotated[User, Depends(require_option_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReactionSummaryOut:
    return await options_service.upsert_reaction(
        session,
        option_id=option_id,
        user_id=current_user.id,
        reaction_type=body.reaction_type,
    )


@router.delete("/{option_id}/reactions", response_model=ReactionSummaryOut)
async def delete_reaction(
    option_id: UUID,
    current_user: Annotated[User, Depends(require_option_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReactionSummaryOut:
    return await options_service.delete_reaction(
        session,
        option_id=option_id,
        user_id=current_user.id,
    )


@router.get("/{option_id}/sources", response_model=list[BookingSourceOut])
async def get_booking_sources(
    option_id: UUID,
    _: Annotated[User, Depends(require_option_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[BookingSourceOut]:
    rows = await options_service.get_or_fetch_booking_sources(
        session,
        option_card_id=option_id,
    )
    return [BookingSourceOut.model_validate(row) for row in rows]


@router.get("/{option_id}/citations", response_model=list[CitationOut])
async def get_citations(
    option_id: UUID,
    _: Annotated[User, Depends(require_option_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[CitationOut]:
    rows = await options_service.get_citations_for_option(
        session,
        option_card_id=option_id,
    )
    return [CitationOut.model_validate(row) for row in rows]
