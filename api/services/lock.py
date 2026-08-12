from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import AppError
from db.models import (
    Leg,
    Lock,
    LockEvent,
    LockEventType,
    OptionCard,
    OptionType,
    Trip,
)
from research.tiering import matches_home_currency
from schemas.legs import LegFiltersIn

# Must stay aligned with the partial unique index predicate in migration
# f6a7b8c9d0e1_lock_type_scoped and Lock.__table_args__ in db/models.py.
SINGLE_LOCK_OPTION_TYPES = frozenset(
    {OptionType.flight, OptionType.hotel, OptionType.imported}
)

# Research stores a per-person quote for these; lock snapshots the party total.
PER_PERSON_OPTION_TYPES = frozenset({OptionType.activity, OptionType.transport})


@dataclass(frozen=True)
class LockPriceComponents:
    total: Decimal
    unit_price: Decimal | None  # None for flight/hotel/imported
    party_size: int | None  # None for flight/hotel/imported


async def _trip_home_currency(session: AsyncSession, leg_id: UUID) -> str | None:
    result = await session.execute(
        select(Trip.home_currency).join(Leg, Leg.trip_id == Trip.id).where(Leg.id == leg_id)
    )
    return result.scalar_one_or_none()


def _leg_party_size(leg: Leg) -> int:
    """Sum of adults+children across this leg's occupancy rooms (docs/22 / docs/23)."""
    parsed = LegFiltersIn.model_validate(leg.filters)
    total = sum(room.adults + room.children for room in parsed.occupancy.rooms)
    return total if total > 0 else 1


def _lock_price_components(*, card: OptionCard, leg: Leg) -> LockPriceComponents:
    """Unit rates stay on the card; budget locks the trip total.

    Hotels/flights/imported: card.base_price_amount is already a stay/party total.
    Activities/transport: card stores per-person; multiply by leg occupancy party size.
    """
    assert card.base_price_amount is not None
    if card.option_type not in PER_PERSON_OPTION_TYPES:
        return LockPriceComponents(
            total=card.base_price_amount,
            unit_price=None,
            party_size=None,
        )
    party_size = _leg_party_size(leg)
    return LockPriceComponents(
        total=card.base_price_amount * party_size,
        unit_price=card.base_price_amount,
        party_size=party_size,
    )


async def _active_locks_for_leg(session: AsyncSession, leg_id: UUID) -> list[Lock]:
    result = await session.execute(
        select(Lock).where(Lock.leg_id == leg_id, Lock.unlocked_at.is_(None))
    )
    return list(result.scalars().all())


async def _active_lock_for_option_card(
    session: AsyncSession,
    *,
    leg_id: UUID,
    option_card_id: UUID,
) -> Lock | None:
    result = await session.execute(
        select(Lock).where(
            Lock.leg_id == leg_id,
            Lock.option_card_id == option_card_id,
            Lock.unlocked_at.is_(None),
        )
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

    leg = await session.get(Leg, leg_id)
    if leg is None:
        raise AppError(404, "not_found", "Leg not found")
    components = _lock_price_components(card=card, leg=leg)

    if card.option_type in SINGLE_LOCK_OPTION_TYPES:
        result = await session.execute(
            select(Lock).where(
                Lock.leg_id == leg_id,
                Lock.option_type == card.option_type,
                Lock.unlocked_at.is_(None),
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            raise AppError(
                409,
                "conflict",
                "Leg already has an active lock for this option type",
                details={"lock_id": str(existing.id)},
            )
    else:
        existing = await _active_lock_for_option_card(
            session,
            leg_id=leg_id,
            option_card_id=card.id,
        )
        if existing is not None:
            raise AppError(
                409,
                "conflict",
                "Option already has an active lock",
                details={"lock_id": str(existing.id)},
            )

    now = datetime.now(UTC)
    lock = Lock(
        leg_id=leg_id,
        option_card_id=card.id,
        option_type=card.option_type,
        locked_by_user_id=user_id,
        locked_price_amount=components.total,
        locked_unit_price_amount=components.unit_price,
        locked_party_size=components.party_size,
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
    option_card_id: UUID,
    user_id: UUID,
) -> None:
    locks = await _active_locks_for_leg(session, leg_id)
    lock = next((item for item in locks if item.option_card_id == option_card_id), None)
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


async def adjust_price(
    session: AsyncSession,
    *,
    leg_id: UUID,
    option_card_id: UUID,
    new_price_amount: Decimal,
    new_currency: str | None,
    note: str | None,
    user_id: UUID,
) -> Lock:
    lock = await _active_lock_for_option_card(
        session, leg_id=leg_id, option_card_id=option_card_id
    )
    if lock is None:
        raise AppError(404, "not_found", "Active lock not found")

    home_currency = await _trip_home_currency(session, leg_id)
    target_currency = (new_currency or lock.locked_currency).upper()
    if home_currency is not None and not matches_home_currency(target_currency, home_currency):
        raise AppError(
            400,
            "validation_error",
            "Cannot set a locked price in a currency that differs from the trip home currency",
            details={"currency": target_currency, "home_currency": home_currency},
        )

    previous_price_amount = lock.locked_price_amount
    previous_currency = lock.locked_currency

    lock.locked_price_amount = new_price_amount
    lock.locked_currency = target_currency
    # A manual override is a negotiated flat total, not a real per-person rate —
    # clearing these means BudgetSidebar's unit×party formula (docs/23) correctly
    # falls back to showing just the flat total instead of a fabricated unit price.
    lock.locked_unit_price_amount = None
    lock.locked_party_size = None

    now = datetime.now(UTC)
    session.add(
        LockEvent(
            lock_id=lock.id,
            event_type=LockEventType.price_adjusted,
            actor_user_id=user_id,
            occurred_at=now,
            previous_price_amount=previous_price_amount,
            new_price_amount=new_price_amount,
            previous_currency=previous_currency,
            new_currency=target_currency,
            note=note,
        )
    )
    await session.commit()
    await session.refresh(lock)
    return lock


async def set_booked(
    session: AsyncSession,
    *,
    leg_id: UUID,
    option_card_id: UUID,
    is_booked: bool,
    user_id: UUID,
) -> Lock:
    """Toggle is_booked on the active lock for this option card.

    On transition to True, booked_at is set to now. On transition to False,
    booked_at is cleared to None so a false is_booked never carries a stale
    booked_at. Re-asserting the same value leaves booked_at unchanged.
    user_id is unused here (membership is enforced by the router); kept for
    call-site symmetry with create_lock/delete_lock.
    """
    _ = user_id
    locks = await _active_locks_for_leg(session, leg_id)
    lock = next((item for item in locks if item.option_card_id == option_card_id), None)
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
