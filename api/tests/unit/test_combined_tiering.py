"""Currency-gated pooling + stale-tier clearing (docs/01_architecture.md §9.12–13)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    BudgetBand,
    FlightOption,
    Leg,
    LegStatus,
    OptionCard,
    OptionType,
    RawApiResponse,
    RawApiSource,
    ResearchRun,
    ResearchRunStatus,
    ResearchRunType,
    Trip,
    TripStatus,
    User,
)
from research.types import (
    FlightSearchParsed,
    ParsedCitation,
    ParsedFlightOption,
    ParsedTransportOption,
    TransportResearchParsed,
)
from services.combined_tiering import (
    build_pool_from_new_and_existing,
    compute_combined_candidate_tiers,
    peer_tier_updates_for_eligible,
)
from services.options import persist_flight_search
from services.transport import persist_transport_research


def _citation() -> ParsedCitation:
    return ParsedCitation(claim_text="claim", source_url="https://example.com/x")


def _flight(
    price: int | str | Decimal,
    *,
    currency: str = "THB",
    token: str | None = None,
) -> ParsedFlightOption:
    amount = Decimal(price)
    return ParsedFlightOption(
        booking_token=token or f"tok-{amount}-{currency}",
        title=f"Flight {amount} {currency}",
        price_amount=amount,
        currency=currency,
        departure_airport="BKK",
        arrival_airport="HKT",
        departure_time=datetime(2026, 11, 10, 7, 0),
        arrival_time=datetime(2026, 11, 10, 8, 20),
        duration_minutes=80,
        stops=0,
        airlines=["TG"],
        layovers=[],
        bags_included=False,
        emissions_grams=None,
    )


def _transport(
    amount: Decimal | None,
    *,
    currency: str | None = "THB",
    departure: str = "Pier",
) -> ParsedTransportOption:
    return ParsedTransportOption(
        mode="ferry",
        operator_name="Op",
        departure_point=departure,
        arrival_point="Phuket",
        estimated_duration_minutes=90,
        estimated_price_amount=amount,
        estimated_price_currency=currency if amount is not None else None,
        booking_url="https://example.com/book",
        citations=[_citation()],
    )


async def _seed_leg(session: AsyncSession) -> tuple[Leg, ResearchRun]:
    user = User(email=f"{uuid4()}@example.com", display_name="Organizer")
    session.add(user)
    await session.flush()
    trip = Trip(
        name="Reference",
        organizer_id=user.id,
        home_currency="THB",
        budget_band=BudgetBand.comfort,
        status=TripStatus.planning,
    )
    session.add(trip)
    await session.flush()
    leg = Leg(
        trip_id=trip.id,
        sequence_index=0,
        origin="Bangkok",
        destination="Phuket",
        origin_iata="BKK",
        destination_iata="HKT",
        start_date=date(2026, 11, 10),
        end_date=date(2026, 11, 14),
        nights=4,
        filters={},
        status=LegStatus.pending,
    )
    session.add(leg)
    await session.flush()
    run = ResearchRun(
        leg_id=leg.id,
        run_type=ResearchRunType.flights,
        status=ResearchRunStatus.running,
        attempt_count=1,
        trace_id=str(uuid4()),
        started_at=datetime.now(UTC),
    )
    session.add(run)
    await session.flush()
    return leg, run


async def _seed_flight_card(
    session: AsyncSession,
    *,
    leg_id: UUID,
    research_run_id: UUID,
    price: Decimal,
    tier: BudgetBand,
    currency: str = "THB",
) -> OptionCard:
    raw = RawApiResponse(
        research_run_id=research_run_id,
        source=RawApiSource.serpapi_flights_search,
        request_params={},
        response_body={},
        fetched_at=datetime.now(UTC),
    )
    session.add(raw)
    await session.flush()
    card = OptionCard(
        leg_id=leg_id,
        option_type=OptionType.flight,
        tier=tier,
        title=f"Flight {price}",
        base_price_amount=price,
        currency=currency,
        raw_response_id=raw.id,
        research_run_id=research_run_id,
    )
    session.add(card)
    await session.flush()
    session.add(
        FlightOption(
            option_card_id=card.id,
            booking_token=f"tok-{price}",
            departure_airport="BKK",
            arrival_airport="HKT",
            departure_time=datetime(2026, 11, 10, 8, 0, tzinfo=UTC),
            arrival_time=datetime(2026, 11, 10, 9, 20, tzinfo=UTC),
            duration_minutes=80,
            stops=0,
            airlines=["TG"],
            layovers=[],
            bags_included=False,
            emissions_grams=None,
        )
    )
    await session.flush()
    return card


def test_build_pool_excludes_non_home_currency() -> None:
    flights = [_flight(100, currency="THB"), _flight(50, currency="USD")]
    transport = [
        _transport(Decimal("24"), currency="USD", departure="USD pier"),
        _transport(Decimal("900"), currency="THB", departure="THB pier"),
    ]
    pool = build_pool_from_new_and_existing(
        home_currency="THB",
        new_flights=flights,
        new_priced_transport=transport,
    )
    assert {item.price_amount for item in pool} == {Decimal("100"), Decimal("900")}


def test_compute_combined_excludes_foreign_currency_from_tiers() -> None:
    flights = [_flight(1290), _flight(1500), _flight(1800)]
    transport = [
        _transport(Decimal("24"), currency="USD"),
        _transport(Decimal("900"), currency="THB"),
        _transport(Decimal("1100"), currency="THB"),
    ]
    flight_tiers, _flight_untiered, transport_tiers, transport_untiered = (
        compute_combined_candidate_tiers(
            flights=flights,
            priced_transport=transport,
            home_currency="THB",
        )
    )
    # Pool: 900, 1100, 1290, 1500, 1800 → all budget (0-2) then comfort (3-4)
    by_price = {
        int(opt.price_amount): tier for tier, opt in flight_tiers
    } | {
        int(opt.estimated_price_amount or 0): tier for tier, opt in transport_tiers
    }
    assert by_price[900] == BudgetBand.budget
    assert by_price[1100] == BudgetBand.budget
    assert by_price[1290] == BudgetBand.budget
    assert by_price[1500] == BudgetBand.comfort
    assert by_price[1800] == BudgetBand.comfort
    assert 24 not in by_price
    assert transport_untiered == []


def test_peer_tier_updates_clear_unselected() -> None:
    keep_id = uuid4()
    drop_id = uuid4()

    class _Eligible:
        def __init__(self, card_id: UUID) -> None:
            self.id = card_id

    eligible = [_Eligible(keep_id), _Eligible(drop_id)]
    tiers_by_key = {f"card:{keep_id}": BudgetBand.comfort}
    updates = peer_tier_updates_for_eligible(eligible, tiers_by_key)  # type: ignore[arg-type]
    assert updates[keep_id] == BudgetBand.comfort
    assert updates[drop_id] is None


@pytest.mark.asyncio
async def test_foreign_currency_transport_persists_with_null_tier(
    db_session: AsyncSession,
) -> None:
    leg, run = await _seed_leg(db_session)
    await _seed_flight_card(
        db_session,
        leg_id=leg.id,
        research_run_id=run.id,
        price=Decimal("1000"),
        tier=BudgetBand.budget,
    )
    await db_session.commit()

    parsed = TransportResearchParsed(
        request_params={"research_type": "transport"},
        response_body={},
        options=[
            _transport(Decimal("24"), currency="USD", departure="USD"),
            _transport(Decimal("900"), currency="THB", departure="THB-A"),
            _transport(Decimal("1200"), currency="THB", departure="THB-B"),
        ],
        extraction_failed=False,
        extraction_error=None,
    )
    cards = await persist_transport_research(
        db_session,
        leg_id=leg.id,
        parsed=parsed,
        research_run_id=run.id,
        trace_id=run.trace_id,
    )

    by_price = {
        (c.base_price_amount.quantize(Decimal("0.01")), c.currency): c.tier
        for c in cards
        if c.base_price_amount is not None
    }
    assert by_price[(Decimal("24.00"), "USD")] is None
    assert by_price[(Decimal("900.00"), "THB")] == BudgetBand.budget
    assert by_price[(Decimal("1200.00"), "THB")] == BudgetBand.budget

    flight = (
        await db_session.execute(
            select(OptionCard).where(
                OptionCard.leg_id == leg.id,
                OptionCard.option_type == OptionType.flight,
                OptionCard.superseded_at.is_(None),
            )
        )
    ).scalar_one()
    # Pool: T900, F1000, T1200 → all budget
    assert flight.tier == BudgetBand.budget


@pytest.mark.asyncio
async def test_stale_tier_cleared_when_pool_exceeds_nine(
    db_session: AsyncSession,
) -> None:
    """Flights fully tiered at ≤9, then cheaper transport pushes some out → tier NULL."""
    leg, run = await _seed_leg(db_session)
    await db_session.commit()

    flight_prices = [100, 200, 300, 400, 500, 600, 700, 800, 900]
    flights_parsed = FlightSearchParsed(
        engine="google_flights",
        endpoint="flights_search",
        request_params={},
        response_body={},
        requested_currency="THB",
        response_currency="THB",
        currency_mismatched=False,
        flights=[_flight(p) for p in flight_prices],
    )
    await persist_flight_search(
        db_session,
        leg_id=leg.id,
        parsed=flights_parsed,
        research_run_id=run.id,
        retier_existing_transport=False,
    )

    flight_cards = (
        await db_session.execute(
            select(OptionCard).where(
                OptionCard.leg_id == leg.id,
                OptionCard.option_type == OptionType.flight,
                OptionCard.superseded_at.is_(None),
            )
        )
    ).scalars().all()
    assert len(flight_cards) == 9
    assert all(c.tier is not None for c in flight_cards)
    expensive = sorted(flight_cards, key=lambda c: c.base_price_amount or Decimal(0))
    assert expensive[-1].tier == BudgetBand.premium
    assert expensive[-2].tier == BudgetBand.premium
    assert expensive[-3].tier == BudgetBand.premium

    transport_run = ResearchRun(
        leg_id=leg.id,
        run_type=ResearchRunType.transport,
        status=ResearchRunStatus.running,
        attempt_count=1,
        trace_id=str(uuid4()),
        started_at=datetime.now(UTC),
    )
    db_session.add(transport_run)
    await db_session.commit()

    # Four cheap THB transport options → combined pool 13; top-9 excludes F700–F900
    transport_parsed = TransportResearchParsed(
        request_params={"research_type": "transport"},
        response_body={},
        options=[
            _transport(Decimal("10"), departure="A"),
            _transport(Decimal("20"), departure="B"),
            _transport(Decimal("30"), departure="C"),
            _transport(Decimal("40"), departure="D"),
        ],
        extraction_failed=False,
        extraction_error=None,
    )
    await persist_transport_research(
        db_session,
        leg_id=leg.id,
        parsed=transport_parsed,
        research_run_id=transport_run.id,
        trace_id=transport_run.trace_id,
    )

    refreshed = (
        await db_session.execute(
            select(OptionCard).where(
                OptionCard.leg_id == leg.id,
                OptionCard.option_type == OptionType.flight,
                OptionCard.superseded_at.is_(None),
            )
        )
    ).scalars().all()
    by_price = {int(c.base_price_amount or 0): c.tier for c in refreshed}
    # Top-9: T10,20,30,40, F100,200,300,400,500 → F600–900 cleared
    # budget: T10–30; comfort: T40,F100,F200; premium: F300–500
    assert by_price[100] == BudgetBand.comfort
    assert by_price[200] == BudgetBand.comfort
    assert by_price[300] == BudgetBand.premium
    assert by_price[400] == BudgetBand.premium
    assert by_price[500] == BudgetBand.premium
    assert by_price[600] is None
    assert by_price[700] is None
    assert by_price[800] is None
    assert by_price[900] is None
    assert sum(1 for t in by_price.values() if t == BudgetBand.premium) == 3
    assert sum(1 for t in by_price.values() if t is None) == 4


@pytest.mark.asyncio
async def test_live_shape_regression_currency_and_stale_tiers(
    db_session: AsyncSession,
) -> None:
    """Shape that surfaced both bugs live: 9 flights ~1290–1804 THB + mixed transport."""
    leg, run = await _seed_leg(db_session)
    await db_session.commit()

    flight_prices = [1290, 1350, 1400, 1450, 1500, 1600, 1700, 1750, 1804]
    await persist_flight_search(
        db_session,
        leg_id=leg.id,
        parsed=FlightSearchParsed(
            engine="google_flights",
            endpoint="flights_search",
            request_params={},
            response_body={},
            requested_currency="THB",
            response_currency="THB",
            currency_mismatched=False,
            flights=[_flight(p) for p in flight_prices],
        ),
        research_run_id=run.id,
        retier_existing_transport=False,
    )

    transport_run = ResearchRun(
        leg_id=leg.id,
        run_type=ResearchRunType.transport,
        status=ResearchRunStatus.running,
        attempt_count=1,
        trace_id=str(uuid4()),
        started_at=datetime.now(UTC),
    )
    db_session.add(transport_run)
    await db_session.commit()

    await persist_transport_research(
        db_session,
        leg_id=leg.id,
        parsed=TransportResearchParsed(
            request_params={"research_type": "transport"},
            response_body={},
            options=[
                _transport(Decimal("24"), currency="USD", departure="USD"),
                _transport(Decimal("900"), currency="THB", departure="cheap"),
                _transport(Decimal("1100"), currency="THB", departure="mid"),
                _transport(Decimal("2000"), currency="THB", departure="pricey"),
            ],
            extraction_failed=False,
            extraction_error=None,
        ),
        research_run_id=transport_run.id,
        trace_id=transport_run.trace_id,
    )

    cards = (
        await db_session.execute(
            select(OptionCard).where(
                OptionCard.leg_id == leg.id,
                OptionCard.superseded_at.is_(None),
                OptionCard.option_type.in_([OptionType.flight, OptionType.transport]),
            )
        )
    ).scalars().all()

    # Eligible THB pool sorted: 900, 1100, 1290, 1350, 1400, 1450, 1500, 1600, 1700
    # (1750 F, 1804 F fall out → tier cleared; 2000 T is a fresh home-currency
    # candidate outside top-9 → persisted with tier=NULL, Bug 3).
    # USD 24 excluded from pool, persisted with tier NULL.
    # budget: 900T, 1100T, 1290F
    # comfort: 1350F, 1400F, 1450F
    # premium: 1500F, 1600F, 1700F
    def _key(amount: Decimal | None, currency: str) -> tuple[Decimal, str]:
        assert amount is not None
        return (amount.quantize(Decimal("0.01")), currency)

    expected: dict[tuple[Decimal, str], BudgetBand | None] = {
        _key(Decimal("24"), "USD"): None,
        _key(Decimal("900"), "THB"): BudgetBand.budget,
        _key(Decimal("1100"), "THB"): BudgetBand.budget,
        _key(Decimal("1290"), "THB"): BudgetBand.budget,
        _key(Decimal("1350"), "THB"): BudgetBand.comfort,
        _key(Decimal("1400"), "THB"): BudgetBand.comfort,
        _key(Decimal("1450"), "THB"): BudgetBand.comfort,
        _key(Decimal("1500"), "THB"): BudgetBand.premium,
        _key(Decimal("1600"), "THB"): BudgetBand.premium,
        _key(Decimal("1700"), "THB"): BudgetBand.premium,
        _key(Decimal("1750"), "THB"): None,
        _key(Decimal("1804"), "THB"): None,
        _key(Decimal("2000"), "THB"): None,
    }
    actual = {_key(c.base_price_amount, c.currency): c.tier for c in cards}
    assert actual == expected
    assert sum(1 for t in actual.values() if t == BudgetBand.premium) == 3
    assert sum(1 for t in actual.values() if t == BudgetBand.budget) == 3
    assert sum(1 for t in actual.values() if t == BudgetBand.comfort) == 3


@pytest.mark.asyncio
async def test_transport_persists_home_currency_overflow_with_null_tier(
    db_session: AsyncSession,
) -> None:
    """10+ home-currency priced transport options: all persist; top-9 tiered, rest NULL."""
    leg, run = await _seed_leg(db_session)
    await db_session.commit()

    options = [
        _transport(Decimal(str(100 * i)), departure=f"Pier {i}") for i in range(1, 12)
    ]
    cards = await persist_transport_research(
        db_session,
        leg_id=leg.id,
        parsed=TransportResearchParsed(
            request_params={"research_type": "transport"},
            response_body={},
            options=options,
            extraction_failed=False,
            extraction_error=None,
        ),
        research_run_id=run.id,
        trace_id=run.trace_id,
    )
    assert len(cards) == 11
    tiered = [c for c in cards if c.tier is not None]
    untiered = [c for c in cards if c.tier is None]
    assert len(tiered) == 9
    assert len(untiered) == 2
    assert {int(c.base_price_amount or 0) for c in untiered} == {1000, 1100}
    assert sum(1 for c in tiered if c.tier == BudgetBand.budget) == 3
    assert sum(1 for c in tiered if c.tier == BudgetBand.comfort) == 3
    assert sum(1 for c in tiered if c.tier == BudgetBand.premium) == 3


@pytest.mark.asyncio
async def test_flights_persist_home_currency_overflow_with_null_tier(
    db_session: AsyncSession,
) -> None:
    """10 home-currency flights: all persist; cheapest 9 tiered, 10th NULL."""
    leg, run = await _seed_leg(db_session)
    await db_session.commit()

    flights = [_flight(100 * i) for i in range(1, 11)]
    cards = await persist_flight_search(
        db_session,
        leg_id=leg.id,
        parsed=FlightSearchParsed(
            engine="google_flights",
            endpoint="flights_search",
            request_params={},
            response_body={},
            requested_currency="THB",
            response_currency="THB",
            currency_mismatched=False,
            flights=flights,
        ),
        research_run_id=run.id,
        retier_existing_transport=False,
    )
    assert len(cards) == 10
    by_price = {int(c.base_price_amount or 0): c.tier for c in cards}
    assert by_price[1000] is None
    assert by_price[100] == BudgetBand.budget
    assert by_price[900] == BudgetBand.premium
    assert sum(1 for t in by_price.values() if t is None) == 1
    assert sum(1 for t in by_price.values() if t is not None) == 9
