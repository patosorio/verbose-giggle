"""Flight+transport combined tiering helpers (docs/01_architecture.md §4.1).

Pooling only considers PRICED cards (base_price_amount IS NOT NULL) whose currency
equals the trip home_currency (§9.12). Null-tier / null-price / foreign-currency
transport cards never enter the pool.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import BudgetBand, OptionCard, OptionType
from research.tiering import PooledPriceItem, assign_pooled_price_tiers, matches_home_currency
from research.types import ParsedFlightOption, ParsedTransportOption

T = TypeVar("T")


def flight_pool_key(index: int) -> str:
    return f"new_flight:{index}"


def transport_pool_key(index: int) -> str:
    return f"new_transport:{index}"


def existing_card_pool_key(card_id: UUID) -> str:
    return f"card:{card_id}"


def parse_existing_card_pool_key(key: str) -> UUID | None:
    prefix = "card:"
    if not key.startswith(prefix):
        return None
    return UUID(key[len(prefix) :])


async def load_active_priced_option_cards(
    session: AsyncSession,
    *,
    leg_id: UUID,
    option_type: OptionType,
    home_currency: str,
) -> list[OptionCard]:
    """Active (non-superseded) priced home-currency cards of one option_type for a leg."""
    result = await session.execute(
        select(OptionCard).where(
            OptionCard.leg_id == leg_id,
            OptionCard.option_type == option_type,
            OptionCard.superseded_at.is_(None),
            OptionCard.base_price_amount.is_not(None),
            OptionCard.currency == home_currency.strip().upper(),
        )
    )
    return list(result.scalars().all())


def build_pool_from_new_and_existing(
    *,
    home_currency: str,
    new_flights: list[ParsedFlightOption] | None = None,
    new_priced_transport: list[ParsedTransportOption] | None = None,
    existing_priced_cards: list[OptionCard] | None = None,
) -> list[PooledPriceItem]:
    """Build a price pool; only home-currency candidates are included (§9.12)."""
    expected = home_currency.strip().upper()
    pool: list[PooledPriceItem] = []
    if new_flights:
        for index, flight in enumerate(new_flights):
            if not matches_home_currency(flight.currency, expected):
                continue
            pool.append(
                PooledPriceItem(key=flight_pool_key(index), price_amount=flight.price_amount)
            )
    if new_priced_transport:
        for index, option in enumerate(new_priced_transport):
            amount = option.estimated_price_amount
            if amount is None:
                continue
            if not matches_home_currency(option.estimated_price_currency, expected):
                continue
            pool.append(PooledPriceItem(key=transport_pool_key(index), price_amount=amount))
    if existing_priced_cards:
        for card in existing_priced_cards:
            if card.base_price_amount is None:
                continue
            if not matches_home_currency(card.currency, expected):
                continue
            pool.append(
                PooledPriceItem(
                    key=existing_card_pool_key(card.id),
                    price_amount=card.base_price_amount,
                )
            )
    return pool


def flight_assignments_from_pool(
    flights: list[ParsedFlightOption],
    tiers_by_key: dict[str, BudgetBand],
) -> list[tuple[BudgetBand, ParsedFlightOption]]:
    result: list[tuple[BudgetBand, ParsedFlightOption]] = []
    for index, flight in enumerate(flights):
        key = flight_pool_key(index)
        if key in tiers_by_key:
            result.append((tiers_by_key[key], flight))
    return result


def flight_untiered_from_pool(
    flights: list[ParsedFlightOption],
    tiers_by_key: dict[str, BudgetBand],
    *,
    home_currency: str,
) -> list[ParsedFlightOption]:
    """Home-currency flights eligible for the pool but not among the selected top-9."""
    expected = home_currency.strip().upper()
    result: list[ParsedFlightOption] = []
    for index, flight in enumerate(flights):
        if not matches_home_currency(flight.currency, expected):
            continue
        if flight_pool_key(index) not in tiers_by_key:
            result.append(flight)
    return result


def transport_assignments_from_pool(
    priced: list[ParsedTransportOption],
    tiers_by_key: dict[str, BudgetBand],
) -> list[tuple[BudgetBand, ParsedTransportOption]]:
    result: list[tuple[BudgetBand, ParsedTransportOption]] = []
    for index, option in enumerate(priced):
        key = transport_pool_key(index)
        if key in tiers_by_key:
            result.append((tiers_by_key[key], option))
    return result


def transport_untiered_from_pool(
    priced_home: list[ParsedTransportOption],
    tiers_by_key: dict[str, BudgetBand],
) -> list[ParsedTransportOption]:
    """Home-currency priced transport eligible for the pool but not among the top-9."""
    result: list[ParsedTransportOption] = []
    for index, option in enumerate(priced_home):
        if transport_pool_key(index) not in tiers_by_key:
            result.append(option)
    return result


def untiered_complement_by_identity(
    eligible: Sequence[T],
    selected: Sequence[tuple[BudgetBand, T]],
) -> list[T]:
    """Members of eligible not present (by identity) in selected assignments."""
    selected_ids = {id(item) for _, item in selected}
    return [item for item in eligible if id(item) not in selected_ids]


def existing_card_tiers_from_pool(
    tiers_by_key: dict[str, BudgetBand],
) -> dict[UUID, BudgetBand]:
    out: dict[UUID, BudgetBand] = {}
    for key, tier in tiers_by_key.items():
        card_id = parse_existing_card_pool_key(key)
        if card_id is not None:
            out[card_id] = tier
    return out


def peer_tier_updates_for_eligible(
    eligible_cards: Sequence[OptionCard],
    tiers_by_key: dict[str, BudgetBand],
) -> dict[UUID, BudgetBand | None]:
    """Selected cards get their new tier; eligible-but-unselected get NULL (§9.13)."""
    selected = existing_card_tiers_from_pool(tiers_by_key)
    return {card.id: selected.get(card.id) for card in eligible_cards}


async def apply_option_card_tier_updates(
    session: AsyncSession,
    tiers_by_card_id: dict[UUID, BudgetBand | None],
) -> int:
    """Write tier for selected cards; clear tier on eligible cards not in the fresh top-9.

    Does not touch superseded_at. Driven off the full eligible candidate set so write and
    clear cannot drift apart (docs/01_architecture.md §9.13).
    """
    if not tiers_by_card_id:
        return 0
    result = await session.execute(
        select(OptionCard).where(OptionCard.id.in_(list(tiers_by_card_id)))
    )
    updated = 0
    for card in result.scalars().all():
        new_tier = tiers_by_card_id[card.id]
        if card.tier != new_tier:
            card.tier = new_tier
            updated += 1
    await session.flush()
    return updated


def compute_combined_candidate_tiers(
    *,
    flights: list[ParsedFlightOption],
    priced_transport: list[ParsedTransportOption],
    home_currency: str,
) -> tuple[
    list[tuple[BudgetBand, ParsedFlightOption]],
    list[ParsedFlightOption],
    list[tuple[BudgetBand, ParsedTransportOption]],
    list[ParsedTransportOption],
]:
    """Single pool over this run's fresh priced flight+transport candidates (full run).

    Returns (flight_tiered, flight_untiered_home, transport_tiered, transport_untiered_home).
    Untiered lists are home-currency priced candidates outside the cheapest-9 cut — persist
    with tier=NULL (Prompt 4 Bug 3).
    """
    expected = home_currency.strip().upper()
    pool = build_pool_from_new_and_existing(
        home_currency=home_currency,
        new_flights=flights,
        new_priced_transport=priced_transport,
    )
    tiers_by_key = assign_pooled_price_tiers(pool)
    flight_tiered = flight_assignments_from_pool(flights, tiers_by_key)
    # Pool keys for transport use indices into the full priced_transport list (same as
    # build_pool_from_new_and_existing), so assignments/untiered must use that list too.
    transport_tiered = transport_assignments_from_pool(priced_transport, tiers_by_key)
    transport_untiered = [
        o
        for index, o in enumerate(priced_transport)
        if matches_home_currency(o.estimated_price_currency, expected)
        and transport_pool_key(index) not in tiers_by_key
    ]
    return (
        flight_tiered,
        flight_untiered_from_pool(flights, tiers_by_key, home_currency=expected),
        transport_tiered,
        transport_untiered,
    )
