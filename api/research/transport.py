"""Transport research agent — two Anthropic API calls, no DB writes.

Pattern: docs/01_architecture.md §5 (same shape as research/activities.py).
1. Research call — web_search enabled, bounded by max_uses.
2. Extraction call — tool_choice forced to emit_transport_options; Python validates.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from anthropic import APIError, AsyncAnthropic
from anthropic.types import Message, ToolUseBlock
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from core.config import settings
from core.errors import AppError
from db.models import TransportMode
from research.types import (
    ParsedCitation,
    ParsedTransportOption,
    TransportResearchParsed,
    coerce_estimated_price_amount,
)

logger = logging.getLogger(__name__)

_EMIT_TRANSPORT_TOOL_NAME = "emit_transport_options"

_EMIT_TRANSPORT_TOOL: dict[str, object] = {
    "name": _EMIT_TRANSPORT_TOOL_NAME,
    "description": (
        "Emit structured ferry/train/bus/private-van transport options for one trip leg. "
        "Emit every distinct real option found across viable modes — not a single best pick. "
        "Every option must include at least one citation with a concrete claim and source URL. "
        "Leave estimated_price_amount null when no source states a price — never invent one."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "options": {
                "type": "array",
                "description": (
                    "Every distinct real transport option between the given origin and "
                    "destination across viable modes. No target count — one real ferry is "
                    "one option; ferry + bus + van is three. Do not invent options to pad."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": [m.value for m in TransportMode],
                            "description": "Transport mode for this option.",
                        },
                        "operator_name": {
                            "type": ["string", "null"],
                            "description": (
                                "Operator or company name when the source names one; "
                                "null when not stated."
                            ),
                        },
                        "departure_point": {
                            "type": "string",
                            "description": (
                                "Free-text departure point, e.g. 'Rassada Pier, Phuket'."
                            ),
                        },
                        "arrival_point": {
                            "type": "string",
                            "description": "Free-text arrival point.",
                        },
                        "estimated_duration_minutes": {
                            "type": ["integer", "null"],
                            "description": (
                                "Duration in minutes when a source states it; null when "
                                "unknown — do not invent a duration."
                            ),
                        },
                        "estimated_price_amount": {
                            "type": ["number", "string", "null"],
                            "description": (
                                "A single numeric point estimate when a source states a price "
                                "(no currency symbol, no commas, no ranges). If the source shows "
                                "a range, put one representative number here. Null when no source "
                                "states a price — do not estimate or invent a typical fare."
                            ),
                        },
                        "estimated_price_currency": {
                            "type": ["string", "null"],
                            "description": (
                                "ISO 4217 currency code as shown on the source when a price is "
                                "present; null iff estimated_price_amount is null."
                            ),
                        },
                        "booking_url": {
                            "type": ["string", "null"],
                            "description": (
                                "Best-effort booking or info URL from a source, or null when "
                                "none is available."
                            ),
                        },
                        "citations": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "claim_text": {
                                        "type": "string",
                                        "description": (
                                            "The specific claim this source supports "
                                            "(route/operator/mode at minimum; price when stated)."
                                        ),
                                    },
                                    "source_url": {
                                        "type": "string",
                                        "description": "URL of the page that supports the claim.",
                                    },
                                },
                                "required": ["claim_text", "source_url"],
                            },
                        },
                    },
                    "required": [
                        "mode",
                        "departure_point",
                        "arrival_point",
                        "citations",
                    ],
                },
            }
        },
        "required": ["options"],
    },
}


class TransportAgentError(AppError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(502, "upstream_api_error", message, details=details)


class _CitationEmit(BaseModel):
    claim_text: str = Field(min_length=1)
    source_url: str = Field(min_length=1)


class _TransportEmit(BaseModel):
    mode: TransportMode
    operator_name: str | None = None
    departure_point: str = Field(min_length=1)
    arrival_point: str = Field(min_length=1)
    estimated_duration_minutes: int | None = None
    estimated_price_amount: Decimal | None = None
    estimated_price_currency: str | None = None
    booking_url: str | None = None
    citations: list[_CitationEmit] = Field(min_length=1)

    @field_validator("operator_name", "booking_url", mode="before")
    @classmethod
    def empty_str_as_none(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator("estimated_price_currency", mode="before")
    @classmethod
    def currency_normalize(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip().upper()
            return stripped or None
        return value

    @field_validator("estimated_price_amount", mode="before")
    @classmethod
    def coerce_price(cls, value: object) -> object:
        return coerce_estimated_price_amount(value)

    @model_validator(mode="after")
    def price_and_currency_together(self) -> _TransportEmit:
        has_price = self.estimated_price_amount is not None
        has_currency = self.estimated_price_currency is not None
        if has_price != has_currency:
            raise ValueError(
                "estimated_price_currency must be null iff estimated_price_amount is null"
            )
        if self.estimated_price_currency is not None and len(self.estimated_price_currency) != 3:
            raise ValueError("estimated_price_currency must be a 3-letter ISO code")
        return self


class _EmitTransportInput(BaseModel):
    options: list[object]


def _client() -> AsyncAnthropic:
    if not settings.anthropic_api_key:
        raise TransportAgentError("ANTHROPIC_API_KEY is not configured")
    return AsyncAnthropic(api_key=settings.anthropic_api_key)


def _message_to_dict(message: Message) -> dict[str, object]:
    return message.model_dump(mode="json")


def _research_prompt(
    *,
    origin: str,
    destination: str,
    start_date: date,
    end_date: date,
    home_currency: str,
) -> str:
    # Origin/destination/dates/currency are structured wizard input but still untrusted
    # for prompt injection (.cursorrules §7) — wrap in delimiters.
    return (
        "You are researching real ferry, train, bus, and private-van transport options "
        "between two specific places on a group trip. Use web_search to gather current "
        "sources.\n\n"
        "Requirements:\n"
        "- Search across EVERY viable mode for this leg — ferry, train, bus, and "
        "private van — not just whichever mode you find first. The goal is a real "
        "comparison set across modes, not one 'best' answer.\n"
        "- Return EVERY distinct real option you find. Do not narrow down to a single "
        "recommendation. If a mode genuinely does not apply to this route (e.g. no rail "
        "line to an island), simply omit that mode — do not force a result for a mode "
        "that has none.\n"
        "- There is no target count. Cover what is real for this route; do not manufacture "
        "options to hit a number. One real ferry operator → one option; a ferry, a bus, "
        "and a private van → all three.\n"
        "- Find options that actually go from this origin to this destination (or the "
        "connecting piers/stations for that route) — not general transport advice about "
        "the region.\n"
        "- Capture operator name (when stated), departure/arrival points, duration "
        "(estimated_duration_minutes whenever a source states it — leave null when "
        "unknown, same as price), price, and a booking link WHEN A SOURCE STATES ONE.\n"
        "- Do NOT estimate, invent, or infer a 'typical' price when no source gives one. "
        "A real option with no discoverable online price is more useful and more honest "
        "than a plausible-sounding uncited number — leave the price unknown for the "
        "extraction step.\n"
        "- Record source URLs and the specific claims they support — a later extraction "
        "step will need citations for every option (route/operator/mode at minimum).\n"
        "- Do NOT convert currencies; keep prices exactly as each source states them.\n"
        "- When a source states multiple currencies, prefer quoting the price in the trip "
        "home currency "
        f"<home_currency>{home_currency}</home_currency> "
        "(preference among currencies already offered — never convert).\n\n"
        f"Origin: <origin>{origin}</origin>\n"
        f"Destination: <destination>{destination}</destination>\n"
        f"Travel window: <start_date>{start_date.isoformat()}</start_date> to "
        f"<end_date>{end_date.isoformat()}</end_date>.\n"
    )


def _extraction_prompt() -> str:
    return (
        "Extract structured transport options from your research above.\n"
        "Call the emit_transport_options tool exactly once.\n"
        "Rules:\n"
        "- Emit EVERY distinct real option from the research across viable modes "
        "(ferry/train/bus/private_van). Do not collapse to one 'best' option. Do not "
        "invent options to pad a count — no target number.\n"
        "- Omit modes that have no real option for this route.\n"
        "- Every option MUST have at least one citation (claim_text + source_url), "
        "including options with no price — cite the route/operator/mode claim.\n"
        "- estimated_price_amount must be a single numeric point estimate when a source "
        "states a price (no ranges, no currency symbols). If the source shows a range, "
        "put one representative number in estimated_price_amount.\n"
        "- If no source states a price, set estimated_price_amount and "
        "estimated_price_currency to null. Do not invent a fare.\n"
        "- estimated_price_currency is null iff estimated_price_amount is null; when "
        "present it must match the source — never convert currencies.\n"
        "- estimated_duration_minutes: set when a source states duration; null when "
        "unknown — same nullable treatment as price; do not invent a duration.\n"
        "- booking_url may be null when no bookable link appears on a source.\n"
        "- mode must be one of: ferry, train, bus, private_van, other.\n"
        "- operator_name may be null when the source does not name an operator.\n"
    )


def _correction_prompt(error_message: str) -> str:
    return (
        "Your previous emit_transport_options tool call was invalid and was rejected.\n"
        f"Validation error: <validation_error>{error_message}</validation_error>\n"
        "Call emit_transport_options again with a corrected payload. Every option still "
        "needs ≥1 citation. Leave price null when no source stated one — do not invent "
        "fares. estimated_price_currency must be null iff estimated_price_amount is null. "
        "Do not convert currencies."
    )


def _find_emit_tool_use(message: Message) -> ToolUseBlock | None:
    for block in message.content:
        if isinstance(block, ToolUseBlock) and block.name == _EMIT_TRANSPORT_TOOL_NAME:
            return block
    return None


def _to_parsed(option: _TransportEmit) -> ParsedTransportOption:
    return ParsedTransportOption(
        mode=option.mode.value,
        operator_name=option.operator_name.strip() if option.operator_name else None,
        departure_point=option.departure_point.strip(),
        arrival_point=option.arrival_point.strip(),
        estimated_duration_minutes=option.estimated_duration_minutes,
        estimated_price_amount=option.estimated_price_amount,
        estimated_price_currency=option.estimated_price_currency,
        booking_url=option.booking_url.strip() if option.booking_url else None,
        citations=[
            ParsedCitation(claim_text=c.claim_text.strip(), source_url=c.source_url.strip())
            for c in option.citations
        ],
    )


def parse_emit_transport_payload(
    tool_input: object,
) -> tuple[list[ParsedTransportOption], list[str]]:
    """Validate emit_transport_options tool input.

    Drop per-option schema failures (including zero citations); raise on batch malformation.
    A missing/null price is valid and is not dropped.
    """
    try:
        batch = _EmitTransportInput.model_validate(tool_input)
    except ValidationError:
        raise

    parsed: list[ParsedTransportOption] = []
    drop_reasons: list[str] = []
    for index, raw in enumerate(batch.options):
        try:
            option = _TransportEmit.model_validate(raw)
        except ValidationError as exc:
            reason = exc.errors()[0].get("msg", "invalid")
            drop_reasons.append(f"option[{index}]: {reason}")
            logger.info("transport_schema_drop index=%s reason=%s", index, reason)
            continue
        parsed.append(_to_parsed(option))
    return parsed, drop_reasons


async def _research_call(
    client: AsyncAnthropic,
    *,
    prompt: str,
    trace_id: str | None,
) -> Message:
    try:
        return await client.messages.create(
            model=settings.anthropic_activities_model,
            max_tokens=settings.anthropic_activities_max_tokens,
            messages=[{"role": "user", "content": prompt}],
            tools=[
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": settings.anthropic_web_search_max_uses,
                }
            ],
        )
    except APIError as exc:
        logger.error(
            "transport_research_api_error trace_id=%s status=%s",
            trace_id,
            getattr(exc, "status_code", None),
        )
        raise TransportAgentError(
            "Anthropic research call failed",
            details={"trace_id": trace_id, "error": str(exc)},
        ) from exc


async def _extraction_call(
    client: AsyncAnthropic,
    *,
    research_message: Message,
    research_user_prompt: str,
    extra_user_prompt: str,
    trace_id: str | None,
) -> Message:
    try:
        return await client.messages.create(
            model=settings.anthropic_activities_model,
            max_tokens=settings.anthropic_activities_max_tokens,
            messages=[
                {"role": "user", "content": research_user_prompt},
                {"role": "assistant", "content": research_message.content},
                {"role": "user", "content": extra_user_prompt},
            ],
            tools=[_EMIT_TRANSPORT_TOOL],
            tool_choice={"type": "tool", "name": _EMIT_TRANSPORT_TOOL_NAME},
        )
    except APIError as exc:
        logger.error(
            "transport_extraction_api_error trace_id=%s status=%s",
            trace_id,
            getattr(exc, "status_code", None),
        )
        raise TransportAgentError(
            "Anthropic extraction call failed",
            details={"trace_id": trace_id, "error": str(exc)},
        ) from exc


def _extract_validated_options(
    extraction_message: Message,
) -> tuple[list[ParsedTransportOption], dict[str, object] | None, str | None]:
    """Returns (options, tool_input_dict_or_none, batch_error_or_none)."""
    tool_use = _find_emit_tool_use(extraction_message)
    if tool_use is None:
        return [], None, "extraction response missing emit_transport_options tool_use block"

    tool_input = tool_use.input
    tool_input_dict: dict[str, object] = (
        tool_input if isinstance(tool_input, dict) else {"raw": tool_input}
    )
    try:
        options, _drop_reasons = parse_emit_transport_payload(tool_input)
    except ValidationError as exc:
        return [], tool_input_dict, f"batch schema invalid: {exc.errors()}"
    return options, tool_input_dict, None


async def research_transport(
    *,
    origin: str,
    destination: str,
    start_date: date,
    end_date: date,
    home_currency: str,
    leg_id: UUID | None = None,
    trace_id: str | None = None,
) -> TransportResearchParsed:
    """Run the two-call transport agent. Pure — never writes to the database."""
    client = _client()
    currency = home_currency.strip().upper()
    research_user_prompt = _research_prompt(
        origin=origin,
        destination=destination,
        start_date=start_date,
        end_date=end_date,
        home_currency=currency,
    )

    logger.info(
        "transport_research_start trace_id=%s leg_id=%s origin=%s destination=%s "
        "home_currency=%s",
        trace_id,
        leg_id,
        origin,
        destination,
        currency,
    )
    research_message = await _research_call(
        client,
        prompt=research_user_prompt,
        trace_id=trace_id,
    )

    extraction_attempts: list[dict[str, object]] = []
    options: list[ParsedTransportOption] = []
    extraction_failed = False
    extraction_error: str | None = None
    max_attempts = 1 + settings.anthropic_activities_max_retries
    next_user_prompt = _extraction_prompt()

    for attempt in range(1, max_attempts + 1):
        extraction_message = await _extraction_call(
            client,
            research_message=research_message,
            research_user_prompt=research_user_prompt,
            extra_user_prompt=next_user_prompt,
            trace_id=trace_id,
        )
        options, tool_input_dict, batch_error = _extract_validated_options(extraction_message)
        extraction_attempts.append(
            {
                "attempt": attempt,
                "message": _message_to_dict(extraction_message),
                "tool_input": tool_input_dict,
                "batch_error": batch_error,
            }
        )
        if batch_error is None:
            extraction_failed = False
            extraction_error = None
            break

        extraction_failed = True
        extraction_error = batch_error
        logger.warning(
            "transport_extraction_batch_invalid trace_id=%s attempt=%s error=%s",
            trace_id,
            attempt,
            batch_error,
        )
        if attempt >= max_attempts:
            break
        next_user_prompt = _correction_prompt(batch_error)

    request_params: dict[str, object] = {
        "research_type": "transport",
        "origin": origin,
        "destination": destination,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "home_currency": currency,
        "leg_id": str(leg_id) if leg_id else None,
        "model": settings.anthropic_activities_model,
        "web_search_max_uses": settings.anthropic_web_search_max_uses,
        "max_retries": settings.anthropic_activities_max_retries,
    }
    response_body: dict[str, object] = {
        "research": _message_to_dict(research_message),
        "extraction_attempts": extraction_attempts,
    }

    logger.info(
        "transport_research_done trace_id=%s leg_id=%s valid_count=%s extraction_failed=%s",
        trace_id,
        leg_id,
        len(options),
        extraction_failed,
    )
    return TransportResearchParsed(
        request_params=request_params,
        response_body=response_body,
        options=options,
        extraction_failed=extraction_failed,
        extraction_error=extraction_error,
    )
