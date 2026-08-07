from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import require_member, require_organizer, require_user
from db.models import User
from db.session import get_session
from schemas.legs import LegBulkCreateIn, LegOut
from schemas.travelers import TravelerCreateIn, TravelerOut
from schemas.trips import (
    TransferOrganizerIn,
    TripCreateIn,
    TripMemberCreateIn,
    TripMemberOut,
    TripOut,
    TripPatchIn,
    TripSummaryOut,
)
from services import legs as legs_service
from services import travelers as travelers_service
from services import trips as trips_service

router = APIRouter(prefix="/trips", tags=["trips"])


@router.post("", status_code=201, response_model=TripOut)
async def create_trip(
    body: TripCreateIn,
    current_user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TripOut:
    trip = await trips_service.create_trip(session, current_user, body)
    return TripOut.model_validate(trip)


@router.get("", response_model=list[TripSummaryOut])
async def list_trips(
    current_user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TripSummaryOut]:
    trips = await trips_service.list_trips_for_user(
        session, current_user, limit=limit, offset=offset
    )
    return [TripSummaryOut.model_validate(trip) for trip in trips]


@router.get("/{trip_id}", response_model=TripOut)
async def get_trip(
    trip_id: UUID,
    _: Annotated[User, Depends(require_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TripOut:
    trip = await trips_service.get_trip(session, trip_id)
    return TripOut.model_validate(trip)


@router.patch("/{trip_id}", response_model=TripOut)
async def patch_trip(
    trip_id: UUID,
    body: TripPatchIn,
    _: Annotated[User, Depends(require_organizer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TripOut:
    trip = await trips_service.patch_trip(session, trip_id, body)
    return TripOut.model_validate(trip)


@router.post("/{trip_id}/members", status_code=201, response_model=TripMemberOut)
async def add_member(
    trip_id: UUID,
    body: TripMemberCreateIn,
    _: Annotated[User, Depends(require_organizer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TripMemberOut:
    member = await trips_service.add_member(session, trip_id, str(body.email))
    return TripMemberOut.model_validate(member)


@router.delete("/{trip_id}/members/{member_id}", status_code=204, response_class=Response)
async def remove_member(
    trip_id: UUID,
    member_id: UUID,
    _: Annotated[User, Depends(require_organizer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    await trips_service.remove_member(session, trip_id, member_id)
    return Response(status_code=204)


@router.post("/{trip_id}/transfer-organizer", response_model=TripOut)
async def transfer_organizer(
    trip_id: UUID,
    body: TransferOrganizerIn,
    _: Annotated[User, Depends(require_organizer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TripOut:
    trip = await trips_service.transfer_organizer(
        session, trip_id, body.new_organizer_user_id
    )
    return TripOut.model_validate(trip)


@router.post("/{trip_id}/travelers", status_code=201, response_model=TravelerOut)
async def create_traveler(
    trip_id: UUID,
    body: TravelerCreateIn,
    _: Annotated[User, Depends(require_organizer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TravelerOut:
    traveler = await travelers_service.create_traveler(session, trip_id, body)
    return TravelerOut.model_validate(traveler)


@router.get("/{trip_id}/travelers", response_model=list[TravelerOut])
async def list_travelers(
    trip_id: UUID,
    _: Annotated[User, Depends(require_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TravelerOut]:
    travelers = await travelers_service.list_travelers(
        session, trip_id, limit=limit, offset=offset
    )
    return [TravelerOut.model_validate(traveler) for traveler in travelers]


@router.post("/{trip_id}/legs:bulk", status_code=201, response_model=list[LegOut])
async def bulk_create_legs(
    trip_id: UUID,
    body: LegBulkCreateIn,
    _: Annotated[User, Depends(require_organizer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[LegOut]:
    legs = await legs_service.bulk_create_legs(session, trip_id, body)
    return [LegOut.model_validate(leg) for leg in legs]


@router.get("/{trip_id}/legs", response_model=list[LegOut])
async def list_legs(
    trip_id: UUID,
    _: Annotated[User, Depends(require_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[LegOut]:
    legs = await legs_service.list_legs(session, trip_id, limit=limit, offset=offset)
    return [LegOut.model_validate(leg) for leg in legs]
