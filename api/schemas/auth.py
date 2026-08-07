from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr


class MagicLinkRequestIn(BaseModel):
    email: EmailStr


class MagicLinkRequestOut(BaseModel):
    message: str


class MagicLinkVerifyIn(BaseModel):
    token: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    display_name: str
    created_at: datetime


class MagicLinkVerifyOut(BaseModel):
    user: UserOut
