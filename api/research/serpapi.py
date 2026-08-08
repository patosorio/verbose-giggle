import asyncio
import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx

from core.config import settings
from core.errors import AppError
from research.types import (
    BookingSourcesParsed,
    FlightSearchParsed,
    HotelSearchParsed,
    ParsedBookingSource,
    ParsedFlightOption,
    ParsedHotelOption,
)

logger = logging.getLogger(__name__)
# Defense in depth: even if setup_logging wasn't called, don't INFO-log URLs with api_key.
logging.getLogger("httpx").setLevel(logging.WARNING)

_SERPAPI_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_FREE_CHECKED_BAG_RE = re.compile(r"checked\s+bag", re.IGNORECASE)


class SerpApiError(AppError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(502, "upstream_api_error", message, details=details)


def _public_params(params: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in params.items() if key != "api_key"}


def _response_currency(body: dict[str, object], requested: str) -> str:
    search_parameters = body.get("search_parameters")
    if isinstance(search_parameters, dict):
        echoed = search_parameters.get("currency")
        if isinstance(echoed, str) and echoed.strip():
            return echoed.strip().upper()
    return requested.upper()


def _warn_currency_mismatch(
    *,
    requested: str,
    response_currency: str,
    engine: str,
    endpoint: str,
    leg_id: UUID | None,
) -> bool:
    mismatched = requested.upper() != response_currency.upper()
    if mismatched:
        logger.warning(
            "serpapi_currency_mismatch engine=%s endpoint=%s leg_id=%s "
            "requested=%s response=%s — storing response currency as returned",
            engine,
            endpoint,
            leg_id,
            requested.upper(),
            response_currency.upper(),
        )
    return mismatched


def _parse_flight_datetime(value: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=None)
        except ValueError:
            continue
    # SerpApi sometimes includes an offset like "2023-12-05 07:15+01:00"
    cleaned = value.strip()
    if len(cleaned) >= 16 and cleaned[10] == " ":
        try:
            return datetime.fromisoformat(cleaned.replace(" ", "T", 1))
        except ValueError:
            pass
    raise SerpApiError(f"Unrecognized flight datetime format: {value!r}")


def _bags_included(flight_segments: list[dict[str, object]], extensions: list[object]) -> bool:
    texts: list[str] = []
    for segment in flight_segments:
        for item in segment.get("extensions") or []:
            if isinstance(item, str):
                texts.append(item)
    for item in extensions:
        if isinstance(item, str):
            texts.append(item)
    for text in texts:
        lower = text.lower()
        if _FREE_CHECKED_BAG_RE.search(text) and "fee" not in lower and "pay" not in lower:
            if "free" in lower or "included" in lower:
                return True
    return False


def _flight_title(airlines: list[str], departure_id: str, arrival_id: str, stops: int) -> str:
    airline_label = ", ".join(airlines) if airlines else "Flight"
    if stops == 0:
        stop_label = "nonstop"
    elif stops == 1:
        stop_label = "1 stop"
    else:
        stop_label = f"{stops} stops"
    return f"{airline_label} {departure_id}→{arrival_id} ({stop_label})"


def parse_flight_options(
    body: dict[str, object],
    *,
    currency: str,
) -> list[ParsedFlightOption]:
    rows: list[dict[str, object]] = []
    for key in ("best_flights", "other_flights"):
        chunk = body.get(key)
        if isinstance(chunk, list):
            rows.extend(item for item in chunk if isinstance(item, dict))

    parsed: list[ParsedFlightOption] = []
    for row in rows:
        booking_token = row.get("booking_token")
        price = row.get("price")
        segments = row.get("flights")
        if not isinstance(booking_token, str) or not booking_token:
            continue
        if not isinstance(price, (int, float)):
            continue
        if not isinstance(segments, list) or not segments:
            continue
        typed_segments = [s for s in segments if isinstance(s, dict)]
        if not typed_segments:
            continue

        first = typed_segments[0]
        last = typed_segments[-1]
        dep = first.get("departure_airport")
        arr = last.get("arrival_airport")
        if not isinstance(dep, dict) or not isinstance(arr, dict):
            continue
        dep_id = dep.get("id")
        arr_id = arr.get("id")
        dep_time = dep.get("time")
        arr_time = arr.get("time")
        if (
            not isinstance(dep_id, str)
            or not dep_id
            or not isinstance(arr_id, str)
            or not arr_id
            or not isinstance(dep_time, str)
            or not dep_time
            or not isinstance(arr_time, str)
            or not arr_time
        ):
            continue

        airlines = sorted(
            {
                str(segment["airline"])
                for segment in typed_segments
                if isinstance(segment.get("airline"), str)
            }
        )
        layovers_raw = row.get("layovers")
        layovers: list[dict[str, object]] = []
        if isinstance(layovers_raw, list):
            layovers = [item for item in layovers_raw if isinstance(item, dict)]

        duration = row.get("total_duration")
        if not isinstance(duration, int):
            duration = sum(
                int(segment["duration"])
                for segment in typed_segments
                if isinstance(segment.get("duration"), int)
            )

        emissions: int | None = None
        carbon = row.get("carbon_emissions")
        if isinstance(carbon, dict) and isinstance(carbon.get("this_flight"), int):
            emissions = carbon["this_flight"]

        extensions_raw = row.get("extensions")
        extensions: list[object] = extensions_raw if isinstance(extensions_raw, list) else []
        stops = max(len(typed_segments) - 1, 0)

        parsed.append(
            ParsedFlightOption(
                booking_token=booking_token,
                title=_flight_title(airlines, dep_id, arr_id, stops),
                price_amount=Decimal(str(price)),
                currency=currency,
                departure_airport=dep_id,
                arrival_airport=arr_id,
                departure_time=_parse_flight_datetime(dep_time),
                arrival_time=_parse_flight_datetime(arr_time),
                duration_minutes=duration,
                stops=stops,
                airlines=airlines,
                layovers=layovers,
                bags_included=_bags_included(typed_segments, extensions),
                emissions_grams=emissions,
            )
        )
    return parsed


def _hotel_star_rating(property_row: dict[str, object]) -> Decimal:
    extracted = property_row.get("extracted_hotel_class")
    if isinstance(extracted, (int, float)):
        return Decimal(str(extracted))
    hotel_class = property_row.get("hotel_class")
    if isinstance(hotel_class, (int, float)):
        return Decimal(str(hotel_class))
    if isinstance(hotel_class, str):
        match = re.search(r"(\d+(?:\.\d+)?)", hotel_class)
        if match:
            return Decimal(match.group(1))
    rating = property_row.get("overall_rating")
    if isinstance(rating, (int, float)):
        return Decimal(str(rating))
    return Decimal("0")


def _total_rate_amount(property_row: dict[str, object]) -> Decimal | None:
    total_rate = property_row.get("total_rate")
    if isinstance(total_rate, dict):
        extracted = total_rate.get("extracted_lowest")
        if isinstance(extracted, (int, float)):
            return Decimal(str(extracted))
    extracted_price = property_row.get("extracted_price")
    if isinstance(extracted_price, (int, float)):
        return Decimal(str(extracted_price))
    return None


def parse_hotel_options(
    body: dict[str, object],
    *,
    currency: str,
    checkin_date: date,
    checkout_date: date,
) -> list[ParsedHotelOption]:
    properties = body.get("properties")
    if not isinstance(properties, list):
        return []

    parsed: list[ParsedHotelOption] = []
    for row in properties:
        if not isinstance(row, dict):
            continue
        property_token = row.get("property_token")
        name = row.get("name")
        gps = row.get("gps_coordinates")
        if not isinstance(property_token, str) or not property_token:
            continue
        if not isinstance(name, str) or not name:
            continue
        if not isinstance(gps, dict):
            continue
        lat = gps.get("latitude")
        lng = gps.get("longitude")
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            continue
        price_amount = _total_rate_amount(row)
        if price_amount is None:
            continue

        amenities_raw = row.get("amenities")
        amenities = (
            [item for item in amenities_raw if isinstance(item, str)]
            if isinstance(amenities_raw, list)
            else []
        )

        parsed.append(
            ParsedHotelOption(
                property_token=property_token,
                name=name,
                title=name,
                price_amount=price_amount,
                currency=currency,
                star_rating=_hotel_star_rating(row),
                gps_lat=Decimal(str(lat)),
                gps_lng=Decimal(str(lng)),
                checkin_date=checkin_date,
                checkout_date=checkout_date,
                free_cancellation=bool(row.get("free_cancellation")),
                eco_certified=bool(row.get("eco_certified")),
                amenities=amenities,
            )
        )
    return parsed


def _booking_post_payload(booking_request: dict[str, object]) -> dict[str, object] | None:
    post_data = booking_request.get("post_data")
    if isinstance(post_data, str) and post_data:
        return {"post_data": post_data}
    return None


def _parse_together_booking(
    together: dict[str, object],
    *,
    currency: str,
) -> ParsedBookingSource | None:
    seller = together.get("book_with")
    price = together.get("price")
    if not isinstance(seller, str) or not seller:
        return None
    if not isinstance(price, (int, float)):
        return None

    deep_link: str | None = None
    post_payload: dict[str, object] | None = None

    booking_request = together.get("booking_request")
    if isinstance(booking_request, dict):
        url = booking_request.get("url")
        if isinstance(url, str) and url:
            deep_link = url
            post_payload = _booking_post_payload(booking_request)

    if deep_link is None:
        link = together.get("link")
        if isinstance(link, str) and link:
            deep_link = link

    if deep_link is None:
        return None

    return ParsedBookingSource(
        seller_name=seller,
        price_amount=Decimal(str(price)),
        currency=currency,
        deep_link_url=deep_link,
        booking_post_data=post_payload,
    )


def parse_flight_booking_sources(
    body: dict[str, object],
    *,
    currency: str,
) -> list[ParsedBookingSource]:
    options = body.get("booking_options")
    if not isinstance(options, list):
        return []

    parsed: list[ParsedBookingSource] = []
    for option in options:
        if not isinstance(option, dict):
            continue
        together = option.get("together")
        if isinstance(together, dict):
            source = _parse_together_booking(together, currency=currency)
            if source is not None:
                parsed.append(source)
            continue
        # Some responses flatten a single seller onto the option object itself.
        source = _parse_together_booking(option, currency=currency)
        if source is not None:
            parsed.append(source)
    return parsed


def parse_hotel_booking_sources(
    body: dict[str, object],
    *,
    currency: str,
) -> list[ParsedBookingSource]:
    prices = body.get("prices")
    if not isinstance(prices, list):
        prices = []
    featured = body.get("featured_prices")
    if isinstance(featured, list):
        prices = [*prices, *featured]

    parsed: list[ParsedBookingSource] = []
    seen: set[tuple[str, str, str]] = set()
    for row in prices:
        if not isinstance(row, dict):
            continue
        seller = row.get("source")
        link = row.get("link")
        if not isinstance(seller, str) or not seller:
            continue
        if not isinstance(link, str) or not link:
            continue
        amount = _total_rate_amount(row)
        if amount is None:
            rate = row.get("rate_per_night")
            if isinstance(rate, dict) and isinstance(rate.get("extracted_lowest"), (int, float)):
                amount = Decimal(str(rate["extracted_lowest"]))
        if amount is None:
            continue
        key = (seller, str(amount), link)
        if key in seen:
            continue
        seen.add(key)
        parsed.append(
            ParsedBookingSource(
                seller_name=seller,
                price_amount=amount,
                currency=currency,
                deep_link_url=link,
                booking_post_data=None,
            )
        )
    return parsed


async def _serpapi_get(
    params: dict[str, object],
    *,
    engine: str,
    endpoint: str,
    leg_id: UUID | None,
) -> dict[str, object]:
    if not settings.serpapi_key:
        raise SerpApiError("SERPAPI_KEY is not configured")

    full_params = {**params, "api_key": settings.serpapi_key, "engine": engine}
    max_retries = settings.serpapi_max_retries
    backoffs = settings.serpapi_backoff_seconds
    attempt = 0

    async with httpx.AsyncClient(timeout=60.0) as client:
        while True:
            attempt += 1
            logger.info(
                "serpapi_call engine=%s endpoint=%s leg_id=%s attempt=%s",
                engine,
                endpoint,
                leg_id,
                attempt,
            )
            try:
                response = await client.get(settings.serpapi_base_url, params=full_params)
            except httpx.HTTPError as exc:
                if attempt > max_retries:
                    raise SerpApiError(
                        f"SerpApi transport error after {attempt} attempts: {exc}",
                        details={"engine": engine, "endpoint": endpoint},
                    ) from exc
                delay = backoffs[min(attempt - 1, len(backoffs) - 1)]
                logger.warning(
                    "serpapi_retry engine=%s endpoint=%s leg_id=%s attempt=%s "
                    "reason=transport error=%s sleep=%s",
                    engine,
                    endpoint,
                    leg_id,
                    attempt,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            if response.status_code in _SERPAPI_RETRY_STATUSES:
                if attempt > max_retries:
                    raise SerpApiError(
                        f"SerpApi returned {response.status_code} after {attempt} attempts",
                        details={
                            "engine": engine,
                            "endpoint": endpoint,
                            "status_code": response.status_code,
                        },
                    )
                delay = backoffs[min(attempt - 1, len(backoffs) - 1)]
                logger.warning(
                    "serpapi_retry engine=%s endpoint=%s leg_id=%s attempt=%s "
                    "status=%s sleep=%s",
                    engine,
                    endpoint,
                    leg_id,
                    attempt,
                    response.status_code,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            if response.status_code >= 400:
                body_preview = response.text[:500]
                raise SerpApiError(
                    f"SerpApi returned HTTP {response.status_code}: {body_preview}",
                    details={
                        "engine": engine,
                        "endpoint": endpoint,
                        "status_code": response.status_code,
                        "body": body_preview,
                    },
                )

            try:
                body = response.json()
            except ValueError as exc:
                raise SerpApiError(
                    "SerpApi returned non-JSON body",
                    details={"engine": engine, "endpoint": endpoint},
                ) from exc

            if not isinstance(body, dict):
                raise SerpApiError(
                    "SerpApi JSON root was not an object",
                    details={"engine": engine, "endpoint": endpoint},
                )

            error = body.get("error")
            if isinstance(error, str) and error:
                raise SerpApiError(
                    error,
                    details={"engine": engine, "endpoint": endpoint},
                )

            return body


async def search_flights(
    *,
    departure_id: str,
    arrival_id: str,
    outbound_date: date,
    currency: str,
    adults: int,
    children: int = 0,
    leg_id: UUID | None = None,
    flight_type: int = 2,
    hl: str = "en",
) -> FlightSearchParsed:
    """One-way google_flights search. `flight_type` defaults to 2 (one way)."""
    params: dict[str, object] = {
        "departure_id": departure_id,
        "arrival_id": arrival_id,
        "outbound_date": outbound_date.isoformat(),
        "currency": currency.upper(),
        "adults": adults,
        "children": children,
        "type": flight_type,
        "hl": hl,
    }
    body = await _serpapi_get(
        params,
        engine="google_flights",
        endpoint="flights_search",
        leg_id=leg_id,
    )
    response_currency = _response_currency(body, currency)
    mismatched = _warn_currency_mismatch(
        requested=currency,
        response_currency=response_currency,
        engine="google_flights",
        endpoint="flights_search",
        leg_id=leg_id,
    )
    flights = parse_flight_options(body, currency=response_currency)
    return FlightSearchParsed(
        engine="google_flights",
        endpoint="flights_search",
        request_params=_public_params({**params, "engine": "google_flights"}),
        response_body=body,
        requested_currency=currency.upper(),
        response_currency=response_currency,
        currency_mismatched=mismatched,
        flights=flights,
    )


async def fetch_flight_booking_options(
    *,
    booking_token: str,
    currency: str,
    leg_id: UUID | None = None,
    departure_id: str | None = None,
    arrival_id: str | None = None,
    outbound_date: date | None = None,
    adults: int | None = None,
    children: int | None = None,
    hl: str = "en",
) -> BookingSourcesParsed:
    """Lazy google_flights booking-options call (paid per item)."""
    params: dict[str, object] = {
        "booking_token": booking_token,
        "currency": currency.upper(),
        "hl": hl,
        "type": 2,
    }
    if departure_id is not None:
        params["departure_id"] = departure_id
    if arrival_id is not None:
        params["arrival_id"] = arrival_id
    if outbound_date is not None:
        params["outbound_date"] = outbound_date.isoformat()
    if adults is not None:
        params["adults"] = adults
    if children is not None:
        params["children"] = children

    body = await _serpapi_get(
        params,
        engine="google_flights",
        endpoint="flights_booking",
        leg_id=leg_id,
    )
    response_currency = _response_currency(body, currency)
    mismatched = _warn_currency_mismatch(
        requested=currency,
        response_currency=response_currency,
        engine="google_flights",
        endpoint="flights_booking",
        leg_id=leg_id,
    )
    sources = parse_flight_booking_sources(body, currency=response_currency)
    return BookingSourcesParsed(
        engine="google_flights",
        endpoint="flights_booking",
        request_params=_public_params({**params, "engine": "google_flights"}),
        response_body=body,
        requested_currency=currency.upper(),
        response_currency=response_currency,
        currency_mismatched=mismatched,
        sources=sources,
    )


def _hotel_guest_params(
    *,
    adults: int,
    children: int,
    children_ages: list[int] | None,
) -> dict[str, object]:
    """Build adults/children/children_ages. SerpApi requires ages when children > 0.

    google_hotels rejects parties larger than 6 total travelers
    (`adults + children`); fail fast rather than round-trip a 400.
    """
    total = adults + children
    if total > 6:
        raise ValueError(
            "google_hotels allows at most 6 travelers total "
            f"(got adults={adults} + children={children} = {total})"
        )
    params: dict[str, object] = {"adults": adults, "children": children}
    if children > 0:
        if children_ages is None or len(children_ages) != children:
            raise ValueError(
                "google_hotels requires children_ages with one age (1–17) per child "
                f"(children={children}, ages={children_ages!r})"
            )
        params["children_ages"] = ",".join(str(age) for age in children_ages)
    return params


async def search_hotels(
    *,
    q: str,
    check_in_date: date,
    check_out_date: date,
    currency: str,
    adults: int,
    children: int = 0,
    children_ages: list[int] | None = None,
    leg_id: UUID | None = None,
    hl: str = "en",
    gl: str = "us",
) -> HotelSearchParsed:
    params: dict[str, object] = {
        "q": q,
        "check_in_date": check_in_date.isoformat(),
        "check_out_date": check_out_date.isoformat(),
        "currency": currency.upper(),
        "hl": hl,
        "gl": gl,
        **_hotel_guest_params(
            adults=adults,
            children=children,
            children_ages=children_ages,
        ),
    }
    body = await _serpapi_get(
        params,
        engine="google_hotels",
        endpoint="hotels_search",
        leg_id=leg_id,
    )
    response_currency = _response_currency(body, currency)
    mismatched = _warn_currency_mismatch(
        requested=currency,
        response_currency=response_currency,
        engine="google_hotels",
        endpoint="hotels_search",
        leg_id=leg_id,
    )
    hotels = parse_hotel_options(
        body,
        currency=response_currency,
        checkin_date=check_in_date,
        checkout_date=check_out_date,
    )
    return HotelSearchParsed(
        engine="google_hotels",
        endpoint="hotels_search",
        request_params=_public_params({**params, "engine": "google_hotels"}),
        response_body=body,
        requested_currency=currency.upper(),
        response_currency=response_currency,
        currency_mismatched=mismatched,
        hotels=hotels,
    )


async def fetch_hotel_property_details(
    *,
    property_token: str,
    check_in_date: date,
    check_out_date: date,
    currency: str,
    adults: int,
    children: int = 0,
    children_ages: list[int] | None = None,
    q: str | None = None,
    leg_id: UUID | None = None,
    hl: str = "en",
    gl: str = "us",
) -> BookingSourcesParsed:
    """Lazy google_hotels Property Details call (paid per item)."""
    params: dict[str, object] = {
        "property_token": property_token,
        "check_in_date": check_in_date.isoformat(),
        "check_out_date": check_out_date.isoformat(),
        "currency": currency.upper(),
        "hl": hl,
        "gl": gl,
        **_hotel_guest_params(
            adults=adults,
            children=children,
            children_ages=children_ages,
        ),
    }
    if q is not None:
        params["q"] = q

    body = await _serpapi_get(
        params,
        engine="google_hotels",
        endpoint="hotels_property",
        leg_id=leg_id,
    )
    response_currency = _response_currency(body, currency)
    mismatched = _warn_currency_mismatch(
        requested=currency,
        response_currency=response_currency,
        engine="google_hotels",
        endpoint="hotels_property",
        leg_id=leg_id,
    )
    sources = parse_hotel_booking_sources(body, currency=response_currency)
    return BookingSourcesParsed(
        engine="google_hotels",
        endpoint="hotels_property",
        request_params=_public_params({**params, "engine": "google_hotels"}),
        response_body=body,
        requested_currency=currency.upper(),
        response_currency=response_currency,
        currency_mismatched=mismatched,
        sources=sources,
    )
