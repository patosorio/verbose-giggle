"""Deterministic IATA resolution from a bundled offline dataset — no network, no AI."""

from __future__ import annotations

from dataclasses import dataclass, field

import airportsdata

_iata_by_code: dict[str, dict[str, object]] | None = None


@dataclass(frozen=True, slots=True)
class AirportCandidate:
    iata: str
    name: str
    city: str
    country: str


@dataclass(frozen=True, slots=True)
class AirportResolution:
    resolved_iata: str | None
    candidates: list[AirportCandidate] = field(default_factory=list)


def _load_iata() -> dict[str, dict[str, object]]:
    global _iata_by_code
    if _iata_by_code is None:
        loaded = airportsdata.load("IATA")
        _iata_by_code = loaded if isinstance(loaded, dict) else {}
    return _iata_by_code


def resolve_place(place_name: str) -> AirportResolution:
    """Case-insensitive exact/substring match on the airport `city` field.

    Zero matches → empty. One match → resolved_iata set (and listed in candidates).
    Two or more → resolved_iata None, candidates lists all matches for the user to pick.
    """
    needle = place_name.strip().lower()
    if not needle:
        return AirportResolution(resolved_iata=None, candidates=[])

    matches: list[AirportCandidate] = []
    for iata, meta in _load_iata().items():
        city_raw = meta.get("city")
        if not isinstance(city_raw, str) or not city_raw.strip():
            continue
        city = city_raw.strip()
        city_l = city.lower()
        if city_l != needle and needle not in city_l:
            continue
        name_raw = meta.get("name")
        country_raw = meta.get("country")
        matches.append(
            AirportCandidate(
                iata=str(iata),
                name=name_raw.strip() if isinstance(name_raw, str) else "",
                city=city,
                country=country_raw.strip() if isinstance(country_raw, str) else "",
            )
        )

    if len(matches) == 0:
        return AirportResolution(resolved_iata=None, candidates=[])
    if len(matches) == 1:
        return AirportResolution(resolved_iata=matches[0].iata, candidates=matches)
    return AirportResolution(resolved_iata=None, candidates=matches)
