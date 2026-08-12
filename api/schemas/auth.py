from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


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


class UserPatchIn(BaseModel):
    display_name: str = Field(min_length=1)


class MagicLinkVerifyOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserOut
