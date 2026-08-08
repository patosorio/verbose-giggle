"""Phase 3 activities eval set — fixture-only, no live Anthropic calls.

docs/04_build_plan.md Phase 3 · docs/02_data_model.md §3 (fixtures + pytest, not DB).
Live exit-criteria walkthrough: scripts/phase3_activities_walkthrough.py
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from research.activities import parse_emit_activities_payload
from research.types import ParsedActivityOption, ParsedCitation, SuggestedTiming
from services.activities import (
    drop_implausible_prices,
    drop_missing_citations,
    drop_same_day_transfer_conflicts,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "evals" / "activities"
SKIP_LOG_FRAGMENT = "same-day check skipped, no duration data"
PRICE_SKIP_LOG_FRAGMENT = (
    "implausible-price check skipped, fewer than 2 same-currency peers"
)


def _load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _fixture_paths() -> list[Path]:
    paths = sorted(FIXTURES_DIR.glob("*.json"))
    if not paths:
        raise AssertionError(f"No eval fixtures found under {FIXTURES_DIR}")
    return paths


def _activity_from_dict(raw: dict[str, Any]) -> ParsedActivityOption:
    citations = [
        ParsedCitation(claim_text=c["claim_text"], source_url=c["source_url"])
        for c in raw.get("citations", [])
    ]
    return ParsedActivityOption(
        title=raw["title"],
        category=raw["category"],
        description=raw["description"],
        duration_minutes=raw.get("duration_minutes"),
        estimated_price_amount=Decimal(str(raw["estimated_price_amount"])),
        estimated_price_currency=raw["estimated_price_currency"],
        citations=citations,
        suggested_timing=SuggestedTiming(raw["suggested_timing"]),
    )


def _assert_title_sets(
    *,
    kept: list[ParsedActivityOption],
    input_titles: list[str],
    expect: dict[str, Any],
) -> None:
    kept_titles = [a.title for a in kept]
    dropped_titles = [t for t in input_titles if t not in kept_titles]
    assert kept_titles == expect["kept_titles"], (
        f"kept mismatch: got {kept_titles!r}, want {expect['kept_titles']!r}"
    )
    assert dropped_titles == expect["dropped_titles"], (
        f"dropped mismatch: got {dropped_titles!r}, want {expect['dropped_titles']!r}"
    )


@pytest.mark.parametrize("fixture_path", _fixture_paths(), ids=lambda p: p.stem)
def test_activities_eval_fixture(
    fixture_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    case = _load_fixture(fixture_path)
    gate = case["gate"]
    layer = case["layer"]
    expect = case["expect"]

    if layer == "research_parse":
        assert gate == "missing_citation"
        payload = case["emit_payload"]
        input_titles = [
            raw["title"]
            for raw in payload["activities"]
            if isinstance(raw, dict) and "title" in raw
        ]
        parsed, _drop_reasons = parse_emit_activities_payload(payload)
        _assert_title_sets(kept=parsed, input_titles=input_titles, expect=expect)
        return

    assert layer == "service_filter"
    activities = [_activity_from_dict(raw) for raw in case["activities"]]
    input_titles = [a.title for a in activities]

    if gate == "missing_citation":
        kept = drop_missing_citations(activities)
        _assert_title_sets(kept=kept, input_titles=input_titles, expect=expect)
        return

    if gate == "implausible_price":
        with caplog.at_level(logging.INFO, logger="services.activities"):
            kept = drop_implausible_prices(activities)
        _assert_title_sets(kept=kept, input_titles=input_titles, expect=expect)
        if "skip_logged" in expect:
            skip_logged = PRICE_SKIP_LOG_FRAGMENT in caplog.text
            assert skip_logged is expect["skip_logged"], (
                f"price skip log expected={expect['skip_logged']}, "
                f"found={skip_logged}, log={caplog.text!r}"
            )
        return

    if gate == "same_day_transfer":
        duration = case.get("flight_duration_minutes")
        with caplog.at_level(logging.INFO, logger="services.activities"):
            kept = drop_same_day_transfer_conflicts(
                activities,
                flight_duration_minutes=duration,
            )
        _assert_title_sets(kept=kept, input_titles=input_titles, expect=expect)
        skip_logged = SKIP_LOG_FRAGMENT in caplog.text
        assert skip_logged is expect["skip_logged"], (
            f"skip log expected={expect['skip_logged']}, "
            f"found={skip_logged}, log={caplog.text!r}"
        )
        return

    raise AssertionError(f"Unknown gate={gate!r} layer={layer!r} in {fixture_path.name}")


def test_deliberately_broken_citation_fixture_enforces_gate() -> None:
    """Exit criteria: a citation-free claim must fail the gate (not only valid cases pass)."""
    case = _load_fixture(FIXTURES_DIR / "citation_empty_array.json")
    parsed, drop_reasons = parse_emit_activities_payload(case["emit_payload"])
    assert parsed == []
    assert drop_reasons, "expected a drop reason proving the citation gate fired"
    assert case["expect"]["dropped_titles"] == ["Citation-Free Snorkel Claim"]


def test_eval_fixture_count_in_target_range() -> None:
    count = len(_fixture_paths())
    # ~15–20 in the build plan; a few more landed when currency bucketing was added.
    assert 15 <= count <= 25, f"expected ~15–25 eval fixtures, found {count}"
