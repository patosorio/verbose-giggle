"""Phase 4 orchestrator tests — docs/04_build_plan.md Phase 4 / docs/11_phase4_cursor_prompts.md Prompt 1."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    AgeCategory,
    BudgetBand,
    Leg,
    LegStatus,
    Lock,
    OptionCard,
    OptionType,
    ResearchRun,
    ResearchRunStatus,
    ResearchRunType,
    Traveler,
    Trip,
    TripStatus,
    User,
)
from research.serpapi import parse_flight_options, parse_hotel_options
from research.types import (
    ActivitiesResearchParsed,
    FlightSearchParsed,
    HotelSearchParsed,
    ParsedActivityOption,
    ParsedCitation,
    ParsedFlightOption,
    ParsedTransportOption,
    SuggestedTiming,
    TransportResearchParsed,
)
from services.research import run_leg_research

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "serpapi"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _flight_parsed() -> FlightSearchParsed:
    body = _load("flights_search.json")
    flights = parse_flight_options(body, currency="THB")
    return FlightSearchParsed(
        engine="google_flights",
        endpoint="flights_search",
        request_params={"engine": "google_flights", "currency": "THB"},
        response_body=body,
        requested_currency="THB",
        response_currency="THB",
        currency_mismatched=False,
        flights=flights[:3],
    )


def _hotel_parsed(*, destination: str = "Phuket") -> HotelSearchParsed:
    body = _load("hotels_search.json")
    hotels = parse_hotel_options(
        body,
        currency="THB",
        checkin_date=date(2026, 11, 10),
        checkout_date=date(2026, 11, 14),
    )
    return HotelSearchParsed(
        engine="google_hotels",
        endpoint="hotels_search",
        request_params={"engine": "google_hotels", "q": f"{destination} hotels"},
        response_body=body,
        requested_currency="THB",
        response_currency="THB",
        currency_mismatched=False,
        hotels=hotels[:3],
    )


def _activities_parsed(*, titles: list[str] | None = None) -> ActivitiesResearchParsed:
    names = titles or [f"Activity {i}" for i in range(1, 4)]
    activities = [
        ParsedActivityOption(
            title=title,
            category="tour",
            description=f"Desc for {title}",
            duration_minutes=120,
            estimated_price_amount=Decimal(str(1000 + index * 100)),
            estimated_price_currency="THB",
            citations=[
                ParsedCitation(
                    claim_text=f"Claim for {title}",
                    source_url=f"https://example.com/{index}",
                )
            ],
            suggested_timing=SuggestedTiming.flexible,
        )
        for index, title in enumerate(names)
    ]
    return ActivitiesResearchParsed(
        request_params={"destination": "Phuket"},
        response_body={"ok": True},
        activities=activities,
        extraction_failed=False,
        extraction_error=None,
    )


def _transport_parsed(
    *,
    options: list[ParsedTransportOption] | None = None,
) -> TransportResearchParsed:
    if options is None:
        options = [
            ParsedTransportOption(
                mode="ferry",
                operator_name="FerryCo",
                departure_point="Pier A",
                arrival_point="Pier B",
                estimated_duration_minutes=90,
                estimated_price_amount=Decimal("500"),
                estimated_price_currency="THB",
                booking_url=None,
                citations=[
                    ParsedCitation(
                        claim_text="Ferry runs daily",
                        source_url="https://example.com/ferry",
                    )
                ],
            )
        ]
    return TransportResearchParsed(
        request_params={"research_type": "transport"},
        response_body={"ok": True},
        options=options,
        extraction_failed=False,
        extraction_error=None,
    )


def _flight_at_price(price: int, token: str | None = None) -> ParsedFlightOption:
    return ParsedFlightOption(
        booking_token=token or f"tok-{price}",
        title=f"Flight {price}",
        price_amount=Decimal(price),
        currency="THB",
        departure_airport="BKK",
        arrival_airport="HKT",
        departure_time=datetime(2026, 11, 10, 8, 0, tzinfo=UTC),
        arrival_time=datetime(2026, 11, 10, 9, 30, tzinfo=UTC),
        duration_minutes=90,
        stops=0,
        airlines=["PG"],
        layovers=[],
        bags_included=False,
        emissions_grams=None,
    )


def _priced_transport(price: int, *, departure: str = "Pier") -> ParsedTransportOption:
    return ParsedTransportOption(
        mode="ferry",
        operator_name=f"Op{price}",
        departure_point=departure,
        arrival_point="Island",
        estimated_duration_minutes=60,
        estimated_price_amount=Decimal(price),
        estimated_price_currency="THB",
        booking_url=None,
        citations=[
            ParsedCitation(
                claim_text=f"Fare {price}",
                source_url=f"https://example.com/{price}",
            )
        ],
    )


def _unpriced_transport() -> ParsedTransportOption:
    return ParsedTransportOption(
        mode="private_van",
        operator_name=None,
        departure_point="Town",
        arrival_point="Island",
        estimated_duration_minutes=None,
        estimated_price_amount=None,
        estimated_price_currency=None,
        booking_url=None,
        citations=[
            ParsedCitation(
                claim_text="Vans leave from town",
                source_url="https://example.com/van",
            )
        ],
    )


def _patch_full_research(
    monkeypatch: pytest.MonkeyPatch,
    *,
    flights: FlightSearchParsed | None = None,
    hotels: HotelSearchParsed | None = None,
    activities: ActivitiesResearchParsed | None = None,
    transport: TransportResearchParsed | None = None,
) -> None:
    flight_payload = flights if flights is not None else _flight_parsed()
    hotel_payload = hotels if hotels is not None else _hotel_parsed()
    activity_payload = activities if activities is not None else _activities_parsed()
    transport_payload = transport if transport is not None else _transport_parsed()

    async def fake_flights(**kwargs: object) -> FlightSearchParsed:
        return flight_payload

    async def fake_hotels(**kwargs: object) -> HotelSearchParsed:
        return hotel_payload

    async def fake_activities(**kwargs: object) -> ActivitiesResearchParsed:
        return activity_payload

    async def fake_transport(**kwargs: object) -> TransportResearchParsed:
        return transport_payload

    monkeypatch.setattr("services.research.search_flights", fake_flights)
    monkeypatch.setattr("services.research.search_hotels", fake_hotels)
    monkeypatch.setattr("services.research.research_activities", fake_activities)
    monkeypatch.setattr("services.research.research_transport", fake_transport)


async def _seed_leg(
    session: AsyncSession,
    *,
    origin_iata: str | None = "BKK",
    destination_iata: str | None = "HKT",
    destination: str = "Phuket",
    adults: int = 2,
    children: int = 0,
) -> tuple[Leg, Trip, User]:
    user = User(email=f"{uuid4()}@example.com", display_name="Organizer")
    session.add(user)
    await session.flush()
    trip = Trip(
        name="Phase4",
        organizer_id=user.id,
        home_currency="THB",
        budget_band=BudgetBand.comfort,
        status=TripStatus.planning,
    )
    session.add(trip)
    await session.flush()
    for i in range(adults):
        session.add(
            Traveler(
                trip_id=trip.id,
                name=f"Adult {i}",
                age_category=AgeCategory.adult,
            )
        )
    for i in range(children):
        session.add(
            Traveler(
                trip_id=trip.id,
                name=f"Child {i}",
                age_category=AgeCategory.child,
            )
        )
    leg = Leg(
        trip_id=trip.id,
        sequence_index=0,
        origin="Bangkok",
        destination=destination,
        origin_iata=origin_iata,
        destination_iata=destination_iata,
        start_date=date(2026, 11, 10),
        end_date=date(2026, 11, 14),
        nights=4,
        filters={"flight": {}, "hotel": {}},
        status=LegStatus.pending,
    )
    session.add(leg)
    await session.flush()
    return leg, trip, user


async def _queued_run(
    session: AsyncSession,
    leg_id: UUID,
    run_type: ResearchRunType,
) -> ResearchRun:
    run = ResearchRun(
        leg_id=leg_id,
        run_type=run_type,
        status=ResearchRunStatus.queued,
        attempt_count=0,
        trace_id=str(uuid4()),
    )
    session.add(run)
    await session.flush()
    return run


@pytest.mark.asyncio
async def test_null_iata_skips_flight_search_and_logs(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    leg, _trip, _user = await _seed_leg(
        db_session,
        origin_iata=None,
        destination_iata=None,
        destination="Koh Yao Noi",
    )
    run = await _queued_run(db_session, leg.id, ResearchRunType.full)
    await db_session.commit()

    flight_calls: list[object] = []

    async def fake_flights(**kwargs: object) -> FlightSearchParsed:
        flight_calls.append(kwargs)
        return _flight_parsed()

    async def fake_hotels(**kwargs: object) -> HotelSearchParsed:
        return _hotel_parsed(destination="Koh Yao Noi")

    async def fake_activities(**kwargs: object) -> ActivitiesResearchParsed:
        return _activities_parsed()

    async def fake_transport(**kwargs: object) -> TransportResearchParsed:
        return _transport_parsed()

    monkeypatch.setattr("services.research.search_flights", fake_flights)
    monkeypatch.setattr("services.research.search_hotels", fake_hotels)
    monkeypatch.setattr("services.research.research_activities", fake_activities)
    monkeypatch.setattr("services.research.research_transport", fake_transport)

    with caplog.at_level(logging.INFO, logger="services.research"):
        await run_leg_research(db_session, leg.id, run.id, ResearchRunType.full)

    assert flight_calls == []
    assert any("flight search skipped, missing IATA codes" in msg for msg in caplog.messages)

    await db_session.refresh(run)
    assert run.status == ResearchRunStatus.completed

    flights = await db_session.execute(
        select(func.count())
        .select_from(OptionCard)
        .where(
            OptionCard.leg_id == leg.id,
            OptionCard.option_type == OptionType.flight,
        )
    )
    assert flights.scalar_one() == 0

    hotels = await db_session.execute(
        select(func.count())
        .select_from(OptionCard)
        .where(
            OptionCard.leg_id == leg.id,
            OptionCard.option_type == OptionType.hotel,
            OptionCard.superseded_at.is_(None),
        )
    )
    assert hotels.scalar_one() == 3

    transports = await db_session.execute(
        select(func.count())
        .select_from(OptionCard)
        .where(
            OptionCard.leg_id == leg.id,
            OptionCard.option_type == OptionType.transport,
            OptionCard.superseded_at.is_(None),
        )
    )
    assert transports.scalar_one() >= 1


@pytest.mark.asyncio
async def test_mid_run_failure_retry_does_not_duplicate_cards(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leg, _trip, _user = await _seed_leg(db_session)
    run = await _queued_run(db_session, leg.id, ResearchRunType.full)
    await db_session.commit()

    call_count = {"hotels": 0}

    async def fake_flights(**kwargs: object) -> FlightSearchParsed:
        return _flight_parsed()

    async def fake_hotels(**kwargs: object) -> HotelSearchParsed:
        call_count["hotels"] += 1
        if call_count["hotels"] == 1:
            raise RuntimeError("forced mid-run hotel failure")
        return _hotel_parsed()

    async def fake_activities(**kwargs: object) -> ActivitiesResearchParsed:
        return _activities_parsed()

    async def fake_transport(**kwargs: object) -> TransportResearchParsed:
        return _transport_parsed()

    monkeypatch.setattr("services.research.search_flights", fake_flights)
    monkeypatch.setattr("services.research.search_hotels", fake_hotels)
    monkeypatch.setattr("services.research.research_activities", fake_activities)
    monkeypatch.setattr("services.research.research_transport", fake_transport)

    with pytest.raises(RuntimeError, match="forced mid-run hotel failure"):
        await run_leg_research(db_session, leg.id, run.id, ResearchRunType.full)

    await db_session.refresh(run)
    assert run.status == ResearchRunStatus.failed
    assert run.attempt_count == 1

    cards_after_fail = await db_session.execute(
        select(OptionCard).where(OptionCard.leg_id == leg.id)
    )
    partial_cards = list(cards_after_fail.scalars().all())
    assert partial_cards  # flights (and maybe activities) checkpointed
    assert all(card.research_run_id == run.id for card in partial_cards)

    await run_leg_research(db_session, leg.id, run.id, ResearchRunType.full)

    await db_session.refresh(run)
    assert run.status == ResearchRunStatus.completed
    assert run.attempt_count == 2

    active = await db_session.execute(
        select(OptionCard).where(
            OptionCard.leg_id == leg.id,
            OptionCard.superseded_at.is_(None),
        )
    )
    active_cards = list(active.scalars().all())
    assert all(card.research_run_id == run.id for card in active_cards)

    by_type = {
        OptionType.flight: 0,
        OptionType.hotel: 0,
        OptionType.activity: 0,
        OptionType.transport: 0,
    }
    for card in active_cards:
        by_type[card.option_type] += 1
    assert by_type[OptionType.flight] == 3
    assert by_type[OptionType.hotel] == 3
    assert by_type[OptionType.activity] == 3
    assert by_type[OptionType.transport] >= 1

    superseded = await db_session.execute(
        select(func.count())
        .select_from(OptionCard)
        .where(
            OptionCard.leg_id == leg.id,
            OptionCard.superseded_at.is_not(None),
        )
    )
    assert superseded.scalar_one() == len(partial_cards)


@pytest.mark.asyncio
async def test_completed_run_redelivery_is_noop(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leg, _trip, _user = await _seed_leg(db_session)
    run = await _queued_run(db_session, leg.id, ResearchRunType.hotels)
    await db_session.commit()

    calls = {"hotels": 0}

    async def fake_hotels(**kwargs: object) -> HotelSearchParsed:
        calls["hotels"] += 1
        return _hotel_parsed()

    monkeypatch.setattr("services.research.search_hotels", fake_hotels)

    await run_leg_research(db_session, leg.id, run.id, ResearchRunType.hotels)
    await run_leg_research(db_session, leg.id, run.id, ResearchRunType.hotels)

    assert calls["hotels"] == 1
    await db_session.refresh(run)
    assert run.status == ResearchRunStatus.completed
    assert run.attempt_count == 1


@pytest.mark.asyncio
async def test_activities_rerun_preserves_locked_card(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leg, _trip, user = await _seed_leg(db_session)
    run1 = await _queued_run(db_session, leg.id, ResearchRunType.activities)
    await db_session.commit()

    async def fake_activities_v1(**kwargs: object) -> ActivitiesResearchParsed:
        return _activities_parsed(titles=["Locked Tour", "Sibling A", "Sibling B"])

    monkeypatch.setattr("services.research.research_activities", fake_activities_v1)
    await run_leg_research(db_session, leg.id, run1.id, ResearchRunType.activities)

    cards = await db_session.execute(
        select(OptionCard)
        .where(
            OptionCard.leg_id == leg.id,
            OptionCard.option_type == OptionType.activity,
            OptionCard.superseded_at.is_(None),
        )
        .order_by(OptionCard.title.asc())
    )
    activity_cards = list(cards.scalars().all())
    assert len(activity_cards) == 3
    locked_card = next(card for card in activity_cards if card.title == "Locked Tour")
    sibling_ids = {card.id for card in activity_cards if card.id != locked_card.id}

    lock = Lock(
        leg_id=leg.id,
        option_card_id=locked_card.id,
        locked_by_user_id=user.id,
        locked_price_amount=locked_card.base_price_amount or Decimal("0"),
        locked_currency=locked_card.currency,
        locked_at=datetime.now(UTC),
        unlocked_at=None,
        is_booked=False,
    )
    db_session.add(lock)
    await db_session.commit()

    run2 = await _queued_run(db_session, leg.id, ResearchRunType.activities)
    await db_session.commit()

    async def fake_activities_v2(**kwargs: object) -> ActivitiesResearchParsed:
        return _activities_parsed(titles=["Fresh 1", "Fresh 2", "Fresh 3"])

    monkeypatch.setattr("services.research.research_activities", fake_activities_v2)
    await run_leg_research(db_session, leg.id, run2.id, ResearchRunType.activities)

    await db_session.refresh(locked_card)
    assert locked_card.superseded_at is None

    for sibling_id in sibling_ids:
        sibling = await db_session.get(OptionCard, sibling_id)
        assert sibling is not None
        assert sibling.superseded_at is not None

    fresh_active = await db_session.execute(
        select(OptionCard).where(
            OptionCard.leg_id == leg.id,
            OptionCard.option_type == OptionType.activity,
            OptionCard.superseded_at.is_(None),
            OptionCard.research_run_id == run2.id,
        )
    )
    assert len(list(fresh_active.scalars().all())) == 3


@pytest.mark.asyncio
async def test_full_run_combined_flight_transport_tiers(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2 flights + 2 transport interleave by price — not two independent tier spans."""
    leg, _trip, _user = await _seed_leg(db_session)
    run = await _queued_run(db_session, leg.id, ResearchRunType.full)
    await db_session.commit()

    # Prices: F100, F400, T200, T300 → sorted 100,200,300,400
    # indices 0-2 budget, 3 comfort → F100 budget, T200 budget, T300 budget, F400 comfort
    flights = FlightSearchParsed(
        engine="google_flights",
        endpoint="flights_search",
        request_params={},
        response_body={},
        requested_currency="THB",
        response_currency="THB",
        currency_mismatched=False,
        flights=[_flight_at_price(100), _flight_at_price(400)],
    )
    transport = _transport_parsed(
        options=[_priced_transport(200, departure="A"), _priced_transport(300, departure="B")]
    )
    _patch_full_research(
        monkeypatch,
        flights=flights,
        transport=transport,
    )

    await run_leg_research(db_session, leg.id, run.id, ResearchRunType.full)

    cards = (
        await db_session.execute(
            select(OptionCard).where(
                OptionCard.leg_id == leg.id,
                OptionCard.option_type.in_([OptionType.flight, OptionType.transport]),
                OptionCard.superseded_at.is_(None),
            )
        )
    ).scalars().all()
    by_price = {
        int(c.base_price_amount or 0): (c.option_type, c.tier) for c in cards
    }
    assert by_price[100] == (OptionType.flight, BudgetBand.budget)
    assert by_price[200] == (OptionType.transport, BudgetBand.budget)
    assert by_price[300] == (OptionType.transport, BudgetBand.budget)
    assert by_price[400] == (OptionType.flight, BudgetBand.comfort)


