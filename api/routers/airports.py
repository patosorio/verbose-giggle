"""Deterministic airport lookup — no AI, no network, no DB. Confirm req.4"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from core.security import require_user
from db.models import User
from schemas.advisor import AirportCandidateOut
from schemas.airports import AirportResolveOut
from services.airports import resolve_place

router = APIRouter(prefix="/airports", tags=["airports"])


@router.get("/resolve", response_model=AirportResolveOut)
async def resolve_airport(
    place: Annotated[str, Query(min_length=1)],
    _: Annotated[User, Depends(require_user)],
) -> AirportResolveOut:
    result = resolve_place(place)
    return AirportResolveOut(
        resolved_iata=result.resolved_iata,
        candidates=[
            AirportCandidateOut(
                iata=c.iata, name=c.name, city=c.city, country=c.country
            )
            for c in result.candidates
        ],
    )
