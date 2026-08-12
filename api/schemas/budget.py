from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from db.models import BudgetBand, OptionType


class LockedOptionSummaryOut(BaseModel):
    option_card_id: UUID
    option_type: OptionType
    title: str
    tier: BudgetBand | None
    amount: Decimal
    currency: str
    is_booked: bool
    booked_at: datetime | None
    unit_price_amount: Decimal | None
    party_size: int | None
    room_label: str | None


class BudgetLegOut(BaseModel):
    leg_id: UUID
    locked_option_ids: list[UUID]
    # Same lock iteration order as locked_option_ids — element-for-element parallel lists.
    locked_options: list[LockedOptionSummaryOut]
    amount: Decimal | None


class BudgetOut(BaseModel):
    home_currency: str
    budget_band: BudgetBand
    budget_target_amount: Decimal | None
    running_total: Decimal
    by_leg: list[BudgetLegOut]
