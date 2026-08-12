from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import AppError
from db.models import HotelOption, Leg, Lock, OptionCard, OptionType, Trip
from schemas.budget import BudgetLegOut, BudgetOut, LockedOptionSummaryOut
from services.lock import PER_PERSON_OPTION_TYPES, _leg_party_size


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
    active_by_leg: dict[UUID, list[Lock]] = defaultdict(list)
    for lock in locks_result.scalars().all():
        active_by_leg[lock.leg_id].append(lock)

    option_card_ids = {
        lock.option_card_id
        for locks in active_by_leg.values()
        for lock in locks
    }
    cards_by_id: dict[UUID, OptionCard] = {}
    room_label_by_card_id: dict[UUID, str | None] = {}
    if option_card_ids:
        cards_result = await session.execute(
            select(OptionCard).where(OptionCard.id.in_(option_card_ids))
        )
        cards_by_id = {card.id: card for card in cards_result.scalars().all()}
        hotel_card_ids = [
            card_id
            for card_id, card in cards_by_id.items()
            if card.option_type == OptionType.hotel
        ]
        if hotel_card_ids:
            hotel_result = await session.execute(
                select(HotelOption.option_card_id, HotelOption.room_label).where(
                    HotelOption.option_card_id.in_(hotel_card_ids)
                )
            )
            room_label_by_card_id = {
                option_card_id: room_label
                for option_card_id, room_label in hotel_result.all()
            }

    by_leg: list[BudgetLegOut] = []
    running_total = Decimal("0")
    for leg in legs:
        locks = active_by_leg.get(leg.id, [])
        if not locks:
            by_leg.append(
                BudgetLegOut(
                    leg_id=leg.id,
                    locked_option_ids=[],
                    locked_options=[],
                    amount=None,
                )
            )
            continue
        locked_option_ids: list[UUID] = []
        locked_options: list[LockedOptionSummaryOut] = []
        for lock in locks:
            option_card = cards_by_id[lock.option_card_id]
            unit_price = lock.locked_unit_price_amount
            party_size = lock.locked_party_size
            # Legacy locks (pre-docs/23) have null snapshots — reconstruct for display
            # from the card unit rate + current leg occupancy so the summary can show
            # unit × party even before the user re-locks.
            if (
                option_card.option_type in PER_PERSON_OPTION_TYPES
                and (unit_price is None or party_size is None)
                and option_card.base_price_amount is not None
            ):
                unit_price = option_card.base_price_amount
                party_size = _leg_party_size(leg)
            display_amount = lock.locked_price_amount
            if (
                option_card.option_type in PER_PERSON_OPTION_TYPES
                and unit_price is not None
                and party_size is not None
            ):
                # Always expose the party total on the summary — never the bare
                # per-person unit — including legacy locks that only snapshotted unit.
                display_amount = unit_price * party_size
            locked_option_ids.append(lock.option_card_id)
            locked_options.append(
                LockedOptionSummaryOut(
                    option_card_id=lock.option_card_id,
                    option_type=option_card.option_type,
                    title=option_card.title,
                    tier=option_card.tier,
                    amount=display_amount,
                    currency=lock.locked_currency,
                    is_booked=lock.is_booked,
                    booked_at=lock.booked_at,
                    unit_price_amount=unit_price,
                    party_size=party_size,
                    room_label=(
                        room_label_by_card_id.get(lock.option_card_id)
                        if option_card.option_type == OptionType.hotel
                        else None
                    ),
                )
            )
        leg_amount = sum((opt.amount for opt in locked_options), Decimal("0"))
        by_leg.append(
            BudgetLegOut(
                leg_id=leg.id,
                locked_option_ids=locked_option_ids,
                locked_options=locked_options,
                amount=leg_amount,
            )
        )
        running_total += leg_amount

    return BudgetOut(
        home_currency=trip.home_currency,
        budget_band=trip.budget_band,
        budget_target_amount=trip.budget_target_amount,
        running_total=running_total,
        by_leg=by_leg,
    )
