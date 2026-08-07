from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import AppError
from db.models import Leg, LegStatus, Trip
from schemas.legs import LegBulkCreateIn, LegPatchIn


def derive_nights(start_date: date, end_date: date) -> int:
    return (end_date - start_date).days


async def bulk_create_legs(
    session: AsyncSession,
    trip_id: UUID,
    data: LegBulkCreateIn,
) -> list[Leg]:
    try:
        trip_result = await session.execute(select(Trip).where(Trip.id == trip_id))
        if trip_result.scalar_one_or_none() is None:
            raise AppError(404, "not_found", "Trip not found")

        created: list[Leg] = []
        for leg_in in data.legs:
            leg = Leg(
                trip_id=trip_id,
                sequence_index=leg_in.sequence_index,
                origin=leg_in.origin,
                destination=leg_in.destination,
                start_date=leg_in.start_date,
                end_date=leg_in.end_date,
                nights=derive_nights(leg_in.start_date, leg_in.end_date),
                filters=leg_in.filters.model_dump(mode="json"),
                status=LegStatus.pending,
            )
            session.add(leg)
            created.append(leg)

        await session.commit()
        for leg in created:
            await session.refresh(leg)
        return created
    except AppError:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise


async def list_legs(
    session: AsyncSession,
    trip_id: UUID,
    *,
    limit: int,
    offset: int,
) -> list[Leg]:
    result = await session.execute(
        select(Leg)
        .where(Leg.trip_id == trip_id)
        .order_by(Leg.sequence_index.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def patch_leg(
    session: AsyncSession,
    leg_id: UUID,
    organizer_id: UUID,
    data: LegPatchIn,
) -> Leg:
    try:
        result = await session.execute(select(Leg).where(Leg.id == leg_id))
        leg = result.scalar_one_or_none()
        if leg is None:
            raise AppError(404, "not_found", "Leg not found")

        trip_result = await session.execute(select(Trip).where(Trip.id == leg.trip_id))
        trip = trip_result.scalar_one_or_none()
        if trip is None:
            raise AppError(404, "not_found", "Trip not found")
        if trip.organizer_id != organizer_id:
            raise AppError(403, "forbidden", "Organizer access required")

        updates = data.model_dump(exclude_unset=True)
        if "filters" in updates and data.filters is not None:
            updates["filters"] = data.filters.model_dump(mode="json")

        for field, value in updates.items():
            setattr(leg, field, value)

        start_date = leg.start_date
        end_date = leg.end_date
        if end_date < start_date:
            raise AppError(
                400,
                "validation_error",
                "end_date must be on or after start_date",
            )
        leg.nights = derive_nights(start_date, end_date)

        await session.commit()
        await session.refresh(leg)
        return leg
    except AppError:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
