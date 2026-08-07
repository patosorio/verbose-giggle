from datetime import date, time
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from db.models import LegStatus


class FlightTimeWindowsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    departure_after: time | None = None
    departure_before: time | None = None


class FlightFiltersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_stops: int | None = None
    airlines: list[str] | None = None
    alliances: list[str] | None = None
    max_price: Decimal | None = None
    time_windows: FlightTimeWindowsIn | None = None
    max_layover_minutes: int | None = None
    max_duration_minutes: int | None = None
    bags_required: bool | None = None


class PriceRangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: Decimal
    max: Decimal


class MaxDistanceKmFromIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float
    lng: float
    km: float


class HotelFiltersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    star_class: list[int] | None = None
    brands: list[str] | None = None
    free_cancellation_only: bool = False
    special_offers_only: bool = False
    eco_certified_only: bool = False
    price_range: PriceRangeIn | None = None
    amenities: list[str] | None = None
    max_distance_km_from: MaxDistanceKmFromIn | None = None


class LegFiltersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flight: FlightFiltersIn = Field(default_factory=FlightFiltersIn)
    hotel: HotelFiltersIn = Field(default_factory=HotelFiltersIn)


class LegCreateIn(BaseModel):
    sequence_index: int
    origin: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    start_date: date
    end_date: date
    filters: LegFiltersIn = Field(default_factory=LegFiltersIn)

    @model_validator(mode="after")
    def validate_date_range(self) -> "LegCreateIn":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class LegBulkCreateIn(BaseModel):
    legs: list[LegCreateIn]


class LegPatchIn(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    filters: LegFiltersIn | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> "LegPatchIn":
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("end_date must be on or after start_date")
        return self


class LegOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trip_id: UUID
    sequence_index: int
    origin: str
    destination: str
    start_date: date
    end_date: date
    nights: int
    filters: LegFiltersIn
    status: LegStatus
