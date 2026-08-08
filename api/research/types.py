from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


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
