from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import require_leg_member, require_leg_organizer, require_user
from db.models import BudgetBand, OptionType, User
from db.session import get_session
from schemas.legs import LegOut, LegPatchIn
from schemas.lock import BookedIn, LockIn, LockOut
from schemas.options import OptionCardOut
from schemas.research import ResearchRunOut, ResearchStartIn, ResearchStartOut
from services import legs as legs_service
from services import lock as lock_service
from services import options as options_service
from services import research as research_service

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


@router.post(
    "/{leg_id}/research",
    status_code=202,
    response_model=ResearchStartOut,
)
async def start_research(
    leg_id: UUID,
    body: ResearchStartIn,
    _: Annotated[User, Depends(require_leg_organizer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ResearchStartOut:
    return await research_service.start_leg_research(
        session,
        leg_id=leg_id,
        run_type=body.run_type,
    )


@router.get(
    "/{leg_id}/research/{run_id}",
    response_model=ResearchRunOut,
)
async def get_research(
    leg_id: UUID,
    run_id: UUID,
    _: Annotated[User, Depends(require_leg_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ResearchRunOut:
    return await research_service.get_leg_research_run(
        session,
        leg_id=leg_id,
        run_id=run_id,
    )


@router.get(
    "/{leg_id}/options",
    response_model=list[OptionCardOut],
)
async def list_options(
    leg_id: UUID,
    current_user: Annotated[User, Depends(require_leg_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
    type: Annotated[
        Literal["flight", "hotel", "activity", "transport"] | None,
        Query(description="Filter by option_type"),
    ] = None,
    tier: Annotated[BudgetBand | None, Query()] = None,
) -> list[OptionCardOut]:
    option_type = OptionType(type) if type is not None else None
    return await options_service.list_options_for_leg(
        session,
        leg_id=leg_id,
        viewer_user_id=current_user.id,
        option_type=option_type,
        tier=tier,
    )


@router.post("/{leg_id}/lock", response_model=LockOut)
async def create_lock(
    leg_id: UUID,
    body: LockIn,
    current_user: Annotated[User, Depends(require_leg_organizer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LockOut:
    lock = await lock_service.create_lock(
        session,
        leg_id=leg_id,
        option_card_id=body.option_card_id,
        user_id=current_user.id,
    )
    return LockOut.model_validate(lock)


@router.delete("/{leg_id}/lock", status_code=204, response_class=Response)
async def delete_lock(
    leg_id: UUID,
    current_user: Annotated[User, Depends(require_leg_organizer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    await lock_service.delete_lock(
        session,
        leg_id=leg_id,
        user_id=current_user.id,
    )
    return Response(status_code=204)


@router.patch("/{leg_id}/lock/booked", response_model=LockOut)
async def set_lock_booked(
    leg_id: UUID,
    body: BookedIn,
    current_user: Annotated[User, Depends(require_leg_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LockOut:
    lock = await lock_service.set_booked(
        session,
        leg_id=leg_id,
        is_booked=body.is_booked,
        user_id=current_user.id,
    )
    return LockOut.model_validate(lock)
