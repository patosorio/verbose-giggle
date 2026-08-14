"""AI trip advisor — one bounded Claude call per turn, then deterministic IATA resolution.

Two tools, model picks one (`tool_choice: any`):
- ask_user — conversation / clarifying questions; does not mutate legs.
- revise_itinerary — write or patch the unlocked itinerary.

Pattern otherwise mirrors research/activities.py: parse via pure functions, at most
one ValidationError correction retry (2 API calls max). No web_search. No DB writes.
Conversation state is entirely client-supplied.
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
    AdvisorAskOut,
    AdvisorLegIn,
    AdvisorMessageIn,
    AdvisorReviseOut,
    AdvisorTurnIn,
    AdvisorTurnResponse,
    AirportCandidateOut,
    ProposedLegOut,
)
from services.airports import resolve_place

logger = logging.getLogger(__name__)

_ASK_USER_TOOL_NAME = "ask_user"
_REVISE_ITINERARY_TOOL_NAME = "revise_itinerary"
_ADVISOR_TOOL_NAMES = frozenset({_ASK_USER_TOOL_NAME, _REVISE_ITINERARY_TOOL_NAME})

_MAX_TURNS_REPLY = (
    "This conversation has gotten long enough that I shouldn't keep revising via chat. "
    "Finish the itinerary directly in the form on the left — every field there is "
    "editable — or start a new Plan with AI conversation if you want a fresh chat."
)

_REPLY_PROPERTY: dict[str, object] = {
    "type": "string",
    "description": (
        "Conversational assistant message in compact Markdown: short paragraphs, "
        "**bold** for place names and dates. No headings, images, or HTML. "
        "Do not list the clarifying questions here — those go in `questions` as "
        "plain strings. Do not paste the itinerary; the form already shows it."
    ),
}

_TRIP_META_PROPERTIES: dict[str, object] = {
    "trip_name": {
        "type": ["string", "null"],
        "description": "Trip title if known or just decided; null if unchanged/unknown.",
    },
    "home_currency": {
        "type": ["string", "null"],
        "description": "ISO 4217 code (e.g. USD) if known; null if unchanged/unknown.",
    },
    "budget_band": {
        "anyOf": [
            {"type": "string", "enum": ["budget", "comfort", "premium"]},
            {"type": "null"},
        ],
        "description": "Null if unchanged/unknown.",
    },
    "budget_target_amount": {
        "anyOf": [{"type": "number"}, {"type": "string"}, {"type": "null"}],
        "description": "Numeric target in home_currency; null if unchanged/unknown.",
    },
}

_ASK_USER_TOOL: dict[str, object] = {
    "name": _ASK_USER_TOOL_NAME,
    "description": (
        "Ask clarifying questions or propose a plan without changing itinerary "
        "legs. Use on a vague first message, while exploring, or when origin / "
        "destination / dates would have to be invented. When you have a concrete "
        "stop in mind, propose it in reply and wait for a yes — then the next "
        "turn must call revise_itinerary. Do not keep asking once the user has "
        "agreed to a writeable stop."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["reply", "questions"],
        "properties": {
            "reply": _REPLY_PROPERTY,
            "questions": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
                "description": (
                    "The actual questions for the user, as plain strings. The UI "
                    "renders these as a list — do not also number them in `reply`."
                ),
            },
            **_TRIP_META_PROPERTIES,
        },
    },
}

_REVISE_LEG_ITEM_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["origin", "destination"],
    "properties": {
        "origin": {
            "type": "string",
            "description": "Place name (e.g. Singapore), never an IATA code.",
        },
        "destination": {
            "type": "string",
            "description": "Place name (e.g. Bangkok), never an IATA code.",
        },
        "start_date": {
            "type": ["string", "null"],
            "description": "YYYY-MM-DD, or null if the user has not given dates. Never guess.",
        },
        "end_date": {
            "type": ["string", "null"],
            "description": "YYYY-MM-DD, or null if unknown. Never guess.",
        },
        "skip_hotel": {
            "type": "boolean",
            "description": "True if staying with family/friends (no hotel search).",
        },
        "skip_flight": {
            "type": "boolean",
            "description": "True for ferry/ground with no airport.",
        },
        "locked": {
            "type": "boolean",
            "description": "Always false. Locked legs are not in this array.",
        },
        "filters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "occupancy": {
                    "type": "object",
                    "properties": {
                        "rooms": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["adults"],
                                "properties": {
                                    "adults": {"type": "integer", "minimum": 1, "maximum": 6},
                                    "children": {"type": "integer", "minimum": 0, "maximum": 5},
                                    "children_ages": {
                                        "type": "array",
                                        "items": {
                                            "type": "integer",
                                            "minimum": 0,
                                            "maximum": 17,
                                        },
                                    },
                                },
                            },
                        }
                    },
                },
                "flight": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "max_stops": {"type": ["integer", "null"]},
                    },
                },
                "hotel": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "star_class": {
                            "type": "array",
                            "items": {"type": "integer", "minimum": 1, "maximum": 5},
                        }
                    },
                },
            },
        },
    },
}

_REVISE_ITINERARY_TOOL: dict[str, object] = {
    "name": _REVISE_ITINERARY_TOOL_NAME,
    "description": (
        "Write or update unlocked itinerary legs. Call this as soon as a stop is "
        "writeable: origin + destination without inventing them, AND either the "
        "user just agreed to a proposal you made, dumped a complete stop, or "
        "answered the last missing slot (dates / who). Occupancy defaults to 2 "
        "adults if unstated — say so in reply. Do not wait for a separate "
        "'please add it' if they already said yes or gave the facts."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["reply", "legs"],
        "properties": {
            "reply": _REPLY_PROPERTY,
            "questions": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "description": (
                    "Optional follow-up questions after the revision. Plain strings; "
                    "the UI lists them. Empty if nothing left to ask."
                ),
            },
            "legs": {
                "type": "array",
                "description": (
                    "The full unlocked itinerary as it should be after this message. "
                    "Keep every unlocked leg the latest message did not change. "
                    "Never include locked_legs. Do not use an empty array unless "
                    "the user asked to remove every unlocked stop."
                ),
                "items": _REVISE_LEG_ITEM_SCHEMA,
            },
            **_TRIP_META_PROPERTIES,
        },
    },
}


class AdvisorAgentError(AppError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(502, "upstream_api_error", message, details=details)


def parse_ask_user_payload(raw: object) -> AdvisorAskOut:
    """Validate ask_user tool input. Pure — never calls Anthropic."""
    return AdvisorAskOut.model_validate(raw)


def parse_revise_itinerary_payload(raw: object) -> AdvisorReviseOut:
    """Validate revise_itinerary tool input. Pure — never calls Anthropic."""
    return AdvisorReviseOut.model_validate(raw)


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
        "the user tells you, and you help them decide what to put in the form.\n\n"
        "Call exactly one tool per reply: ask_user or revise_itinerary. Never both. "
        "This is a hybrid: talk first, then write legs into the form as soon as "
        "the user agrees or has given a writeable stop. The chat is pointless if "
        "it only questions and never fills the itinerary; it is also wrong if it "
        "invents a full trip from one vague sentence.\n\n"
        "The block below is the center-panel itinerary state RIGHT NOW:\n"
        f"<current_itinerary>\n{json.dumps(current_state, indent=2)}\n</current_itinerary>\n\n"
        "locked_legs are already finalized by the user. Treat them as read-only "
        "context (so you do not duplicate or contradict them). Never include them "
        "in revise_itinerary `legs`.\n\n"
        "current_legs are the only legs revise_itinerary may change. When you call "
        "revise_itinerary, return in `legs` the full unlocked itinerary as it should "
        "be after this message — keep every unlocked leg/field the latest message "
        "does not imply should change.\n\n"
        "A stop is writeable when you have origin city + destination city (never "
        "invent those) AND dates the user actually gave (or they said to add the "
        "row without dates — then dates may be null). Occupancy: use what they "
        "stated; if they have not, default to 2 adults and say so in reply. Hotel "
        "stars, max_stops, skip_hotel, skip_flight, trip_name, and currency are "
        "polish — do not block writing the first leg on them; ask as follow-ups "
        "in `questions` on the revise (or a later ask_user).\n\n"
        "When to call ask_user:\n"
        "- The latest message is vague (e.g. \"planning a trip to Thailand\") — "
        "ask who / when / where, or propose 1–2 concrete loops and wait for a yes.\n"
        "- You would have to invent origin, destination, or dates to write a leg.\n"
        "- You are proposing a plan (\"Singapore → Bangkok, 1–5 May, 2 adults — "
        "add that stop?\") and they have not agreed yet.\n"
        "ask_user does not change legs. You may still fill trip_name, home_currency, "
        "budget_band, or budget_target_amount when the user has given them.\n\n"
        "When to call revise_itinerary — same turn, do not wait for another prompt:\n"
        "- They said yes / looks good / add it / go ahead to a proposal you made.\n"
        "- They dumped a complete stop (\"Singapore to Bangkok May 1–5, 2 adults\").\n"
        "- Their latest answer filled the last missing slot so a stop is writeable.\n"
        "- They asked to add, remove, or change a stop and you have origin + "
        "destination without inventing them.\n"
        "- They agreed to a multi-stop sketch with enough dates (e.g. Bangkok then "
        "Chiang Mai then Phuket) — write those legs together.\n"
        "Never invent dates. Do not call revise_itinerary with an empty `legs` "
        "array unless the user asked to remove every unlocked stop. After writing, "
        "a short confirmation in `reply` is enough (the form shows the row); put "
        "any remaining polish in `questions`.\n\n"
        "origin and destination are plain place-name strings (e.g. \"Bangkok\"), never "
        "IATA codes — airport resolution happens server-side after your tool call.\n\n"
        "`reply` is compact Markdown (paragraphs, **bold** for places/dates). Put "
        "the actual questions in `questions` as plain strings; the UI lists them, so "
        "do not also number them inside `reply`."
    )


def _correction_prompt(error_message: str) -> str:
    return (
        "Your previous tool call was invalid and was rejected.\n"
        f"Validation error: <validation_error>{error_message}</validation_error>\n"
        "Call exactly one tool: ask_user (clarify or propose; no legs) or "
        "revise_itinerary (write/update unlocked legs once the user agreed or a "
        "stop is writeable). Never call both. Do not invent dates."
    )


def _advisor_tool_blocks(message: Message) -> list[ToolUseBlock]:
    return [
        block
        for block in message.content
        if isinstance(block, ToolUseBlock) and block.name in _ADVISOR_TOOL_NAMES
    ]


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
            tools=[_ASK_USER_TOOL, _REVISE_ITINERARY_TOOL],
            tool_choice={"type": "any"},
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
) -> tuple[AdvisorAskOut | AdvisorReviseOut | None, str | None, ToolUseBlock | None]:
    blocks = _advisor_tool_blocks(message)
    if len(blocks) != 1:
        names = [block.name for block in blocks]
        return (
            None,
            f"expected exactly one of ask_user|revise_itinerary, got {len(blocks)} ({names})",
            blocks[0] if blocks else None,
        )
    tool_use = blocks[0]
    try:
        if tool_use.name == _ASK_USER_TOOL_NAME:
            return parse_ask_user_payload(tool_use.input), None, tool_use
        return parse_revise_itinerary_payload(tool_use.input), None, tool_use
    except ValidationError as exc:
        return None, f"tool input schema invalid: {exc.errors()}", tool_use


def _to_response(parsed: AdvisorAskOut | AdvisorReviseOut) -> AdvisorTurnResponse:
    if isinstance(parsed, AdvisorAskOut):
        return AdvisorTurnResponse(
            action="ask",
            reply=parsed.reply,
            questions=parsed.questions,
            legs=[],
            trip_name=parsed.trip_name,
            home_currency=parsed.home_currency,
            budget_band=parsed.budget_band,
            budget_target_amount=parsed.budget_target_amount,
        )
    return AdvisorTurnResponse(
        action="revise",
        reply=parsed.reply,
        questions=parsed.questions,
        legs=attach_airport_resolution(parsed.legs),
        trip_name=parsed.trip_name,
        home_currency=parsed.home_currency,
        budget_band=parsed.budget_band,
        budget_target_amount=parsed.budget_target_amount,
    )


def _max_turns_response(turn: AdvisorTurnIn) -> AdvisorTurnResponse:
    return AdvisorTurnResponse(
        action="ask",
        reply=_MAX_TURNS_REPLY,
        questions=[],
        legs=[],
        trip_name=turn.trip_name,
        home_currency=turn.home_currency,
        budget_band=turn.budget_band,
        budget_target_amount=turn.budget_target_amount,
    )


def _log_turn_ok(
    parsed: AdvisorAskOut | AdvisorReviseOut, *, trace_id: str, attempt: int
) -> None:
    if isinstance(parsed, AdvisorAskOut):
        logger.info(
            "advisor_turn_ok trace_id=%s attempt=%s action=ask legs=0 questions=%s",
            trace_id,
            attempt,
            len(parsed.questions),
        )
        return
    logger.info(
        "advisor_turn_ok trace_id=%s attempt=%s action=revise legs=%s questions=%s",
        trace_id,
        attempt,
        len(parsed.legs),
        len(parsed.questions),
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
    parsed, batch_error, _tool_use = _parse_tool_message(response)
    if parsed is not None:
        _log_turn_ok(parsed, trace_id=tid, attempt=1)
        return _to_response(parsed)

    logger.warning(
        "advisor_turn_invalid trace_id=%s attempt=%s error=%s",
        tid,
        1,
        batch_error,
    )

    # Attempt 2 (final) — one correction retry only. Include a tool_result for
    # every prior tool_use (Anthropic requires that); never a third call.
    prior_tools = _advisor_tool_blocks(response)
    if not prior_tools:
        raise AdvisorAgentError(
            "Advisor turn failed validation and no tool_use to correct",
            details={"trace_id": tid, "error": batch_error},
        )

    correction_error = batch_error or "invalid"
    correction_content: list[dict[str, object]] = [
        {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": correction_error,
            "is_error": True,
        }
        for block in prior_tools
    ]
    correction_content.append(
        {"type": "text", "text": _correction_prompt(correction_error)}
    )
    correction_messages: list[dict[str, object]] = [
        *api_messages,
        {"role": "assistant", "content": response.content},
        {"role": "user", "content": correction_content},
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
        _log_turn_ok(parsed2, trace_id=tid, attempt=2)
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
