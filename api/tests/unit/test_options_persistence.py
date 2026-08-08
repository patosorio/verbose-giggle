import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    BookingSource,
    BudgetBand,
    FlightOption,
    HotelOption,
    Leg,
    LegStatus,
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
from research.serpapi import (
    parse_flight_booking_sources,
    parse_flight_options,
    parse_hotel_booking_sources,
    parse_hotel_options,
)
from research.types import BookingSourcesParsed, FlightSearchParsed, HotelSearchParsed, ParsedHotelOption
from services import options as options_service

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "serpapi"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


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
        origin="BKK",
        destination="Phuket",
        start_date=date(2026, 11, 10),
        end_date=date(2026, 11, 14),
        nights=4,
        filters={"flight": {}, "hotel": {}},
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


@pytest.mark.asyncio
async def test_raw_api_response_written_before_option_card(db_session: AsyncSession) -> None:
    leg, run = await _seed_leg(db_session)
    body = _load("flights_search.json")
    flights = parse_flight_options(body, currency="THB")
    parsed = FlightSearchParsed(
        engine="google_flights",
        endpoint="flights_search",
        request_params={"engine": "google_flights", "currency": "THB"},
        response_body=body,
        requested_currency="THB",
        response_currency="THB",
        currency_mismatched=False,
        flights=flights,
    )

    add_order: list[str] = []
    original_add = db_session.add

    def tracking_add(instance: object) -> None:
        add_order.append(type(instance).__name__)
        original_add(instance)

    db_session.add = tracking_add  # type: ignore[method-assign]
    try:
        cards = await options_service.persist_flight_search(
            db_session,
            leg_id=leg.id,
            parsed=parsed,
            research_run_id=run.id,
        )
    finally:
        db_session.add = original_add  # type: ignore[method-assign]

    assert cards
    assert "RawApiResponse" in add_order
    assert "OptionCard" in add_order
    assert add_order.index("RawApiResponse") < add_order.index("OptionCard")

    raw_ids = {card.raw_response_id for card in cards}
    assert len(raw_ids) == 1
    raw = await db_session.get(RawApiResponse, next(iter(raw_ids)))
    assert raw is not None
    assert raw.source == RawApiSource.serpapi_flights_search
    assert raw.research_run_id == run.id

    details = await db_session.execute(
        select(FlightOption).where(FlightOption.option_card_id.in_([c.id for c in cards]))
    )
    assert len(details.scalars().all()) == len(cards)


@pytest.mark.asyncio
async def test_persist_hotels_and_booking_sources(db_session: AsyncSession) -> None:
    leg, run = await _seed_leg(db_session)
    body = _load("hotels_search.json")
    hotels = parse_hotel_options(
        body,
        currency="THB",
        checkin_date=date(2026, 11, 10),
        checkout_date=date(2026, 11, 14),
    )
    parsed = HotelSearchParsed(
        engine="google_hotels",
        endpoint="hotels_search",
        request_params={"engine": "google_hotels", "currency": "THB"},
        response_body=body,
        requested_currency="THB",
        response_currency="THB",
        currency_mismatched=False,
        hotels=hotels,
    )
    cards = await options_service.persist_hotel_search(
        db_session,
        leg_id=leg.id,
        parsed=parsed,
        research_run_id=run.id,
    )
    assert len(cards) == 9
    assert cards[0].option_type == OptionType.hotel
    assert cards[0].tier == BudgetBand.budget
    assert cards[0].base_price_amount == Decimal("3900")

    hotel_detail = await db_session.get(HotelOption, cards[0].id)
    assert hotel_detail is not None

    booking_body = _load("hotels_property.json")
    sources = parse_hotel_booking_sources(booking_body, currency="THB")
    booking_parsed = BookingSourcesParsed(
        engine="google_hotels",
        endpoint="hotels_property",
        request_params={"engine": "google_hotels", "property_token": "prop-07"},
        response_body=booking_body,
        requested_currency="THB",
        response_currency="THB",
        currency_mismatched=False,
        sources=sources,
    )
    rows = await options_service.persist_booking_sources(
        db_session,
        option_card_id=cards[0].id,
        parsed=booking_parsed,
        research_run_id=None,
    )
    assert len(rows) == 3
    assert all(row.booking_post_data is None for row in rows)
    assert all(row.raw_response_id is not None for row in rows)

    raw = await db_session.get(RawApiResponse, rows[0].raw_response_id)
    assert raw is not None
    assert raw.source == RawApiSource.serpapi_hotels_property
    assert raw.research_run_id is None


