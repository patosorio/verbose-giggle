"""Persistence tests for transport research (Phase 4.5) — no live API calls."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    BudgetBand,
    Citation,
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
    TransportMode,
    TransportOption,
    Trip,
    TripStatus,
    User,
)
from research.types import (
    ParsedCitation,
    ParsedTransportOption,
    TransportResearchParsed,
)
from services.transport import (
    drop_missing_citations,
    persist_transport_research,
)


def _citation(claim: str = "claim", url: str = "https://example.com/x") -> ParsedCitation:
    return ParsedCitation(claim_text=claim, source_url=url)


def _priced(
    *,
    amount: Decimal,
    departure: str = "Rassada Pier",
    arrival: str = "Koh Yao Noi",
    mode: str = "ferry",
    operator: str | None = "Lomprayah",
) -> ParsedTransportOption:
    return ParsedTransportOption(
        mode=mode,
        operator_name=operator,
        departure_point=departure,
        arrival_point=arrival,
        estimated_duration_minutes=90,
        estimated_price_amount=amount,
        estimated_price_currency="THB",
        booking_url="https://example.com/book",
        citations=[_citation()],
    )


def _unpriced(
    *,
    departure: str = "Phuket Town",
    arrival: str = "Koh Yao Noi",
) -> ParsedTransportOption:
    return ParsedTransportOption(
        mode="private_van",
        operator_name=None,
        departure_point=departure,
        arrival_point=arrival,
        estimated_duration_minutes=120,
        estimated_price_amount=None,
        estimated_price_currency=None,
        booking_url=None,
        citations=[_citation("Van route exists", "https://example.com/van")],
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
        origin="Phuket",
        destination="Koh Yao Noi",
        start_date=date(2026, 11, 10),
        end_date=date(2026, 11, 12),
        nights=2,
        filters={},
        status=LegStatus.pending,
    )
    session.add(leg)
    await session.flush()
    run = ResearchRun(
        leg_id=leg.id,
        run_type=ResearchRunType.transport,
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
) -> OptionCard:
    raw = RawApiResponse(
        research_run_id=research_run_id,
        source=RawApiSource.serpapi_flights_search,
        request_params={"engine": "google_flights"},
        response_body={},
        fetched_at=datetime.now(UTC),
    )
    session.add(raw)
    await session.flush()
    card = OptionCard(
        leg_id=leg_id,
        option_type=OptionType.flight,
        tier=BudgetBand.budget,
        title=f"Flight {price}",
        base_price_amount=price,
        currency="THB",
        raw_response_id=raw.id,
        research_run_id=research_run_id,
    )
    session.add(card)
    await session.flush()
    session.add(
        FlightOption(
            option_card_id=card.id,
            booking_token=f"tok-{price}",
            departure_airport="HKT",
            arrival_airport="USM",
            departure_time=datetime(2026, 11, 10, 8, 0, tzinfo=UTC),
            arrival_time=datetime(2026, 11, 10, 9, 0, tzinfo=UTC),
            duration_minutes=60,
            stops=0,
            airlines=["PG"],
            layovers=[],
            bags_included=False,
            emissions_grams=None,
        )
    )
    await session.flush()
    return card


def test_drop_missing_citations_priced_and_unpriced() -> None:
    priced_ok = _priced(amount=Decimal("500"))
    unpriced_ok = _unpriced()
    priced_bad = ParsedTransportOption(
        mode="ferry",
        operator_name=None,
        departure_point="A",
        arrival_point="B",
        estimated_duration_minutes=None,
        estimated_price_amount=Decimal("100"),
        estimated_price_currency="THB",
        booking_url=None,
        citations=[],
    )
    unpriced_bad = ParsedTransportOption(
        mode="bus",
        operator_name=None,
        departure_point="C",
        arrival_point="D",
        estimated_duration_minutes=None,
        estimated_price_amount=None,
        estimated_price_currency=None,
        booking_url=None,
        citations=[],
    )
    kept = drop_missing_citations([priced_ok, unpriced_ok, priced_bad, unpriced_bad])
    assert kept == [priced_ok, unpriced_ok]


@pytest.mark.asyncio
async def test_persist_priced_and_unpriced_with_pooled_tiering(
    db_session: AsyncSession,
) -> None:
    leg, run = await _seed_leg(db_session)
    await _seed_flight_card(
        db_session, leg_id=leg.id, research_run_id=run.id, price=Decimal("100")
    )
    await _seed_flight_card(
        db_session, leg_id=leg.id, research_run_id=run.id, price=Decimal("200")
    )
    await _seed_flight_card(
        db_session, leg_id=leg.id, research_run_id=run.id, price=Decimal("300")
    )
    await db_session.commit()

    # Pool: F100, F200, F300, T400, T800 — indices 0-2 budget, 3 comfort, 4 comfort
    # → T400 comfort, T800 comfort (not independently budget/budget).
    parsed = TransportResearchParsed(
        request_params={"research_type": "transport", "origin": "Phuket"},
        response_body={"research": {}, "extraction_attempts": []},
        options=[
            _priced(amount=Decimal("400"), departure="Pier A"),
            _unpriced(departure="Town square"),
            _priced(amount=Decimal("800"), departure="Pier B", operator="Another"),
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

    assert len(cards) == 3
    unpriced_cards = [c for c in cards if c.tier is None]
    priced_cards = sorted(
        [c for c in cards if c.tier is not None],
        key=lambda c: c.base_price_amount or Decimal(0),
    )
    assert len(unpriced_cards) == 1
    assert unpriced_cards[0].base_price_amount is None
    assert unpriced_cards[0].currency == "THB"
    assert len(priced_cards) == 2
    assert priced_cards[0].base_price_amount == Decimal("400")
    assert priced_cards[0].tier == BudgetBand.comfort
    assert priced_cards[1].base_price_amount == Decimal("800")
    assert priced_cards[1].tier == BudgetBand.comfort
    assert all(c.option_type == OptionType.transport for c in cards)

    detail = (
        await db_session.execute(
            select(TransportOption).where(
                TransportOption.option_card_id.in_([c.id for c in cards])
            )
        )
    ).scalars().all()
    assert len(detail) == 3
    assert {d.mode for d in detail} == {TransportMode.ferry, TransportMode.private_van}

    citations = (
        await db_session.execute(
            select(Citation).where(Citation.option_card_id.in_([c.id for c in cards]))
        )
    ).scalars().all()
    assert len(citations) == 3

    transport_raw = (
        await db_session.execute(
            select(RawApiResponse).where(
                RawApiResponse.research_run_id == run.id,
                RawApiResponse.source == RawApiSource.claude_web_search,
            )
        )
    ).scalars().all()
    assert len(transport_raw) == 1
    assert transport_raw[0].request_params.get("research_type") == "transport"


@pytest.mark.asyncio
async def test_persist_unpriced_only_skips_flight_pool_query(
    db_session: AsyncSession,
) -> None:
    leg, run = await _seed_leg(db_session)
    await db_session.commit()

    parsed = TransportResearchParsed(
        request_params={"research_type": "transport"},
        response_body={"research": {}, "extraction_attempts": []},
        options=[_unpriced()],
        extraction_failed=False,
        extraction_error=None,
    )

    with patch(
        "services.combined_tiering.load_active_priced_option_cards",
        new_callable=AsyncMock,
    ) as mock_flights:
        cards = await persist_transport_research(
            db_session,
            leg_id=leg.id,
            parsed=parsed,
            research_run_id=run.id,
            trace_id=run.trace_id,
        )
        mock_flights.assert_not_awaited()

    assert len(cards) == 1
    assert cards[0].tier is None
    assert cards[0].base_price_amount is None


@pytest.mark.asyncio
async def test_persist_drops_zero_citation_regardless_of_price(
    db_session: AsyncSession,
) -> None:
    leg, run = await _seed_leg(db_session)
    await db_session.commit()

    no_cite_priced = ParsedTransportOption(
        mode="ferry",
        operator_name=None,
        departure_point="A",
        arrival_point="B",
        estimated_duration_minutes=None,
        estimated_price_amount=Decimal("200"),
        estimated_price_currency="THB",
        booking_url=None,
        citations=[],
    )
    no_cite_unpriced = ParsedTransportOption(
        mode="bus",
        operator_name=None,
        departure_point="C",
        arrival_point="D",
        estimated_duration_minutes=None,
        estimated_price_amount=None,
        estimated_price_currency=None,
        booking_url=None,
        citations=[],
    )
    parsed = TransportResearchParsed(
        request_params={"research_type": "transport"},
        response_body={"research": {}, "extraction_attempts": []},
        options=[no_cite_priced, no_cite_unpriced, _priced(amount=Decimal("350"))],
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
    assert len(cards) == 1
    assert cards[0].base_price_amount == Decimal("350")
    assert cards[0].tier is not None
