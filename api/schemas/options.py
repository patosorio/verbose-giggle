from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from db.models import BudgetBand, OptionType, ReactionType, TransportMode


class ReactionIn(BaseModel):
    reaction_type: ReactionType


class ReactionSummaryOut(BaseModel):
    up: int
    down: int
    my_reaction: ReactionType | None


class BookingSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seller_name: str
    price_amount: Decimal
    currency: str
    deep_link_url: str
    booking_post_data: dict[str, object] | None
    fetched_at: datetime


class CitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    claim_text: str
    source_url: str
    retrieved_at: datetime


class OptionCardCoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tier: BudgetBand | None
    title: str
    base_price_amount: Decimal | None
    currency: str
    original_price_amount: Decimal | None = None
    original_currency: str | None = None
    fx_rate: Decimal | None = None
    fx_rate_as_of: date | None = None
    reaction_summary: ReactionSummaryOut


class FlightOptionOut(OptionCardCoreOut):
    option_type: Literal[OptionType.flight] = OptionType.flight
    booking_token: str
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


class HotelOptionOut(OptionCardCoreOut):
    option_type: Literal[OptionType.hotel] = OptionType.hotel
    property_token: str
    name: str
    star_rating: Decimal
    gps_lat: Decimal
    gps_lng: Decimal
    checkin_date: date
    checkout_date: date
    free_cancellation: bool
    eco_certified: bool
    amenities: list[str]
    room_label: str | None


class ActivityOptionOut(OptionCardCoreOut):
    option_type: Literal[OptionType.activity] = OptionType.activity
    category: str
    description: str
    duration_minutes: int | None
    estimated_price_amount: Decimal
    estimated_price_currency: str


class TransportOptionOut(OptionCardCoreOut):
    option_type: Literal[OptionType.transport] = OptionType.transport
    mode: TransportMode
    operator_name: str | None
    departure_point: str
    arrival_point: str
    estimated_duration_minutes: int | None
    booking_url: str | None


class ImportedOptionOut(OptionCardCoreOut):
    option_type: Literal[OptionType.imported] = OptionType.imported
    source_url: str | None
    extracted_title: str
    extracted_description: str | None
    category_hint: str | None


OptionCardOut = Annotated[
    FlightOptionOut
    | HotelOptionOut
    | ActivityOptionOut
    | TransportOptionOut
    | ImportedOptionOut,
    Field(discriminator="option_type"),
]
