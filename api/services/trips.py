from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import AppError
from db.models import Trip, TripMember, TripMemberRole, TripStatus, User
from schemas.trips import TripCreateIn, TripPatchIn


async def create_trip(session: AsyncSession, organizer: User, data: TripCreateIn) -> Trip:
    try:
        trip = Trip(
            name=data.name,
            organizer_id=organizer.id,
            home_currency=data.home_currency,
            budget_band=data.budget_band,
            budget_target_amount=data.budget_target_amount,
            status=TripStatus.planning,
        )
        session.add(trip)
        await session.flush()

        session.add(
            TripMember(
                trip_id=trip.id,
                user_id=organizer.id,
                invited_email=organizer.email,
                role=TripMemberRole.organizer,
                joined_at=datetime.now(UTC),
            )
        )
        await session.commit()
        await session.refresh(trip)
        return trip
    except Exception:
        await session.rollback()
        raise


async def list_trips_for_user(
    session: AsyncSession,
    user: User,
    *,
    limit: int,
    offset: int,
) -> list[Trip]:
    result = await session.execute(
        select(Trip)
        .join(TripMember, TripMember.trip_id == Trip.id)
        .where(
            Trip.status != TripStatus.archived,
            or_(
                TripMember.user_id == user.id,
                TripMember.invited_email == user.email,
            ),
        )
        .order_by(Trip.created_at.desc())
        .limit(limit)
        .offset(offset)
        .distinct()
    )
    return list(result.scalars().all())


async def get_trip(session: AsyncSession, trip_id: UUID) -> Trip:
    result = await session.execute(select(Trip).where(Trip.id == trip_id))
    trip = result.scalar_one_or_none()
    if trip is None:
        raise AppError(404, "not_found", "Trip not found")
    return trip


async def delete_trip(session: AsyncSession, trip_id: UUID) -> None:
    """Soft-delete: archive the trip. No FK CASCADE on Trip children — hard delete
    would fail while members/legs/options exist. Archived trips are hidden from
    GET /trips; membership rows are left intact for audit.
    """
    try:
        result = await session.execute(select(Trip).where(Trip.id == trip_id))
        trip = result.scalar_one_or_none()
        if trip is None:
            raise AppError(404, "not_found", "Trip not found")
        if trip.status == TripStatus.archived:
            return
        trip.status = TripStatus.archived
        await session.commit()
    except AppError:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise


async def patch_trip(session: AsyncSession, trip_id: UUID, data: TripPatchIn) -> Trip:
    try:
        result = await session.execute(select(Trip).where(Trip.id == trip_id))
        trip = result.scalar_one_or_none()
        if trip is None:
            raise AppError(404, "not_found", "Trip not found")

        updates = data.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(trip, field, value)

        await session.commit()
        await session.refresh(trip)
        return trip
    except AppError:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise


async def list_members(session: AsyncSession, trip_id: UUID) -> list[TripMember]:
    result = await session.execute(
        select(TripMember).where(TripMember.trip_id == trip_id)
    )
    members = list(result.scalars().all())
    # Organizer first, then everyone else in whatever order they were fetched — TripMember
    # has no created_at to sort joined-members by, and role is a StrEnum where alphabetical
    # DB-side ordering ("member" < "organizer") wouldn't put organizer first, so this is a
    # small Python sort rather than an ORDER BY clause.
    return sorted(members, key=lambda m: m.role != TripMemberRole.organizer)


async def add_member(session: AsyncSession, trip_id: UUID, email: str) -> TripMember:
    try:
        trip_result = await session.execute(select(Trip).where(Trip.id == trip_id))
        trip = trip_result.scalar_one_or_none()
        if trip is None:
            raise AppError(404, "not_found", "Trip not found")

        user_result = await session.execute(select(User).where(User.email == email))
        existing_user = user_result.scalar_one_or_none()

        member = TripMember(
            trip_id=trip_id,
            user_id=existing_user.id if existing_user is not None else None,
            invited_email=email,
            role=TripMemberRole.member,
            joined_at=datetime.now(UTC) if existing_user is not None else None,
        )
        session.add(member)
        await session.commit()
        await session.refresh(member)
        return member
    except AppError:
        await session.rollback()
        raise
    except IntegrityError as exc:
        await session.rollback()
        raise AppError(
            409,
            "conflict",
            "A member with that email is already on this trip",
        ) from exc
    except Exception:
        await session.rollback()
        raise


async def remove_member(session: AsyncSession, trip_id: UUID, member_id: UUID) -> None:
    try:
        result = await session.execute(
            select(TripMember).where(
                TripMember.id == member_id,
                TripMember.trip_id == trip_id,
            )
        )
        member = result.scalar_one_or_none()
        if member is None:
            raise AppError(404, "not_found", "Trip member not found")
        if member.role == TripMemberRole.organizer:
            raise AppError(409, "conflict", "Cannot remove the trip organizer")

        await session.delete(member)
        await session.commit()
    except AppError:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise


async def transfer_organizer(
    session: AsyncSession,
    trip_id: UUID,
    new_organizer_user_id: UUID,
) -> Trip:
    try:
        trip_result = await session.execute(select(Trip).where(Trip.id == trip_id))
        trip = trip_result.scalar_one_or_none()
        if trip is None:
            raise AppError(404, "not_found", "Trip not found")

        members_result = await session.execute(
            select(TripMember).where(TripMember.trip_id == trip_id)
        )
        members = list(members_result.scalars().all())

        current_organizer_member = next(
            (member for member in members if member.role == TripMemberRole.organizer),
            None,
        )
        new_organizer_member = next(
            (member for member in members if member.user_id == new_organizer_user_id),
            None,
        )

        if new_organizer_member is None:
            raise AppError(
                400,
                "validation_error",
                "new_organizer_user_id must already be a trip member",
            )

        if current_organizer_member is not None:
            current_organizer_member.role = TripMemberRole.member

        new_organizer_member.role = TripMemberRole.organizer
        if new_organizer_member.joined_at is None:
            new_organizer_member.joined_at = datetime.now(UTC)

        trip.organizer_id = new_organizer_user_id
        await session.commit()
        await session.refresh(trip)
        return trip
    except AppError:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
