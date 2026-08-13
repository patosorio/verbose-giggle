"""Deterministic GET /airports/resolve shape — no network, no AI."""

from __future__ import annotations

from schemas.airports import AirportResolveOut
from services.airports import resolve_place


def test_resolve_ambiguous_city_london_matches_out_shape() -> None:
    resolution = resolve_place("London")
    out = AirportResolveOut(
        resolved_iata=resolution.resolved_iata,
        candidates=[
            {
                "iata": c.iata,
                "name": c.name,
                "city": c.city,
                "country": c.country,
            }
            for c in resolution.candidates
        ],
    )
    assert out.resolved_iata is None
    assert len(out.candidates) >= 2
    iatas = {c.iata for c in out.candidates}
    assert "LHR" in iatas or "LGW" in iatas


def test_resolve_unambiguous_bangkok_or_candidates_matches_out_shape() -> None:
    resolution = resolve_place("Bangkok")
    out = AirportResolveOut(
        resolved_iata=resolution.resolved_iata,
        candidates=[
            {
                "iata": c.iata,
                "name": c.name,
                "city": c.city,
                "country": c.country,
            }
            for c in resolution.candidates
        ],
    )
    if out.resolved_iata is not None:
        assert len(out.candidates) == 1
        assert out.candidates[0].iata == out.resolved_iata
    else:
        assert len(out.candidates) >= 2
