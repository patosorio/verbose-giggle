"""Phase 5 Prompt 2 — booking sources lazy-fetch + citations read."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    BookingSource,
    BudgetBand,
    Citation,
    FlightOption,
    HotelOption,
    OptionCard,
    OptionType,
    RawApiResponse,
    RawApiSource,
)
from research.types import BookingSourcesParsed, ParsedBookingSource
from services import options as options_service


class _TokenEmailSender(Protocol):
    @property
    def last_token(self) -> str: ...


async def _login_as(client: AsyncClient, email_sender: _TokenEmailSender, email: str) -> None:
    request_response = await client.post(
        "/auth/magic-link/request",
        json={"email": email},
    )
    assert request_response.status_code == 202
    verify_response = await client.post(
        "/auth/magic-link/verify",
        json={"token": email_sender.last_token},
    )
    assert verify_response.status_code == 200


async def _create_trip_with_leg(client: AsyncClient, *, name: str) -> tuple[str, str]:
    trip_response = await client.post(
        "/trips",
        json={"name": name, "home_currency": "THB", "budget_band": "comfort"},
    )
    assert trip_response.status_code == 201
    trip_id = trip_response.json()["id"]
    legs_response = await client.post(
        f"/trips/{trip_id}/legs:bulk",
        json={
            "legs": [
                {
                    "sequence_index": 0,
                    "origin": "Bangkok",
                    "destination": "Phuket",
                    "start_date": date(2026, 11, 10).isoformat(),
                    "end_date": date(2026, 11, 11).isoformat(),
                    "filters": {"flight": {}, "hotel": {}},
                }
            ]
        },
    )
    assert legs_response.status_code == 201
    return trip_id, legs_response.json()[0]["id"]


async def _seed_raw(db_session: AsyncSession) -> RawApiResponse:
    raw = RawApiResponse(
        research_run_id=None,
        source=RawApiSource.serpapi_flights_search,
        request_params={},
        response_body={},
        fetched_at=datetime.now(UTC),
    )
    db_session.add(raw)
    await db_session.flush()
    return raw


async def _seed_flight_card(
    db_session: AsyncSession,
    *,
    leg_id: str | UUID,
    title: str = "Seed Flight",
) -> OptionCard:
    raw = await _seed_raw(db_session)
    card = OptionCard(
        leg_id=leg_id,
        option_type=OptionType.flight,
        tier=BudgetBand.budget,
        title=title,
        base_price_amount=Decimal("1500.00"),
        currency="THB",
        raw_response_id=raw.id,
    )
    db_session.add(card)
    await db_session.flush()
    db_session.add(
        FlightOption(
            option_card_id=card.id,
            booking_token="flight-token-abc",
            departure_airport="BKK",
            arrival_airport="HKT",
            departure_time=datetime(2026, 11, 10, 8, 0, tzinfo=UTC),
            arrival_time=datetime(2026, 11, 10, 9, 30, tzinfo=UTC),
            duration_minutes=90,
            stops=0,
            airlines=["TG"],
            layovers=[],
            bags_included=True,
            emissions_grams=None,
        )
    )
    await db_session.commit()
    await db_session.refresh(card)
    return card


async def _seed_hotel_card(
    db_session: AsyncSession,
    *,
    leg_id: str | UUID,
    title: str = "Seed Hotel",
) -> OptionCard:
    raw = await _seed_raw(db_session)
    card = OptionCard(
        leg_id=leg_id,
        option_type=OptionType.hotel,
        tier=BudgetBand.comfort,
        title=title,
        base_price_amount=Decimal("3200.00"),
        currency="THB",
        raw_response_id=raw.id,
    )
    db_session.add(card)
    await db_session.flush()
    db_session.add(
        HotelOption(
            option_card_id=card.id,
            property_token="hotel-token-xyz",
            name=title,
            star_rating=Decimal("4.0"),
            gps_lat=Decimal("7.8804"),
            gps_lng=Decimal("98.3923"),
            checkin_date=date(2026, 11, 10),
            checkout_date=date(2026, 11, 11),
            free_cancellation=True,
            eco_certified=False,
            amenities=["wifi"],
        )
    )
    await db_session.commit()
    await db_session.refresh(card)
    return card


async def _seed_typed_card(
    db_session: AsyncSession,
    *,
    leg_id: str | UUID,
    option_type: OptionType,
    title: str,
) -> OptionCard:
    raw = await _seed_raw(db_session)
    card = OptionCard(
        leg_id=leg_id,
        option_type=option_type,
        tier=BudgetBand.budget if option_type != OptionType.transport else None,
        title=title,
        base_price_amount=Decimal("500.00"),
        currency="THB",
        raw_response_id=raw.id,
    )
    db_session.add(card)
    await db_session.commit()
    await db_session.refresh(card)
    return card


def _parsed_sources(*, endpoint: str) -> BookingSourcesParsed:
    return BookingSourcesParsed(
        engine="google_flights" if endpoint == "flights_booking" else "google_hotels",
        endpoint=endpoint,
        request_params={"engine": "mock"},
        response_body={},
        requested_currency="THB",
        response_currency="THB",
        currency_mismatched=False,
        sources=[
            ParsedBookingSource(
                seller_name="Mock OTA",
                price_amount=Decimal("1500.00"),
                currency="THB",
                deep_link_url="https://example.com/book",
                booking_post_data=None,
            )
        ],
    )


@pytest.mark.asyncio
async def test_sources_cache_hit_skips_serpapi(
    client: AsyncClient,
    email_sender: _TokenEmailSender,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _login_as(client, email_sender, "sources-cache@example.com")
    _, leg_id = await _create_trip_with_leg(client, name="Sources Cache Trip")
    card = await _seed_flight_card(db_session, leg_id=leg_id)

    raw = await _seed_raw(db_session)
    now = datetime.now(UTC)
    db_session.add(
        BookingSource(
            option_card_id=card.id,
            seller_name="Cached OTA",
            price_amount=Decimal("1400.00"),
            currency="THB",
            deep_link_url="https://example.com/cached",
            booking_post_data=None,
            raw_response_id=raw.id,
            fetched_at=now,
            ttl_expires_at=now + timedelta(hours=1),
        )
    )
    await db_session.commit()

    flight_fetch = AsyncMock(side_effect=AssertionError("flight fetch should not run"))
    hotel_fetch = AsyncMock(side_effect=AssertionError("hotel fetch should not run"))
    monkeypatch.setattr(options_service, "fetch_flight_booking_options", flight_fetch)
    monkeypatch.setattr(options_service, "fetch_hotel_property_details", hotel_fetch)

    response = await client.get(f"/options/{card.id}/sources")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["seller_name"] == "Cached OTA"
    flight_fetch.assert_not_called()
    hotel_fetch.assert_not_called()


@pytest.mark.asyncio
async def test_sources_cache_miss_fetches_flight(
    client: AsyncClient,
    email_sender: _TokenEmailSender,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _login_as(client, email_sender, "sources-flight@example.com")
    _, leg_id = await _create_trip_with_leg(client, name="Sources Flight Trip")
    card = await _seed_flight_card(db_session, leg_id=leg_id)

    flight_fetch = AsyncMock(return_value=_parsed_sources(endpoint="flights_booking"))
    hotel_fetch = AsyncMock(side_effect=AssertionError("hotel fetch should not run"))
    monkeypatch.setattr(options_service, "fetch_flight_booking_options", flight_fetch)
    monkeypatch.setattr(options_service, "fetch_hotel_property_details", hotel_fetch)

    response = await client.get(f"/options/{card.id}/sources")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["seller_name"] == "Mock OTA"
    flight_fetch.assert_awaited_once()
    assert flight_fetch.await_args.kwargs["booking_token"] == "flight-token-abc"
    hotel_fetch.assert_not_called()


@pytest.mark.asyncio
async def test_sources_cache_miss_fetches_hotel(
    client: AsyncClient,
    email_sender: _TokenEmailSender,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _login_as(client, email_sender, "sources-hotel@example.com")
    _, leg_id = await _create_trip_with_leg(client, name="Sources Hotel Trip")
    card = await _seed_hotel_card(db_session, leg_id=leg_id)

    hotel_fetch = AsyncMock(return_value=_parsed_sources(endpoint="hotels_property"))
    flight_fetch = AsyncMock(side_effect=AssertionError("flight fetch should not run"))
    monkeypatch.setattr(options_service, "fetch_flight_booking_options", flight_fetch)
    monkeypatch.setattr(options_service, "fetch_hotel_property_details", hotel_fetch)

    response = await client.get(f"/options/{card.id}/sources")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["seller_name"] == "Mock OTA"
    hotel_fetch.assert_awaited_once()
    assert hotel_fetch.await_args.kwargs["property_token"] == "hotel-token-xyz"
    flight_fetch.assert_not_called()


@pytest.mark.asyncio
async def test_sources_404_for_activity_and_transport(
    client: AsyncClient,
    email_sender: _TokenEmailSender,
    db_session: AsyncSession,
) -> None:
    await _login_as(client, email_sender, "sources-404@example.com")
    _, leg_id = await _create_trip_with_leg(client, name="Sources 404 Trip")
    activity = await _seed_typed_card(
        db_session,
        leg_id=leg_id,
        option_type=OptionType.activity,
        title="Activity Card",
    )
    transport = await _seed_typed_card(
        db_session,
        leg_id=leg_id,
        option_type=OptionType.transport,
        title="Transport Card",
    )

    for card in (activity, transport):
        response = await client.get(f"/options/{card.id}/sources")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_citations_404_for_flight_and_hotel(
    client: AsyncClient,
    email_sender: _TokenEmailSender,
    db_session: AsyncSession,
) -> None:
    await _login_as(client, email_sender, "citations-404@example.com")
    _, leg_id = await _create_trip_with_leg(client, name="Citations 404 Trip")
    flight = await _seed_flight_card(db_session, leg_id=leg_id, title="No Cite Flight")
    hotel = await _seed_hotel_card(db_session, leg_id=leg_id, title="No Cite Hotel")

    for card in (flight, hotel):
        response = await client.get(f"/options/{card.id}/citations")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_citations_returns_ordered_rows_for_activity_and_transport(
    client: AsyncClient,
    email_sender: _TokenEmailSender,
    db_session: AsyncSession,
) -> None:
    await _login_as(client, email_sender, "citations-ok@example.com")
    _, leg_id = await _create_trip_with_leg(client, name="Citations OK Trip")
    activity = await _seed_typed_card(
        db_session,
        leg_id=leg_id,
        option_type=OptionType.activity,
        title="Cited Activity",
    )
    transport = await _seed_typed_card(
        db_session,
        leg_id=leg_id,
        option_type=OptionType.transport,
        title="Cited Transport",
    )

    earlier = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
    later = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
    db_session.add_all(
        [
            Citation(
                option_card_id=activity.id,
                claim_text="Later claim",
                source_url="https://example.com/later",
                retrieved_at=later,
            ),
            Citation(
                option_card_id=activity.id,
                claim_text="Earlier claim",
                source_url="https://example.com/earlier",
                retrieved_at=earlier,
            ),
            Citation(
                option_card_id=transport.id,
                claim_text="Ferry runs daily",
                source_url="https://example.com/ferry",
                retrieved_at=earlier,
            ),
        ]
    )
    await db_session.commit()

    activity_response = await client.get(f"/options/{activity.id}/citations")
    assert activity_response.status_code == 200
    activity_body = activity_response.json()
    assert [row["claim_text"] for row in activity_body] == [
        "Earlier claim",
        "Later claim",
    ]

    transport_response = await client.get(f"/options/{transport.id}/citations")
    assert transport_response.status_code == 200
    transport_body = transport_response.json()
    assert len(transport_body) == 1
    assert transport_body[0]["claim_text"] == "Ferry runs daily"
    assert transport_body[0]["source_url"] == "https://example.com/ferry"
