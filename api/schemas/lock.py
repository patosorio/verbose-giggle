from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class LockIn(BaseModel):
    option_card_id: UUID


class LockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    leg_id: UUID
    option_card_id: UUID
    locked_by_user_id: UUID
    locked_price_amount: Decimal
    locked_currency: str
    locked_at: datetime
    unlocked_at: datetime | None
    is_booked: bool
    booked_at: datetime | None


class BookedIn(BaseModel):
    is_booked: bool
