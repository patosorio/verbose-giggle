"""Phase 2 exit-criteria walkthrough — live SerpApi calls (spends quota).

Prerequisite: Phase 2 options/research migration applied, plus the
BookingSource.booking_post_data column migration. SERPAPI_KEY and DATABASE_URL
set in api/.env.

Invoke from api/:

    uv run python scripts/phase2_serpapi_walkthrough.py

This is intentionally NOT a pytest test — a bare `uv run pytest` must never
hit the live SerpApi.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_API_ROOT = Path(__file__).resolve().parents[1]
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from core.config import settings
from core.logging import setup_logging
from db.models import (
    BookingSource,
    BudgetBand,
    FlightOption,
    HotelOption,
    Leg,
    LegStatus,
    OptionCard,
    RawApiResponse,
    ResearchRun,
    ResearchRunStatus,
    ResearchRunType,
    Trip,
    TripStatus,
    User,
)
from research import serpapi
from services import options as options_service

logger = logging.getLogger("phase2_walkthrough")

ADULTS = 6
CHILDREN = 1
# google_hotels caps adults+children at 6. Flights accept the full reference
# party (6+1); hotels search with 5+1 so the child still affects pricing.
# google_hotels also requires one age (1–17) per child when children > 0.
HOTEL_ADULTS = 5
HOTEL_CHILDREN = 1
HOTEL_CHILDREN_AGES = [8]
HOME_CURRENCY = "THB"


@dataclass(frozen=True, slots=True)
class ReferenceLeg:
    label: str
    departure_id: str
    arrival_id: str
    hotel_q: str
    start_date: date
    end_date: date
    nights: int
    search_flights: bool


# Explicit SerpApi params for the 5 reference legs (docs/04_build_plan.md).
# Airport codes / hotel queries are walkthrough inputs — not resolved from
# Leg.origin/destination (Phase 6 wizard concern).
#
# Island hops without a scheduled commercial flight (Phuket↔Koh Yao Noi,
# Koh Yao Noi↔Koh Lanta) skip the flights search and only exercise hotels +
# property-details; otherwise we'd burn SerpApi calls on nonsense same-airport
# queries. Flights are still exercised on the three air legs.
REFERENCE_LEGS: tuple[ReferenceLeg, ...] = (
    ReferenceLeg(
        label="BKK→Phuket",
        departure_id="BKK",
        arrival_id="HKT",
        hotel_q="Phuket hotels",
        start_date=date(2026, 11, 10),
        end_date=date(2026, 11, 11),
        nights=1,
        search_flights=True,
    ),
    ReferenceLeg(
        label="Phuket→Koh Yao Noi (4n)",
        departure_id="HKT",
        arrival_id="HKT",
        hotel_q="Koh Yao Noi hotels",
        start_date=date(2026, 11, 11),
        end_date=date(2026, 11, 15),
        nights=4,
        search_flights=False,
    ),
    ReferenceLeg(
        label="Koh Yao Noi→Koh Lanta (2n)",
        departure_id="HKT",
        arrival_id="HKT",
        hotel_q="Koh Lanta hotels",
        start_date=date(2026, 11, 15),
        end_date=date(2026, 11, 17),
        nights=2,
        search_flights=False,
    ),
    ReferenceLeg(
        label="Koh Lanta→Krabi (1n)",
        departure_id="HKT",
        arrival_id="KBV",
        hotel_q="Krabi hotels",
        start_date=date(2026, 11, 17),
        end_date=date(2026, 11, 18),
        nights=1,
        search_flights=True,
    ),
    ReferenceLeg(
        label="Krabi→BKK",
        departure_id="KBV",
        arrival_id="BKK",
        hotel_q="Bangkok hotels near Suvarnabhumi",
        start_date=date(2026, 11, 18),
        end_date=date(2026, 11, 19),
        nights=1,
        search_flights=True,
    ),
)


async def _seed_trip(session: AsyncSession) -> Trip:
    user = User(
        email=f"phase2-walkthrough-{uuid4().hex[:8]}@example.com",
        display_name="Phase2 Walkthrough",
    )
    session.add(user)
    await session.flush()
    trip = Trip(
        name="Phase 2 SerpApi walkthrough",
        organizer_id=user.id,
        home_currency=HOME_CURRENCY,
        budget_band=BudgetBand.comfort,
        status=TripStatus.planning,
    )
    session.add(trip)
    await session.flush()

    for index, ref in enumerate(REFERENCE_LEGS):
        session.add(
            Leg(
                trip_id=trip.id,
                sequence_index=index,
                origin=ref.departure_id,
                destination=ref.label,
                start_date=ref.start_date,
                end_date=ref.end_date,
                nights=ref.nights,
                filters={"flight": {}, "hotel": {}},
                status=LegStatus.pending,
            )
        )
    await session.commit()
    await session.refresh(trip)
    return trip


async def _new_run(
    session: AsyncSession,
    leg_id: UUID,
    run_type: ResearchRunType,
) -> ResearchRun:
    run = ResearchRun(
        leg_id=leg_id,
        run_type=run_type,
        status=ResearchRunStatus.running,
        attempt_count=1,
        trace_id=str(uuid4()),
        started_at=datetime.now(UTC),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def _assert_traceability(session: AsyncSession, leg_id: UUID) -> None:
    cards = await session.execute(select(OptionCard).where(OptionCard.leg_id == leg_id))
    for card in cards.scalars().all():
        raw = await session.get(RawApiResponse, card.raw_response_id)
        if raw is None:
            raise RuntimeError(f"OptionCard {card.id} missing RawApiResponse")

    sources = await session.execute(
        select(BookingSource).where(
            BookingSource.option_card_id.in_(
                select(OptionCard.id).where(OptionCard.leg_id == leg_id)
            )
        )
    )
    for source in sources.scalars().all():
        raw = await session.get(RawApiResponse, source.raw_response_id)
        if raw is None:
            raise RuntimeError(f"BookingSource {source.id} missing RawApiResponse")
        if not source.deep_link_url:
            raise RuntimeError(f"BookingSource {source.id} missing deep_link_url")
        if source.ttl_expires_at <= source.fetched_at:
            raise RuntimeError(f"BookingSource {source.id} TTL not in the future")
        if source.ttl_expires_at - source.fetched_at < timedelta(minutes=19):
            raise RuntimeError(f"BookingSource {source.id} TTL shorter than expected")


async def _walk_leg(session: AsyncSession, leg: Leg, ref: ReferenceLeg) -> None:
    logger.info("=== leg %s (%s) ===", leg.sequence_index, ref.label)

    if ref.search_flights:
        flight_run = await _new_run(session, leg.id, ResearchRunType.flights)
        flight_parsed = await serpapi.search_flights(
            departure_id=ref.departure_id,
            arrival_id=ref.arrival_id,
            outbound_date=ref.start_date,
            currency=HOME_CURRENCY,
            adults=ADULTS,
            children=CHILDREN,
            leg_id=leg.id,
        )
        flight_cards = await options_service.persist_flight_search(
            session,
            leg_id=leg.id,
            parsed=flight_parsed,
            research_run_id=flight_run.id,
        )
        logger.info("persisted %s flight OptionCards", len(flight_cards))

        if not flight_cards:
            raise RuntimeError(f"No flight options for {ref.label}")

        flight_detail = await session.get(FlightOption, flight_cards[0].id)
        assert flight_detail is not None
        booking_parsed = await serpapi.fetch_flight_booking_options(
            booking_token=flight_detail.booking_token,
            currency=HOME_CURRENCY,
            leg_id=leg.id,
            departure_id=ref.departure_id,
            arrival_id=ref.arrival_id,
            outbound_date=ref.start_date,
            adults=ADULTS,
            children=CHILDREN,
        )
        booking_rows = await options_service.persist_booking_sources(
            session,
            option_card_id=flight_cards[0].id,
            parsed=booking_parsed,
        )
        if not booking_rows:
            raise RuntimeError(f"No flight booking sources for {ref.label}")
        logger.info(
            "flight booking sources=%s (post_data=%s plain=%s)",
            len(booking_rows),
            sum(1 for row in booking_rows if row.booking_post_data is not None),
            sum(1 for row in booking_rows if row.booking_post_data is None),
        )
        for row in booking_rows:
            logger.info(
                "  OTA=%s price=%s %s link=%s post=%s",
                row.seller_name,
                row.price_amount,
                row.currency,
                row.deep_link_url[:80],
                "yes" if row.booking_post_data else "no",
            )
    else:
        logger.info("skipping flights search for transfer/ferry leg %s", ref.label)

    hotel_run = await _new_run(session, leg.id, ResearchRunType.hotels)
    hotel_parsed = await serpapi.search_hotels(
        q=ref.hotel_q,
        check_in_date=ref.start_date,
        check_out_date=ref.end_date,
        currency=HOME_CURRENCY,
        adults=HOTEL_ADULTS,
        children=HOTEL_CHILDREN,
        children_ages=HOTEL_CHILDREN_AGES,
        leg_id=leg.id,
        gl="th",
    )
    hotel_cards = await options_service.persist_hotel_search(
        session,
        leg_id=leg.id,
        parsed=hotel_parsed,
        research_run_id=hotel_run.id,
    )
    logger.info("persisted %s hotel OptionCards", len(hotel_cards))

    if not hotel_cards:
        raise RuntimeError(f"No hotel options for {ref.label}")

    hotel_detail = await session.get(HotelOption, hotel_cards[0].id)
    assert hotel_detail is not None
    property_parsed = await serpapi.fetch_hotel_property_details(
        property_token=hotel_detail.property_token,
        check_in_date=hotel_detail.checkin_date,
        check_out_date=hotel_detail.checkout_date,
        currency=HOME_CURRENCY,
        adults=HOTEL_ADULTS,
        children=HOTEL_CHILDREN,
        children_ages=HOTEL_CHILDREN_AGES,
        q=ref.hotel_q,
        leg_id=leg.id,
        gl="th",
    )
    property_rows = await options_service.persist_booking_sources(
        session,
        option_card_id=hotel_cards[0].id,
        parsed=property_parsed,
    )
    if not property_rows:
        raise RuntimeError(f"No hotel booking sources for {ref.label}")
    logger.info("hotel booking sources=%s", len(property_rows))
    for row in property_rows:
        logger.info(
            "  OTA=%s price=%s %s link=%s",
            row.seller_name,
            row.price_amount,
            row.currency,
            row.deep_link_url[:80],
        )

    await _assert_traceability(session, leg.id)


async def main() -> None:
    setup_logging()
    if not settings.serpapi_key:
        raise SystemExit("SERPAPI_KEY is empty — set it in api/.env before running this script")
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is empty")

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        trip = await _seed_trip(session)
        logger.info("created trip_id=%s", trip.id)
        legs = await session.execute(
            select(Leg).where(Leg.trip_id == trip.id).order_by(Leg.sequence_index.asc())
        )
        leg_rows = list(legs.scalars().all())
        for leg, ref in zip(leg_rows, REFERENCE_LEGS, strict=True):
            await _walk_leg(session, leg, ref)

    await engine.dispose()
    logger.info("Phase 2 walkthrough complete")


if __name__ == "__main__":
    asyncio.run(main())
