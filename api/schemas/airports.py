from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from schemas.advisor import AirportCandidateOut


class AirportResolveOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolved_iata: str | None
    candidates: list[AirportCandidateOut]
