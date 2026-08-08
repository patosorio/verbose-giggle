from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import AppError
from db.models import Leg, Lock, Trip
from schemas.budget import BudgetLegOut, BudgetOut


async def get_trip_budget(session: AsyncSession, trip_id: UUID) -> BudgetOut:
    trip = await session.get(Trip, trip_id)
    if trip is None:
        raise AppError(404, "not_found", "Trip not found")

    legs_result = await session.execute(
        select(Leg).where(Leg.trip_id == trip_id).order_by(Leg.sequence_index.asc())
    )
    legs = list(legs_result.scalars().all())
    if not legs:
        return BudgetOut(
            home_currency=trip.home_currency,
            budget_band=trip.budget_band,
            budget_target_amount=trip.budget_target_amount,
            running_total=Decimal("0"),
            by_leg=[],
        )

    leg_ids = [leg.id for leg in legs]
    locks_result = await session.execute(
        select(Lock).where(Lock.leg_id.in_(leg_ids), Lock.unlocked_at.is_(None))
    )
    active_by_leg = {lock.leg_id: lock for lock in locks_result.scalars().all()}

    by_leg: list[BudgetLegOut] = []
    running_total = Decimal("0")
    for leg in legs:
        lock = active_by_leg.get(leg.id)
        if lock is None:
            by_leg.append(
                BudgetLegOut(leg_id=leg.id, locked_option_id=None, amount=None)
            )
            continue
        by_leg.append(
            BudgetLegOut(
                leg_id=leg.id,
                locked_option_id=lock.option_card_id,
                amount=lock.locked_price_amount,
            )
        )
        running_total += lock.locked_price_amount

    return BudgetOut(
        home_currency=trip.home_currency,
        budget_band=trip.budget_band,
        budget_target_amount=trip.budget_target_amount,
        running_total=running_total,
        by_leg=by_leg,
    )
