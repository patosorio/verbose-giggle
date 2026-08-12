from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from db.models import AgeCategory


class TravelerCreateIn(BaseModel):
    name: str = Field(min_length=1)
    age_category: AgeCategory


class TravelerPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    age_category: AgeCategory | None = None


class TravelerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trip_id: UUID
    name: str
    age_category: AgeCategory
    created_at: datetime
