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


class RoomOccupancyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adults: int = Field(ge=1, le=6)
    children: int = Field(default=0, ge=0, le=5)
    children_ages: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_room(self) -> "RoomOccupancyIn":
        if self.adults + self.children > 6:
            raise ValueError(
                "google_hotels allows at most 6 travelers per room "
                f"(got adults={self.adults} + children={self.children})"
            )
        if len(self.children_ages) != self.children:
            raise ValueError(
                "children_ages must have exactly one age (0-17) per child"
            )
        if any(age < 0 or age > 17 for age in self.children_ages):
            raise ValueError("children_ages must each be between 0 and 17")
        return self


class OccupancyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rooms: list[RoomOccupancyIn] = Field(
        default_factory=lambda: [RoomOccupancyIn(adults=2)],
        min_length=1,
        max_length=20,
    )


class LegFiltersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flight: FlightFiltersIn = Field(default_factory=FlightFiltersIn)
    hotel: HotelFiltersIn = Field(default_factory=HotelFiltersIn)
    occupancy: OccupancyIn = Field(default_factory=OccupancyIn)


class LegCreateIn(BaseModel):
    sequence_index: int
    origin: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    origin_iata: str | None = Field(default=None, min_length=3, max_length=3)
    destination_iata: str | None = Field(default=None, min_length=3, max_length=3)
    start_date: date
    end_date: date
    filters: LegFiltersIn = Field(default_factory=LegFiltersIn)
    skip_hotel: bool = False

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
    origin_iata: str | None = Field(default=None, min_length=3, max_length=3)
    destination_iata: str | None = Field(default=None, min_length=3, max_length=3)
    filters: LegFiltersIn | None = None
    skip_hotel: bool | None = None

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
    origin_iata: str | None
    destination_iata: str | None
    start_date: date
    end_date: date
    nights: int
    filters: LegFiltersIn
    skip_hotel: bool
    status: LegStatus
