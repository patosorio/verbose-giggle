"""AI trip advisor — one bounded Claude call per turn, then deterministic IATA resolution.

Pattern mirrors research/activities.py: tool_choice forced to a single tool, parse
via a pure function, at most one ValidationError correction retry (2 API calls max).
No web_search. No DB writes. Conversation state is entirely client-supplied.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from anthropic import APIError, AsyncAnthropic
from anthropic.types import Message, ToolUseBlock
from pydantic import ValidationError

from core.config import settings
from core.errors import AppError
from schemas.advisor import (
    AdvisorLegIn,
    AdvisorMessageIn,
    AdvisorTurnIn,
    AdvisorTurnOut,
    AdvisorTurnResponse,
    AirportCandidateOut,
    ProposedLegOut,
)
from services.airports import resolve_place

logger = logging.getLogger(__name__)

_ADVISOR_TURN_TOOL_NAME = "advisor_turn"

_MAX_TURNS_REPLY = (
    "This conversation has gotten long enough that I shouldn't keep revising via chat. "
    "Finish the itinerary directly in the form on the left — every field there is "
    "editable — or start a new Plan with AI conversation if you want a fresh chat."
)

_ADVISOR_TURN_TOOL: dict[str, object] = {
    "name": _ADVISOR_TURN_TOOL_NAME,
    "description": (
        "Emit the assistant chat reply plus the full revised itinerary state after "
        "this user message. Legs use plain origin/destination strings — never IATA codes."
    ),
    "input_schema": AdvisorTurnOut.model_json_schema(),
}


class AdvisorAgentError(AppError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(502, "upstream_api_error", message, details=details)


def parse_advisor_turn_payload(raw: object) -> AdvisorTurnOut:
    """Validate advisor_turn tool input. Pure — never calls Anthropic."""
    return AdvisorTurnOut.model_validate(raw)


def attach_airport_resolution(legs: list[AdvisorLegIn]) -> list[ProposedLegOut]:
    """Upgrade plain legs with deterministic IATA resolution (isolated from the model)."""
    proposed: list[ProposedLegOut] = []
    for leg in legs:
        origin_res = resolve_place(leg.origin)
        dest_res = resolve_place(leg.destination)
        proposed.append(
            ProposedLegOut(
                origin=leg.origin,
                destination=leg.destination,
                start_date=leg.start_date,
                end_date=leg.end_date,
                filters=leg.filters,
                skip_hotel=leg.skip_hotel,
                skip_flight=leg.skip_flight,
                locked=leg.locked,
                origin_iata=origin_res.resolved_iata,
                origin_candidates=[
                    AirportCandidateOut(
                        iata=c.iata,
                        name=c.name,
                        city=c.city,
                        country=c.country,
                    )
                    for c in origin_res.candidates
                ],
                destination_iata=dest_res.resolved_iata,
                destination_candidates=[
                    AirportCandidateOut(
                        iata=c.iata,
                        name=c.name,
                        city=c.city,
                        country=c.country,
                    )
                    for c in dest_res.candidates
                ],
            )
        )
    return proposed


def _client() -> AsyncAnthropic:
    if not settings.anthropic_api_key:
        raise AdvisorAgentError("ANTHROPIC_API_KEY is not configured")
    return AsyncAnthropic(api_key=settings.anthropic_api_key)


def _system_prompt(turn: AdvisorTurnIn) -> str:
    current_state = {
        "trip_name": turn.trip_name,
        "home_currency": turn.home_currency,
        "budget_band": turn.budget_band.value if turn.budget_band is not None else None,
        "budget_target_amount": (
            str(turn.budget_target_amount) if turn.budget_target_amount is not None else None
        ),
        "current_legs": [leg.model_dump(mode="json") for leg in turn.current_legs],
        "locked_legs": [leg.model_dump(mode="json") for leg in turn.locked_legs],
    }
    return (
        "You are the trip advisor for Junket, a collaborative group trip planner. "
        "Users compare priced flight/hotel/activity options per stop (leg); an "
        "organizer locks final choices against a running budget. Flights and hotels "
        "are researched via SerpApi; activities via a separate research agent. You do "
        "NOT verify whether a route is flyable or bookable — you only structure what "
        "the user tells you into the itinerary form.\n\n"
        "Call the advisor_turn tool exactly once per reply.\n\n"
        "The block below is the center-panel itinerary state RIGHT NOW:\n"
        f"<current_itinerary>\n{json.dumps(current_state, indent=2)}\n</current_itinerary>\n\n"
        "locked_legs are already finalized by the user. Treat them as read-only "
        "context (so you do not duplicate or contradict them). Do NOT include "
        "locked_legs in your tool `legs` array.\n\n"
        "current_legs are the only legs you may revise. Return in `legs` the full "
        "revisable itinerary as it should be after this message — keep every "
        "unlocked leg/field the conversation doesn't imply should change; only "
        "add, remove, or modify what the latest message actually addresses. "
        "New legs you add also go in `legs` (still never re-emit locked_legs).\n\n"
        "Ask clarifying questions before inventing details. Prefer asking about "
        "anything needed to fill LegFiltersIn well before including a leg with real "
        "dates: occupancy (filters.occupancy.rooms with adults, children, "
        "children_ages — use those exact field names), star rating / budget "
        "preference (budget_band and hotel star_class / price filters), flight "
        "max_stops, whether a leg should skip_hotel (staying with family/friends), "
        "and whether a leg should skip_flight (ferry / ground transfer with no "
        "airport — e.g. Phuket to Koh Yao Noi). When skip_flight is true, IATA is "
        "not required; transport research still runs. "
        "Also ask about trip_name, home_currency, and budget_target_amount when still "
        "unknown.\n\n"
        "A leg with unknown dates should stay absent from legs, or keep "
        "start_date/end_date as null — never guess dates. Prefer an empty legs array "
        "while still gathering basics over fabricating a full itinerary from one "
        "vague sentence.\n\n"
        "origin and destination are plain place-name strings (e.g. \"Bangkok\"), never "
        "IATA codes — airport resolution happens server-side after your tool call.\n"
    )


def _correction_prompt(error_message: str) -> str:
    return (
        "Your previous advisor_turn tool call was invalid and was rejected.\n"
        f"Validation error: <validation_error>{error_message}</validation_error>\n"
        "Call advisor_turn again with a corrected payload. Keep the revise-in-place "
        "rules: only change what the latest user message addressed; do not invent dates."
    )


def _find_advisor_tool_use(message: Message) -> ToolUseBlock | None:
    for block in message.content:
        if isinstance(block, ToolUseBlock) and block.name == _ADVISOR_TURN_TOOL_NAME:
            return block
    return None


def _log_usage(message: Message, *, trace_id: str, attempt: int) -> None:
    usage = message.usage
    logger.info(
        "advisor_claude_usage trace_id=%s attempt=%s input_tokens=%s output_tokens=%s",
        trace_id,
        attempt,
        usage.input_tokens,
        usage.output_tokens,
    )


def _messages_for_api(messages: list[AdvisorMessageIn]) -> list[dict[str, str]]:
    return [{"role": m.role, "content": m.content} for m in messages]


async def _advisor_call(
    client: AsyncAnthropic,
    *,
    system: str,
    messages: list[dict[str, object]],
    trace_id: str,
    attempt: int,
) -> Message:
    try:
        response = await client.messages.create(
            model=settings.anthropic_advisor_model,
            max_tokens=settings.anthropic_advisor_max_tokens,
            system=system,
            messages=messages,
            tools=[_ADVISOR_TURN_TOOL],
            tool_choice={"type": "tool", "name": _ADVISOR_TURN_TOOL_NAME},
        )
    except APIError as exc:
        logger.error(
            "advisor_api_error trace_id=%s attempt=%s status=%s",
            trace_id,
            attempt,
            getattr(exc, "status_code", None),
        )
        raise AdvisorAgentError(
            "Anthropic advisor call failed",
            details={"trace_id": trace_id, "error": str(exc)},
        ) from exc

    _log_usage(response, trace_id=trace_id, attempt=attempt)
    return response


def _parse_tool_message(
    message: Message,
) -> tuple[AdvisorTurnOut | None, str | None, ToolUseBlock | None]:
    tool_use = _find_advisor_tool_use(message)
    if tool_use is None:
        return None, "advisor response missing advisor_turn tool_use block", None
    try:
        return parse_advisor_turn_payload(tool_use.input), None, tool_use
    except ValidationError as exc:
        return None, f"tool input schema invalid: {exc.errors()}", tool_use


def _to_response(parsed: AdvisorTurnOut) -> AdvisorTurnResponse:
    return AdvisorTurnResponse(
        reply=parsed.reply,
        legs=attach_airport_resolution(parsed.legs),
        trip_name=parsed.trip_name,
        home_currency=parsed.home_currency,
        budget_band=parsed.budget_band,
        budget_target_amount=parsed.budget_target_amount,
    )


def _max_turns_response(turn: AdvisorTurnIn) -> AdvisorTurnResponse:
    return AdvisorTurnResponse(
        reply=_MAX_TURNS_REPLY,
        legs=attach_airport_resolution(turn.current_legs),
        trip_name=turn.trip_name,
        home_currency=turn.home_currency,
        budget_band=turn.budget_band,
        budget_target_amount=turn.budget_target_amount,
    )


async def run_advisor_turn(
    turn: AdvisorTurnIn,
    *,
    trace_id: str | None = None,
) -> AdvisorTurnResponse:
    """Run one advisor turn. At most two Claude calls; max-turns path is zero-cost."""
    tid = trace_id or str(uuid4())

    # Hard conversation cap — must run before _client() is ever touched.
    if len(turn.messages) >= settings.anthropic_advisor_max_turns * 2:
        logger.info(
            "advisor_max_turns_hit trace_id=%s message_count=%s max_turns=%s",
            tid,
            len(turn.messages),
            settings.anthropic_advisor_max_turns,
        )
        return _max_turns_response(turn)

    client = _client()
    system = _system_prompt(turn)
    api_messages: list[dict[str, object]] = list(_messages_for_api(turn.messages))

    # Attempt 1.
    response = await _advisor_call(
        client,
        system=system,
        messages=api_messages,
        trace_id=tid,
        attempt=1,
    )
    parsed, batch_error, tool_use = _parse_tool_message(response)
    if parsed is not None:
        logger.info(
            "advisor_turn_ok trace_id=%s attempt=%s legs=%s",
            tid,
            1,
            len(parsed.legs),
        )
        return _to_response(parsed)

    logger.warning(
        "advisor_turn_invalid trace_id=%s attempt=%s error=%s",
        tid,
        1,
        batch_error,
    )

    # Attempt 2 (final) — one correction retry only. Include tool_result so the
    # API accepts the prior tool_use; never a third call.
    if tool_use is None:
        raise AdvisorAgentError(
            "Advisor turn failed validation and no tool_use to correct",
            details={"trace_id": tid, "error": batch_error},
        )

    correction_messages: list[dict[str, object]] = [
        *api_messages,
        {"role": "assistant", "content": response.content},
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": batch_error or "invalid",
                    "is_error": True,
                },
                {"type": "text", "text": _correction_prompt(batch_error or "invalid")},
            ],
        },
    ]
    response2 = await _advisor_call(
        client,
        system=system,
        messages=correction_messages,
        trace_id=tid,
        attempt=2,
    )
    parsed2, batch_error2, _tool_use2 = _parse_tool_message(response2)
    if parsed2 is not None:
        logger.info(
            "advisor_turn_ok trace_id=%s attempt=%s legs=%s",
            tid,
            2,
            len(parsed2.legs),
        )
        return _to_response(parsed2)

    logger.warning(
        "advisor_turn_invalid trace_id=%s attempt=%s error=%s",
        tid,
        2,
        batch_error2,
    )
    raise AdvisorAgentError(
        "Advisor turn failed validation after correction retry",
        details={"trace_id": tid, "error": batch_error2},
    )
