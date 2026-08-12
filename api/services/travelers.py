from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import AppError
from db.models import Traveler, Trip
from schemas.travelers import TravelerCreateIn, TravelerPatchIn


async def create_traveler(
    session: AsyncSession,
    trip_id: UUID,
    data: TravelerCreateIn,
) -> Traveler:
    try:
        trip_result = await session.execute(select(Trip).where(Trip.id == trip_id))
        if trip_result.scalar_one_or_none() is None:
            raise AppError(404, "not_found", "Trip not found")

        traveler = Traveler(
            trip_id=trip_id,
            name=data.name,
            age_category=data.age_category,
        )
        session.add(traveler)
        await session.commit()
        await session.refresh(traveler)
        return traveler
    except AppError:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise


async def list_travelers(
    session: AsyncSession,
    trip_id: UUID,
    *,
    limit: int,
    offset: int,
) -> list[Traveler]:
    result = await session.execute(
        select(Traveler)
        .where(Traveler.trip_id == trip_id)
        .order_by(Traveler.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def update_traveler(
    session: AsyncSession,
    trip_id: UUID,
    traveler_id: UUID,
    data: TravelerPatchIn,
) -> Traveler:
    try:
        result = await session.execute(select(Traveler).where(Traveler.id == traveler_id))
        traveler = result.scalar_one_or_none()
        if traveler is None or traveler.trip_id != trip_id:
            raise AppError(404, "not_found", "Traveler not found")

        updates = data.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(traveler, field, value)

        await session.commit()
        await session.refresh(traveler)
        return traveler
    except AppError:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise


async def delete_traveler(
    session: AsyncSession,
    trip_id: UUID,
    traveler_id: UUID,
) -> None:
    try:
        result = await session.execute(select(Traveler).where(Traveler.id == traveler_id))
        traveler = result.scalar_one_or_none()
        if traveler is None or traveler.trip_id != trip_id:
            raise AppError(404, "not_found", "Traveler not found")

        await session.delete(traveler)
        await session.commit()
    except AppError:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
