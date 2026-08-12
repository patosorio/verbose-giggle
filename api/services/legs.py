from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import AppError
from db.models import Leg, LegStatus, OptionCard, Trip
from schemas.legs import LegBulkCreateIn, LegPatchIn
from services.research import _active_lock_option_card_ids


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

        requested_indexes = [leg_in.sequence_index for leg_in in data.legs]
        if len(requested_indexes) != len(set(requested_indexes)):
            raise AppError(
                409,
                "conflict",
                "Duplicate sequence_index values in bulk create request",
                details={"sequence_indexes": requested_indexes},
            )

        if requested_indexes:
            existing_result = await session.execute(
                select(Leg.sequence_index).where(
                    Leg.trip_id == trip_id,
                    Leg.sequence_index.in_(requested_indexes),
                )
            )
            existing_indexes = sorted({index for index in existing_result.scalars().all()})
            if existing_indexes:
                raise AppError(
                    409,
                    "conflict",
                    "One or more sequence_index values already exist for this trip",
                    details={"sequence_indexes": existing_indexes},
                )

        created: list[Leg] = []
        for leg_in in data.legs:
            leg = Leg(
                trip_id=trip_id,
                sequence_index=leg_in.sequence_index,
                origin=leg_in.origin,
                destination=leg_in.destination,
                origin_iata=leg_in.origin_iata,
                destination_iata=leg_in.destination_iata,
                start_date=leg_in.start_date,
                end_date=leg_in.end_date,
                nights=derive_nights(leg_in.start_date, leg_in.end_date),
                filters=leg_in.filters.model_dump(mode="json"),
                skip_hotel=leg_in.skip_hotel,
                skip_flight=leg_in.skip_flight,
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
    except IntegrityError as exc:
        await session.rollback()
        raise AppError(
            409,
            "conflict",
            "One or more sequence_index values already exist for this trip",
        ) from exc
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


async def delete_leg(
    session: AsyncSession,
    leg_id: UUID,
    organizer_id: UUID,
) -> None:
    try:
        result = await session.execute(select(Leg).where(Leg.id == leg_id))
        leg = result.scalar_one_or_none()
        if leg is None:
            raise AppError(404, "not_found", "Leg not found")

        trip_id = leg.trip_id
        trip_result = await session.execute(select(Trip).where(Trip.id == trip_id))
        trip = trip_result.scalar_one_or_none()
        if trip is None:
            raise AppError(404, "not_found", "Trip not found")
        if trip.organizer_id != organizer_id:
            raise AppError(403, "forbidden", "Organizer access required")

        locked_card_ids = await _active_lock_option_card_ids(session, leg_id)
        if locked_card_ids:
            raise AppError(
                409,
                "conflict",
                "Cannot delete a leg with an active lock",
            )

        surviving_result = await session.execute(
            select(OptionCard.id)
            .where(
                OptionCard.leg_id == leg_id,
                OptionCard.superseded_at.is_(None),
            )
            .limit(1)
        )
        if surviving_result.scalar_one_or_none() is not None:
            raise AppError(
                409,
                "conflict",
                "Cannot delete a leg with surviving option cards",
            )

        await session.delete(leg)
        await session.commit()
    except AppError:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
