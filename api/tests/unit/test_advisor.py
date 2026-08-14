"""Unit tests for advisor parse + IATA attach — no live Anthropic calls.

docs/26_ai_trip_advisor_cursor_prompt.md §7. Never imports or touches AsyncAnthropic.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas.advisor import AdvisorLegIn, AdvisorMessageIn, AdvisorTurnIn
from services.advisor import (
    attach_airport_resolution,
    parse_ask_user_payload,
    parse_revise_itinerary_payload,
    run_advisor_turn,
)
from services.airports import resolve_place


def test_parse_ask_user_gathering() -> None:
    parsed = parse_ask_user_payload(
        {
            "reply": "Happy to help with **Thailand**. A few details so I don't guess.",
            "questions": [
                "Where are you flying from?",
                "Roughly which dates?",
                "How many adults and children?",
            ],
            "trip_name": None,
            "home_currency": None,
            "budget_band": None,
            "budget_target_amount": None,
        }
    )
    assert parsed.questions[0].startswith("Where")
    assert "Thailand" in parsed.reply
    assert len(parsed.questions) == 3


def test_parse_ask_user_requires_questions() -> None:
    with pytest.raises(ValidationError):
        parse_ask_user_payload(
            {
                "reply": "Happy to help — how many people?",
                "questions": [],
            }
        )


def test_parse_revise_itinerary_normal() -> None:
    parsed = parse_revise_itinerary_payload(
        {
            "reply": "Added **Bangkok**, 1–5 May.",
            "questions": ["Want a hotel search there, or staying with friends?"],
            "legs": [
                {
                    "origin": "Singapore",
                    "destination": "Bangkok",
                    "start_date": "2026-05-01",
                    "end_date": "2026-05-05",
                    "skip_hotel": False,
                    "skip_flight": False,
                    "locked": False,
                    "filters": {
                        "occupancy": {
                            "rooms": [{"adults": 2, "children": 0, "children_ages": []}]
                        }
                    },
                }
            ],
            "trip_name": "Thailand 2026",
            "home_currency": "USD",
            "budget_band": "comfort",
            "budget_target_amount": None,
        }
    )
    assert parsed.reply.startswith("Added")
    assert len(parsed.legs) == 1
    assert parsed.legs[0].destination == "Bangkok"
    assert parsed.legs[0].start_date is not None
    assert parsed.budget_band == "comfort"
    assert len(parsed.questions) == 1


def test_parse_revise_malformed_payload_raises() -> None:
    with pytest.raises(ValidationError):
        parse_revise_itinerary_payload(
            {
                "reply": "ok",
                "legs": [{"origin": 123, "destination": None}],
            }
        )


def test_parse_revise_missing_reply_raises() -> None:
    with pytest.raises(ValidationError):
        parse_revise_itinerary_payload(
            {
                "legs": [{"origin": "Singapore", "destination": "Bangkok"}],
            }
        )


def test_resolve_ambiguous_city_london() -> None:
    resolution = resolve_place("London")
    assert resolution.resolved_iata is None
    assert len(resolution.candidates) >= 2
    iatas = {c.iata for c in resolution.candidates}
    assert "LHR" in iatas or "LGW" in iatas


def test_resolve_unambiguous_bangkok_or_candidates() -> None:
    resolution = resolve_place("Bangkok")
    # Bangkok may be one airport or several (BKK/DMK) — never invent a silent pick
    # beyond what resolve_place's exact/substring rules produce.
    if resolution.resolved_iata is not None:
        assert len(resolution.candidates) == 1
        assert resolution.candidates[0].iata == resolution.resolved_iata
    else:
        assert len(resolution.candidates) >= 2


def test_attach_airport_resolution_ambiguous_city() -> None:
    legs = [
        AdvisorLegIn(origin="Singapore", destination="London"),
    ]
    proposed = attach_airport_resolution(legs)
    assert len(proposed) == 1
    assert proposed[0].destination == "London"
    assert proposed[0].destination_iata is None
    assert len(proposed[0].destination_candidates) >= 2


@pytest.mark.asyncio
async def test_max_turns_is_ask_without_claude() -> None:
    """Hard cap path must not touch Anthropic and must not rewrite legs."""
    messages = [
        AdvisorMessageIn(
            role="user" if i % 2 == 0 else "assistant",
            content=f"msg-{i}",
        )
        for i in range(40)
    ]
    turn = AdvisorTurnIn(
        messages=messages,
        current_legs=[
            AdvisorLegIn(origin="Singapore", destination="Bangkok"),
        ],
        trip_name="Cap test",
        home_currency="USD",
        budget_band="budget",
        budget_target_amount=None,
    )
    result = await run_advisor_turn(turn, trace_id="test-max-turns")
    assert result.action == "ask"
    assert result.legs == []
    assert result.questions == []
    assert "form" in result.reply.lower() or "conversation" in result.reply.lower()
    assert result.trip_name == "Cap test"
    assert result.budget_band == "budget"
