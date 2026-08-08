from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from db.models import BudgetBand


class BudgetLegOut(BaseModel):
    leg_id: UUID
    locked_option_id: UUID | None
    amount: Decimal | None


class BudgetOut(BaseModel):
    home_currency: str
    budget_band: BudgetBand
    budget_target_amount: Decimal | None
    running_total: Decimal
    by_leg: list[BudgetLegOut]
