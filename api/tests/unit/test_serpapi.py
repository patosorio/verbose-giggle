import json
import logging
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from research.serpapi import (
    SerpApiError,
    fetch_flight_booking_options,
    parse_flight_booking_sources,
    parse_flight_options,
    parse_hotel_booking_sources,
    parse_hotel_options,
    search_flights,
    search_hotels,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "serpapi"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.asyncio
async def test_retry_backs_off_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("research.serpapi.settings.serpapi_key", "test-key")
    monkeypatch.setattr("research.serpapi.settings.serpapi_max_retries", 3)
    monkeypatch.setattr(
        "research.serpapi.settings.serpapi_backoff_seconds",
        (0.5, 1.0, 2.0),
    )

    body = _load("flights_search.json")
    responses = [
        httpx.Response(429, request=httpx.Request("GET", "https://serpapi.com/search")),
        httpx.Response(429, request=httpx.Request("GET", "https://serpapi.com/search")),
        httpx.Response(
            200,
            json=body,
            request=httpx.Request("GET", "https://serpapi.com/search"),
        ),
    ]
    sleep_mock = AsyncMock()
    get_mock = AsyncMock(side_effect=responses)

    mock_client = MagicMock()
    mock_client.get = get_mock
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("research.serpapi.httpx.AsyncClient", return_value=mock_client),
        patch("research.serpapi.asyncio.sleep", sleep_mock),
    ):
        result = await search_flights(
            departure_id="BKK",
            arrival_id="HKT",
            outbound_date=date(2026, 11, 10),
            currency="THB",
            adults=6,
            children=1,
            leg_id=uuid4(),
        )

    assert len(result.flights) == 10
    assert get_mock.await_count == 3
    assert [call.args[0] for call in sleep_mock.await_args_list] == [0.5, 1.0]


@pytest.mark.asyncio
async def test_retry_exhaustion_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("research.serpapi.settings.serpapi_key", "test-key")
    monkeypatch.setattr("research.serpapi.settings.serpapi_max_retries", 3)
    monkeypatch.setattr(
        "research.serpapi.settings.serpapi_backoff_seconds",
        (0.5, 1.0, 2.0),
    )

    responses = [
        httpx.Response(503, request=httpx.Request("GET", "https://serpapi.com/search"))
        for _ in range(4)
    ]
    sleep_mock = AsyncMock()
    get_mock = AsyncMock(side_effect=responses)
    mock_client = MagicMock()
    mock_client.get = get_mock
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("research.serpapi.httpx.AsyncClient", return_value=mock_client),
        patch("research.serpapi.asyncio.sleep", sleep_mock),
        pytest.raises(SerpApiError, match="503"),
    ):
        await search_flights(
            departure_id="BKK",
            arrival_id="HKT",
            outbound_date=date(2026, 11, 10),
            currency="THB",
            adults=2,
        )

    assert get_mock.await_count == 4
    assert [call.args[0] for call in sleep_mock.await_args_list] == [0.5, 1.0, 2.0]


@pytest.mark.asyncio
async def test_currency_mismatch_is_logged_not_converted(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr("research.serpapi.settings.serpapi_key", "test-key")
    body = _load("flights_search.json")
    body["search_parameters"]["currency"] = "USD"

    mock_client = MagicMock()
    mock_client.get = AsyncMock(
        return_value=httpx.Response(
            200,
            json=body,
            request=httpx.Request("GET", "https://serpapi.com/search"),
        )
    )
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("research.serpapi.httpx.AsyncClient", return_value=mock_client),
        caplog.at_level(logging.WARNING, logger="research.serpapi"),
    ):
        result = await search_flights(
            departure_id="BKK",
            arrival_id="HKT",
            outbound_date=date(2026, 11, 10),
            currency="THB",
            adults=6,
            children=1,
        )

    assert result.currency_mismatched is True
    assert result.response_currency == "USD"
    assert result.requested_currency == "THB"
    assert all(flight.currency == "USD" for flight in result.flights)
    assert "serpapi_currency_mismatch" in caplog.text
    assert "requested=THB" in caplog.text
    assert "response=USD" in caplog.text


def test_parse_flight_booking_keeps_post_data() -> None:
    body = _load("flights_booking.json")
    sources = parse_flight_booking_sources(body, currency="THB")
    assert len(sources) == 3
    post_backed = [s for s in sources if s.booking_post_data is not None]
    plain = [s for s in sources if s.booking_post_data is None]
    assert len(post_backed) == 2
    assert post_backed[0].booking_post_data == {"post_data": "u=fixture-post-body-thai-airways"}
    assert plain[0].seller_name == "Kayak"
    assert plain[0].deep_link_url.startswith("https://www.kayak.com/")


def test_parse_hotel_property_sources() -> None:
    body = _load("hotels_property.json")
    sources = parse_hotel_booking_sources(body, currency="THB")
    assert len(sources) == 3
    assert all(s.booking_post_data is None for s in sources)
    assert {s.seller_name for s in sources} == {"Booking.com", "Hotels.com", "Agoda"}


def test_parse_hotels_uses_total_rate() -> None:
    body = _load("hotels_search.json")
    hotels = parse_hotel_options(
        body,
        currency="THB",
        checkin_date=date(2026, 11, 10),
        checkout_date=date(2026, 11, 14),
    )
    assert len(hotels) == 9
    assert min(h.price_amount for h in hotels) == 3900
    assert all(h.property_token for h in hotels)


@pytest.mark.asyncio
async def test_fetch_booking_options_cost_log(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr("research.serpapi.settings.serpapi_key", "test-key")
    body = _load("flights_booking.json")
    mock_client = MagicMock()
    mock_client.get = AsyncMock(
        return_value=httpx.Response(
            200,
            json=body,
            request=httpx.Request("GET", "https://serpapi.com/search"),
        )
    )
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    leg_id = uuid4()

    with (
        patch("research.serpapi.httpx.AsyncClient", return_value=mock_client),
        caplog.at_level(logging.INFO, logger="research.serpapi"),
    ):
        await fetch_flight_booking_options(
            booking_token="token-flight-01",
            currency="THB",
            leg_id=leg_id,
        )

    assert "serpapi_call" in caplog.text
    assert "endpoint=flights_booking" in caplog.text
    assert str(leg_id) in caplog.text


@pytest.mark.asyncio
async def test_hotel_search_requires_children_ages() -> None:
    with pytest.raises(ValueError, match="children_ages"):
        await search_hotels(
            q="Phuket hotels",
            check_in_date=date(2026, 11, 10),
            check_out_date=date(2026, 11, 11),
            currency="THB",
            adults=5,
            children=1,
        )


@pytest.mark.asyncio
async def test_hotel_search_rejects_party_over_six() -> None:
    with pytest.raises(ValueError, match="at most 6 travelers"):
        await search_hotels(
            q="Phuket hotels",
            check_in_date=date(2026, 11, 10),
            check_out_date=date(2026, 11, 11),
            currency="THB",
            adults=6,
            children=1,
            children_ages=[8],
        )


def test_parse_flights_skips_rows_without_booking_token() -> None:
    body = {
        "best_flights": [
            {
                "flights": [
                    {
                        "departure_airport": {
                            "name": "A",
                            "id": "BKK",
                            "time": "2026-11-10 07:00",
                        },
                        "arrival_airport": {
                            "name": "B",
                            "id": "HKT",
                            "time": "2026-11-10 08:20",
                        },
                        "duration": 80,
                        "airline": "X",
                    }
                ],
                "total_duration": 80,
                "price": 1000,
                "departure_token": "only-departure",
            }
        ]
    }
    assert parse_flight_options(body, currency="THB") == []