@pytest.mark.asyncio
async def test_persist_flight_booking_post_data(db_session: AsyncSession) -> None:
    leg, run = await _seed_leg(db_session)
    body = _load("flights_search.json")
    flights = parse_flight_options(body, currency="THB")
    cards = await options_service.persist_flight_search(
        db_session,
        leg_id=leg.id,
        parsed=FlightSearchParsed(
            engine="google_flights",
            endpoint="flights_search",
            request_params={"engine": "google_flights"},
            response_body=body,
            requested_currency="THB",
            response_currency="THB",
            currency_mismatched=False,
            flights=flights[:1],
        ),
        research_run_id=run.id,
    )
    booking_body = _load("flights_booking.json")
    sources = parse_flight_booking_sources(booking_body, currency="THB")
    rows = await options_service.persist_booking_sources(
        db_session,
        option_card_id=cards[0].id,
        parsed=BookingSourcesParsed(
            engine="google_flights",
            endpoint="flights_booking",
            request_params={"engine": "google_flights", "booking_token": "token-flight-01"},
            response_body=booking_body,
            requested_currency="THB",
            response_currency="THB",
            currency_mismatched=False,
            sources=sources,
        ),
    )
    stored = await db_session.execute(
        select(BookingSource).where(BookingSource.option_card_id == cards[0].id)
    )
    booking_rows = list(stored.scalars().all())
    assert len(booking_rows) == 3
    with_post = [row for row in booking_rows if row.booking_post_data is not None]
    assert len(with_post) == 2
    assert with_post[0].booking_post_data == {"post_data": "u=fixture-post-body-thai-airways"}


def _hotel_at_price(price: int) -> ParsedHotelOption:
    return ParsedHotelOption(
        property_token=f"prop-{price}",
        name=f"Hotel {price}",
        title=f"Hotel {price}",
        price_amount=Decimal(price),
        currency="THB",
        star_rating=Decimal("4"),
        gps_lat=Decimal("7.8804"),
        gps_lng=Decimal("98.3923"),
        checkin_date=date(2026, 11, 10),
        checkout_date=date(2026, 11, 14),
        free_cancellation=False,
        eco_certified=False,
        amenities=[],
    )


@pytest.mark.asyncio
async def test_persist_hotels_keeps_overflow_with_null_tier(
    db_session: AsyncSession,
) -> None:
    leg, run = await _seed_leg(db_session)
    hotels = [_hotel_at_price(1000 + i * 100) for i in range(11)]
    cards = await options_service.persist_hotel_search(
        db_session,
        leg_id=leg.id,
        parsed=HotelSearchParsed(
            engine="google_hotels",
            endpoint="hotels_search",
            request_params={},
            response_body={},
            requested_currency="THB",
            response_currency="THB",
            currency_mismatched=False,
            hotels=hotels,
        ),
        research_run_id=run.id,
    )
    assert len(cards) == 11
    by_price = {int(c.base_price_amount or 0): c.tier for c in cards}
    assert by_price[1000] == BudgetBand.budget
    assert by_price[1800] == BudgetBand.premium
    assert by_price[1900] is None
    assert by_price[2000] is None
    assert sum(1 for t in by_price.values() if t is None) == 2
