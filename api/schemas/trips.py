from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from db.models import BudgetBand, TripMemberRole, TripStatus


class TripCreateIn(BaseModel):
    name: str = Field(min_length=1)
    home_currency: str
    budget_band: BudgetBand
    budget_target_amount: Decimal | None = None

    @field_validator("home_currency")
    @classmethod
    def validate_home_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("home_currency must be a 3-letter ISO 4217 code")
        return normalized


class TripPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    budget_band: BudgetBand | None = None
    budget_target_amount: Decimal | None = None


class TripSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    organizer_id: UUID
    home_currency: str
    budget_band: BudgetBand
    budget_target_amount: Decimal | None
    status: TripStatus
    created_at: datetime


class TripOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    organizer_id: UUID
    home_currency: str
    budget_band: BudgetBand
    budget_target_amount: Decimal | None
    status: TripStatus
    created_at: datetime


class TripMemberCreateIn(BaseModel):
    email: EmailStr


class TripMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trip_id: UUID
    user_id: UUID | None
    invited_email: EmailStr
    role: TripMemberRole
    joined_at: datetime | None


class TransferOrganizerIn(BaseModel):
    new_organizer_user_id: UUID
