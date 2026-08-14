"""AI trip advisor request/response schemas (docs/26_ai_trip_advisor_cursor_prompt.md §3)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from db.models import BudgetBand
from schemas.legs import LegFiltersIn


class AdvisorMessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str


class AdvisorLegIn(BaseModel):
    """Mirrors LegCreateIn shape minus sequence_index / IATA (resolved server-side)."""

    model_config = ConfigDict(extra="forbid")

    origin: str
    destination: str
    start_date: date | None = None
    end_date: date | None = None
    filters: LegFiltersIn = Field(default_factory=LegFiltersIn)
    skip_hotel: bool = False
    skip_flight: bool = False
    # Client-only until confirm: advisor must not revise legs marked locked.
    locked: bool = False


class AdvisorTurnIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[AdvisorMessageIn]
    current_legs: list[AdvisorLegIn]
    # Option B: finalized legs omitted from current_legs; sent only as read-only context.
    locked_legs: list[AdvisorLegIn] = Field(default_factory=list)
    trip_name: str | None = None
    home_currency: str | None = None
    budget_band: BudgetBand | None = None
    budget_target_amount: Decimal | None = None


class AirportCandidateOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    iata: str
    name: str
    city: str
    country: str


class ProposedLegOut(AdvisorLegIn):
    origin_iata: str | None = None
    origin_candidates: list[AirportCandidateOut] = Field(default_factory=list)
    destination_iata: str | None = None
    destination_candidates: list[AirportCandidateOut] = Field(default_factory=list)


class AdvisorAskOut(BaseModel):
    """ask_user tool input — conversation only; never includes legs."""

    model_config = ConfigDict(extra="forbid")

    reply: str = Field(min_length=1)
    questions: list[str] = Field(min_length=1)
    trip_name: str | None = None
    home_currency: str | None = None
    budget_band: BudgetBand | None = None
    budget_target_amount: Decimal | None = None


class AdvisorReviseOut(BaseModel):
    """revise_itinerary tool input — full unlocked itinerary after this turn."""

    model_config = ConfigDict(extra="forbid")

    reply: str = Field(min_length=1)
    questions: list[str] = Field(default_factory=list)
    legs: list[AdvisorLegIn]
    trip_name: str | None = None
    home_currency: str | None = None
    budget_band: BudgetBand | None = None
    budget_target_amount: Decimal | None = None


class AdvisorTurnResponse(BaseModel):
    """HTTP response. `legs` is populated only when action is revise (IATA-resolved)."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["ask", "revise"]
    reply: str
    questions: list[str]
    legs: list[ProposedLegOut]
    trip_name: str | None = None
    home_currency: str | None = None
    budget_band: BudgetBand | None = None
    budget_target_amount: Decimal | None = None
