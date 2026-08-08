from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


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
