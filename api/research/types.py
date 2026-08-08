from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum

logger = logging.getLogger(__name__)

# "-"- or "to"-separated numeric range after commas stripped (docs/04_build_plan.md Phase 3).
_PRICE_RANGE_TO_RE = re.compile(
    r"^\s*(?P<low>\d+(?:\.\d+)?)\s+to\s+(?P<high>\d+(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)
_PRICE_RANGE_HYPHEN_RE = re.compile(
    r"^\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*$",
)


def _midpoint_from_price_range(raw: str) -> Decimal | None:
    """Return midpoint for a '-'/to range string, else None (not a coercible range)."""
    cleaned = raw.replace(",", "").strip()
    match = _PRICE_RANGE_TO_RE.match(cleaned) or _PRICE_RANGE_HYPHEN_RE.match(cleaned)
    if match is None:
        return None
    low = Decimal(match.group("low"))
    high = Decimal(match.group("high"))
    return (low + high) / Decimal(2)


def coerce_estimated_price_amount(value: object) -> Decimal | None:
    """Coerce estimated_price_amount: null passes; numbers pass; '-'/'to' ranges → midpoint.

    docs/04_build_plan.md Phase 3 — price-range/malformed-price coercion.
    Shared by activities and transport emit schemas (docs/02_data_model.md TransportOption).
    A null/absent price returns None and is not coerced or dropped.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError(f"invalid estimated_price_amount: {value!r}")
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if not isinstance(value, str):
        raise ValueError(f"invalid estimated_price_amount: {value!r}")

    raw = value.strip()
    if raw == "":
        raise ValueError(f"invalid estimated_price_amount: {value!r}")

    midpoint = _midpoint_from_price_range(raw)
    if midpoint is not None:
        logger.info("price range coerced: %r -> %s", raw, midpoint)
        return midpoint

    try:
        return Decimal(raw)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"invalid estimated_price_amount: {value!r}") from exc


class SuggestedTiming(StrEnum):
    """Transient extraction signal for same-day-transfer checks — not an ActivityOption column."""

    arrival_day = "arrival_day"
    departure_day = "departure_day"
    flexible = "flexible"


@dataclass(frozen=True, slots=True)
class ParsedCitation:
    claim_text: str
    source_url: str


@dataclass(frozen=True, slots=True)
class ParsedActivityOption:
    title: str
    category: str
    description: str
    duration_minutes: int | None
    estimated_price_amount: Decimal
    estimated_price_currency: str
    citations: list[ParsedCitation]
    suggested_timing: SuggestedTiming

    @property
    def price_amount(self) -> Decimal:
        """Alias for assign_price_tiers (docs/01_architecture.md §4.1)."""
        return self.estimated_price_amount


@dataclass(frozen=True, slots=True)
class ParsedTransportOption:
    mode: str
    operator_name: str | None
    departure_point: str
    arrival_point: str
    estimated_duration_minutes: int | None
    estimated_price_amount: Decimal | None
    estimated_price_currency: str | None
    booking_url: str | None
    citations: list[ParsedCitation]

    @property
    def price_amount(self) -> Decimal:
        """Alias for assign_price_tiers — only call when estimated_price_amount is set."""
        if self.estimated_price_amount is None:
            raise ValueError("unpriced transport option has no price_amount")
        return self.estimated_price_amount


@dataclass(frozen=True, slots=True)
class ParsedFlightOption:
    booking_token: str
    title: str
    price_amount: Decimal
    currency: str
    departure_airport: str
    arrival_airport: str
    departure_time: datetime
    arrival_time: datetime
    duration_minutes: int
    stops: int
    airlines: list[str]
    layovers: list[dict[str, object]]
    bags_included: bool
    emissions_grams: int | None


@dataclass(frozen=True, slots=True)
class ParsedHotelOption:
    property_token: str
    name: str
    title: str
    price_amount: Decimal
    currency: str
    star_rating: Decimal
    gps_lat: Decimal
    gps_lng: Decimal
    checkin_date: date
    checkout_date: date
    free_cancellation: bool
    eco_certified: bool
    amenities: list[str]


@dataclass(frozen=True, slots=True)
class ParsedBookingSource:
    seller_name: str
    price_amount: Decimal
    currency: str
    deep_link_url: str
    booking_post_data: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class SerpApiRawResult:
    engine: str
    endpoint: str
    request_params: dict[str, object]
    response_body: dict[str, object]
    requested_currency: str
    response_currency: str
    currency_mismatched: bool


@dataclass(frozen=True, slots=True)
class FlightSearchParsed(SerpApiRawResult):
    flights: list[ParsedFlightOption]


@dataclass(frozen=True, slots=True)
class HotelSearchParsed(SerpApiRawResult):
    hotels: list[ParsedHotelOption]


@dataclass(frozen=True, slots=True)
class BookingSourcesParsed(SerpApiRawResult):
    sources: list[ParsedBookingSource]


@dataclass(frozen=True, slots=True)
class ActivitiesResearchParsed:
    """Raw Claude research+extraction payload plus schema-valid activities.

    research/ never writes to the DB. response_body always holds both call outputs
    (docs/01_architecture.md §4.1 / §5) so services can persist RawApiResponse first.
    """

    request_params: dict[str, object]
    response_body: dict[str, object]
    activities: list[ParsedActivityOption]
    extraction_failed: bool
    extraction_error: str | None


@dataclass(frozen=True, slots=True)
class TransportResearchParsed:
    """Raw Claude research+extraction payload plus schema-valid transport options.

    research/ never writes to the DB. response_body always holds both call outputs
    (docs/01_architecture.md §4.1 / §5) so services can persist RawApiResponse first.
    """

    request_params: dict[str, object]
    response_body: dict[str, object]
    options: list[ParsedTransportOption]
    extraction_failed: bool
    extraction_error: str | None
