from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import require_user
from db.models import User
from db.session import get_session
from schemas.legs import LegOut, LegPatchIn
from services import legs as legs_service

router = APIRouter(prefix="/legs", tags=["legs"])


@router.patch("/{leg_id}", response_model=LegOut)
async def patch_leg(
    leg_id: UUID,
    body: LegPatchIn,
    current_user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LegOut:
    leg = await legs_service.patch_leg(session, leg_id, current_user.id, body)
    return LegOut.model_validate(leg)
