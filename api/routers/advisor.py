"""AI trip advisor router — POST /advisor/messages (pre-trip, any authenticated user)."""

from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends

from core.security import require_user
from db.models import User
from schemas.advisor import AdvisorTurnIn, AdvisorTurnResponse
from services import advisor as advisor_service

router = APIRouter(prefix="/advisor", tags=["advisor"])


@router.post("/messages", response_model=AdvisorTurnResponse)
async def post_advisor_message(
    body: AdvisorTurnIn,
    _: Annotated[User, Depends(require_user)],
) -> AdvisorTurnResponse:
    # No trip exists yet — same auth gate as POST /trips (require_user), not organizer.
    return await advisor_service.run_advisor_turn(body, trace_id=str(uuid4()))
