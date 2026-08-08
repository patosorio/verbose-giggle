from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import AppError
from db.models import Leg, Lock, LockEvent, LockEventType, OptionCard, Trip
from research.tiering import matches_home_currency


async def _trip_home_currency(session: AsyncSession, leg_id: UUID) -> str | None:
    result = await session.execute(
        select(Trip.home_currency).join(Leg, Leg.trip_id == Trip.id).where(Leg.id == leg_id)
    )
    return result.scalar_one_or_none()


async def _active_lock_for_leg(session: AsyncSession, leg_id: UUID) -> Lock | None:
    result = await session.execute(
        select(Lock).where(Lock.leg_id == leg_id, Lock.unlocked_at.is_(None))
    )
    return result.scalar_one_or_none()


async def create_lock(
    session: AsyncSession,
    *,
    leg_id: UUID,
    option_card_id: UUID,
    user_id: UUID,
) -> Lock:
    card = await session.get(OptionCard, option_card_id)
    if card is None or card.leg_id != leg_id:
        raise AppError(404, "not_found", "Option card not found")

    if card.base_price_amount is None:
        raise AppError(
            400,
            "validation_error",
            "Cannot lock an option without a base_price_amount",
        )

    home_currency = await _trip_home_currency(session, leg_id)
    if home_currency is None:
        raise AppError(404, "not_found", "Leg not found")
    if not matches_home_currency(card.currency, home_currency):
        raise AppError(
            400,
            "validation_error",
            "Cannot lock an option whose currency differs from the trip home currency",
            details={
                "option_currency": card.currency,
                "home_currency": home_currency,
            },
        )

    existing = await _active_lock_for_leg(session, leg_id)
    if existing is not None:
        raise AppError(
            409,
            "conflict",
            "Leg already has an active lock",
            details={"lock_id": str(existing.id)},
        )

    now = datetime.now(UTC)
    lock = Lock(
        leg_id=leg_id,
        option_card_id=card.id,
        locked_by_user_id=user_id,
        locked_price_amount=card.base_price_amount,
        locked_currency=card.currency,
        locked_at=now,
        unlocked_at=None,
        is_booked=False,
        booked_at=None,
    )
    session.add(lock)
    await session.flush()
    session.add(
        LockEvent(
            lock_id=lock.id,
            event_type=LockEventType.locked,
            actor_user_id=user_id,
            occurred_at=now,
        )
    )
    await session.commit()
    await session.refresh(lock)
    return lock


async def delete_lock(
    session: AsyncSession,
    *,
    leg_id: UUID,
    user_id: UUID,
) -> None:
    lock = await _active_lock_for_leg(session, leg_id)
    if lock is None:
        raise AppError(404, "not_found", "Active lock not found")

    now = datetime.now(UTC)
    lock.unlocked_at = now
    session.add(
        LockEvent(
            lock_id=lock.id,
            event_type=LockEventType.unlocked,
            actor_user_id=user_id,
            occurred_at=now,
        )
    )
    await session.commit()


async def set_booked(
    session: AsyncSession,
    *,
    leg_id: UUID,
    is_booked: bool,
    user_id: UUID,
) -> Lock:
    """Toggle is_booked on the leg's active lock.

    On transition to True, booked_at is set to now. On transition to False,
    booked_at is cleared to None so a false is_booked never carries a stale
    booked_at. Re-asserting the same value leaves booked_at unchanged.
    user_id is unused here (membership is enforced by the router); kept for
    call-site symmetry with create_lock/delete_lock.
    """
    _ = user_id
    lock = await _active_lock_for_leg(session, leg_id)
    if lock is None:
        raise AppError(404, "not_found", "Active lock not found")

    if is_booked and not lock.is_booked:
        lock.is_booked = True
        lock.booked_at = datetime.now(UTC)
    elif not is_booked and lock.is_booked:
        lock.is_booked = False
        lock.booked_at = None

    await session.commit()
    await session.refresh(lock)
    return lock