@pytest.mark.asyncio
async def test_transport_rerun_retiers_existing_flight_without_superseding(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leg, _trip, _user = await _seed_leg(db_session)
    flight_run = await _queued_run(db_session, leg.id, ResearchRunType.flights)
    await db_session.commit()

    async def fake_flights(**kwargs: object) -> FlightSearchParsed:
        return FlightSearchParsed(
            engine="google_flights",
            endpoint="flights_search",
            request_params={},
            response_body={},
            requested_currency="THB",
            response_currency="THB",
            currency_mismatched=False,
            # Alone: F100, F200, F300 → all budget (indices 0,1,2)
            flights=[
                _flight_at_price(100),
                _flight_at_price(200),
                _flight_at_price(300),
            ],
        )

    monkeypatch.setattr("services.research.search_flights", fake_flights)
    await run_leg_research(db_session, leg.id, flight_run.id, ResearchRunType.flights)

    flight_card = (
        await db_session.execute(
            select(OptionCard).where(
                OptionCard.leg_id == leg.id,
                OptionCard.option_type == OptionType.flight,
                OptionCard.base_price_amount == Decimal("300"),
                OptionCard.superseded_at.is_(None),
            )
        )
    ).scalar_one()
    assert flight_card.tier == BudgetBand.budget
    original_title = flight_card.title
    original_price = flight_card.base_price_amount
    original_superseded = flight_card.superseded_at

    transport_run = await _queued_run(db_session, leg.id, ResearchRunType.transport)
    await db_session.commit()

    # Add cheaper transport so F300 moves to comfort in pool of 5:
    # T10, T20, F100, F200, F300 → indices 0-2 budget, 3-4 comfort
    async def fake_transport(**kwargs: object) -> TransportResearchParsed:
        return _transport_parsed(
            options=[_priced_transport(10), _priced_transport(20)]
        )

    monkeypatch.setattr("services.research.research_transport", fake_transport)
    await run_leg_research(
        db_session, leg.id, transport_run.id, ResearchRunType.transport
    )

    await db_session.refresh(flight_card)
    assert flight_card.superseded_at is original_superseded
    assert flight_card.superseded_at is None
    assert flight_card.title == original_title
    assert flight_card.base_price_amount == original_price
    assert flight_card.tier == BudgetBand.comfort


@pytest.mark.asyncio
async def test_flights_rerun_retiers_existing_transport_without_superseding(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leg, _trip, _user = await _seed_leg(db_session)
    transport_run = await _queued_run(db_session, leg.id, ResearchRunType.transport)
    await db_session.commit()

    async def fake_transport(**kwargs: object) -> TransportResearchParsed:
        return _transport_parsed(
            options=[
                _priced_transport(100),
                _priced_transport(200),
                _priced_transport(300),
            ]
        )

    monkeypatch.setattr("services.research.research_transport", fake_transport)
    await run_leg_research(
        db_session, leg.id, transport_run.id, ResearchRunType.transport
    )

    transport_card = (
        await db_session.execute(
            select(OptionCard).where(
                OptionCard.leg_id == leg.id,
                OptionCard.option_type == OptionType.transport,
                OptionCard.base_price_amount == Decimal("300"),
                OptionCard.superseded_at.is_(None),
            )
        )
    ).scalar_one()
    assert transport_card.tier == BudgetBand.budget

    flight_run = await _queued_run(db_session, leg.id, ResearchRunType.flights)
    await db_session.commit()

    async def fake_flights(**kwargs: object) -> FlightSearchParsed:
        return FlightSearchParsed(
            engine="google_flights",
            endpoint="flights_search",
            request_params={},
            response_body={},
            requested_currency="THB",
            response_currency="THB",
            currency_mismatched=False,
            flights=[_flight_at_price(10), _flight_at_price(20)],
        )

    monkeypatch.setattr("services.research.search_flights", fake_flights)
    await run_leg_research(db_session, leg.id, flight_run.id, ResearchRunType.flights)

    await db_session.refresh(transport_card)
    assert transport_card.superseded_at is None
    assert transport_card.tier == BudgetBand.comfort


@pytest.mark.asyncio
async def test_null_iata_transport_tiers_alone_without_flight_pool_error(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leg, _trip, _user = await _seed_leg(
        db_session,
        origin_iata=None,
        destination_iata=None,
        destination="Koh Yao Noi",
    )
    run = await _queued_run(db_session, leg.id, ResearchRunType.full)
    await db_session.commit()

    transport = _transport_parsed(
        options=[_priced_transport(100), _priced_transport(200), _priced_transport(300)]
    )
    _patch_full_research(monkeypatch, transport=transport)

    await run_leg_research(db_session, leg.id, run.id, ResearchRunType.full)

    flights = await db_session.execute(
        select(func.count())
        .select_from(OptionCard)
        .where(
            OptionCard.leg_id == leg.id,
            OptionCard.option_type == OptionType.flight,
        )
    )
    assert flights.scalar_one() == 0

    transport_cards = (
        await db_session.execute(
            select(OptionCard).where(
                OptionCard.leg_id == leg.id,
                OptionCard.option_type == OptionType.transport,
                OptionCard.superseded_at.is_(None),
                OptionCard.base_price_amount.is_not(None),
            )
        )
    ).scalars().all()
    assert len(transport_cards) == 3
    assert all(c.tier == BudgetBand.budget for c in transport_cards)


@pytest.mark.asyncio
async def test_flights_rerun_leaves_null_price_transport_untouched(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leg, _trip, _user = await _seed_leg(db_session)
    transport_run = await _queued_run(db_session, leg.id, ResearchRunType.transport)
    await db_session.commit()

    async def fake_transport(**kwargs: object) -> TransportResearchParsed:
        return _transport_parsed(
            options=[_unpriced_transport(), _priced_transport(500)]
        )

    monkeypatch.setattr("services.research.research_transport", fake_transport)
    await run_leg_research(
        db_session, leg.id, transport_run.id, ResearchRunType.transport
    )

    null_card = (
        await db_session.execute(
            select(OptionCard).where(
                OptionCard.leg_id == leg.id,
                OptionCard.option_type == OptionType.transport,
                OptionCard.base_price_amount.is_(None),
                OptionCard.superseded_at.is_(None),
            )
        )
    ).scalar_one()
    assert null_card.tier is None

    flight_run = await _queued_run(db_session, leg.id, ResearchRunType.flights)
    await db_session.commit()

    async def fake_flights(**kwargs: object) -> FlightSearchParsed:
        return FlightSearchParsed(
            engine="google_flights",
            endpoint="flights_search",
            request_params={},
            response_body={},
            requested_currency="THB",
            response_currency="THB",
            currency_mismatched=False,
            flights=[_flight_at_price(100), _flight_at_price(200)],
        )

    monkeypatch.setattr("services.research.search_flights", fake_flights)
    await run_leg_research(db_session, leg.id, flight_run.id, ResearchRunType.flights)

    await db_session.refresh(null_card)
    assert null_card.tier is None
    assert null_card.superseded_at is None
    assert null_card.base_price_amount is None


@pytest.mark.asyncio
async def test_full_run_persists_combined_pool_overflow_with_null_tier(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Combined flight+transport pool >9 in one full run: excess of both types persist NULL."""
    leg, _trip, _user = await _seed_leg(db_session)
    run = await _queued_run(db_session, leg.id, ResearchRunType.full)
    await db_session.commit()

    # 7 flights (100..700) + 5 transport (10,20,30,40,50) = 12 home-currency priced
    # Top-9: T10-50 + F100-400 → F500-700 and nothing else from transport outside
    # Actually sorted: 10,20,30,40,50,100,200,300,400 | 500,600,700 out (all flights)
    flights = FlightSearchParsed(
        engine="google_flights",
        endpoint="flights_search",
        request_params={},
        response_body={},
        requested_currency="THB",
        response_currency="THB",
        currency_mismatched=False,
        flights=[_flight_at_price(p) for p in (100, 200, 300, 400, 500, 600, 700)],
    )
    transport = _transport_parsed(
        options=[_priced_transport(p, departure=f"P{p}") for p in (10, 20, 30, 40, 50)]
    )
    _patch_full_research(monkeypatch, flights=flights, transport=transport)

    await run_leg_research(db_session, leg.id, run.id, ResearchRunType.full)

    cards = (
        await db_session.execute(
            select(OptionCard).where(
                OptionCard.leg_id == leg.id,
                OptionCard.superseded_at.is_(None),
                OptionCard.option_type.in_([OptionType.flight, OptionType.transport]),
            )
        )
    ).scalars().all()
    flight_cards = [c for c in cards if c.option_type == OptionType.flight]
    transport_cards = [c for c in cards if c.option_type == OptionType.transport]
    assert len(flight_cards) == 7
    assert len(transport_cards) == 5

    by_price = {int(c.base_price_amount or 0): c.tier for c in cards}
    assert by_price[10] == BudgetBand.budget
    assert by_price[400] == BudgetBand.premium
    assert by_price[500] is None
    assert by_price[600] is None
    assert by_price[700] is None
    assert sum(1 for t in by_price.values() if t is None) == 3
    assert sum(1 for t in by_price.values() if t is not None) == 9
