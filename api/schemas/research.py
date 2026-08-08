from uuid import UUID

from pydantic import BaseModel, ConfigDict

from db.models import ResearchRunStatus, ResearchRunType


class ResearchStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_type: ResearchRunType


class ResearchStartOut(BaseModel):
    run_id: UUID
    status: ResearchRunStatus


class ResearchRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: ResearchRunStatus
    error_message: str | None
