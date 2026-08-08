"""Activities research agent — two Anthropic API calls, no DB writes.

Pattern: docs/01_architecture.md §5.
1. Research call — web_search enabled, bounded by max_uses.
2. Extraction call — tool_choice forced to emit_activities; Python validates.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from anthropic import APIError, AsyncAnthropic
from anthropic.types import Message, ToolUseBlock
from pydantic import BaseModel, Field, ValidationError, field_validator

from core.config import settings
from core.errors import AppError
from research.types import (
    ActivitiesResearchParsed,
    ParsedActivityOption,
    ParsedCitation,
    SuggestedTiming,
    coerce_estimated_price_amount,
)

logger = logging.getLogger(__name__)

_EMIT_ACTIVITIES_TOOL_NAME = "emit_activities"

_EMIT_ACTIVITIES_TOOL: dict[str, object] = {
    "name": _EMIT_ACTIVITIES_TOOL_NAME,
    "description": (
        "Emit structured activity options for one trip leg. Every activity must include "
        "at least one citation with a concrete claim and source URL."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "activities": {
                "type": "array",
                "description": "Distinct activity suggestions (aim for 6–9 spanning a price range).",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": (
                                "Short display title for the option card, e.g. "
                                "'Sunset Kayaking Tour in Koh Yao Noi'."
                            ),
                        },
                        "category": {
                            "type": "string",
                            "description": "Free-text category, e.g. boat tour, cooking class.",
                        },
                        "description": {
                            "type": "string",
                            "description": (
                                "What the activity is and why it fits this destination. "
                                "If the source lists a price range, disclose that range here "
                                "(e.g. 'typically 1,000–1,500 THB') — never put a range in "
                                "estimated_price_amount."
                            ),
                        },
                        "duration_minutes": {
                            "type": ["integer", "null"],
                            "description": "Typical duration in minutes, or null if unknown.",
                        },
                        "estimated_price_amount": {
                            "type": ["number", "string"],
                            "description": (
                                "A single numeric point estimate for the price (no currency "
                                "symbol, no commas, no ranges). If the source shows a range, "
                                "put one representative number here and disclose the full "
                                "range in description instead. Do not convert currencies."
                            ),
                        },
                        "estimated_price_currency": {
                            "type": "string",
                            "description": "ISO 4217 currency code as shown on the source (e.g. THB, USD).",
                        },
                        "suggested_timing": {
                            "type": "string",
                            "enum": ["arrival_day", "departure_day", "flexible"],
                            "description": (
                                "When this activity is best scheduled relative to the leg's "
                                "transfer days: arrival_day, departure_day, or flexible."
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
                                        "description": "The specific claim this source supports.",
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
                        "title",
                        "category",
                        "description",
                        "estimated_price_amount",
                        "estimated_price_currency",
                        "suggested_timing",
                        "citations",
                    ],
                },
            }
        },
        "required": ["activities"],
    },
}


class ActivitiesAgentError(AppError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(502, "upstream_api_error", message, details=details)


class _CitationEmit(BaseModel):
    claim_text: str = Field(min_length=1)
    source_url: str = Field(min_length=1)


class _ActivityEmit(BaseModel):
    title: str = Field(min_length=1)
    category: str = Field(min_length=1)
    description: str = Field(min_length=1)
    duration_minutes: int | None = None
    estimated_price_amount: Decimal
    estimated_price_currency: str = Field(min_length=3, max_length=3)
    suggested_timing: SuggestedTiming
    citations: list[_CitationEmit] = Field(min_length=1)

    @field_validator("estimated_price_currency", mode="before")
    @classmethod
    def currency_upper(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("estimated_price_amount", mode="before")
    @classmethod
    def coerce_price(cls, value: object) -> object:
        coerced = coerce_estimated_price_amount(value)
        if coerced is None:
            raise ValueError("estimated_price_amount is required")
        return coerced


class _EmitActivitiesInput(BaseModel):
    activities: list[object]


def _client() -> AsyncAnthropic:
    if not settings.anthropic_api_key:
        raise ActivitiesAgentError("ANTHROPIC_API_KEY is not configured")
    return AsyncAnthropic(api_key=settings.anthropic_api_key)


def _message_to_dict(message: Message) -> dict[str, object]:
    return message.model_dump(mode="json")


def _research_prompt(
    *,
    destination: str,
    start_date: date,
    end_date: date,
    nights: int,
    home_currency: str,
) -> str:
    # Destination/dates/currency are structured wizard input but still untrusted for
    # prompt injection (.cursorrules §7) — wrap in delimiters rather than interpolating raw.
    return (
        "You are researching real, bookable or visit-worthy activities for one stop on a "
        "group trip. Use web_search to gather current sources.\n\n"
        "Requirements:\n"
        "- Find 6–9 DISTINCT activities (not near-duplicates of the same tour).\n"
        "- Span a real price range (cheap / mid / pricey) so tiering does not collapse.\n"
        "- Prefer sources that state a concrete price and currency.\n"
        "- Record source URLs and the specific claims they support — a later extraction "
        "step will need citations.\n"
        "- Do NOT convert currencies; keep prices exactly as each source states them.\n"
        "- When a source states multiple currencies, prefer quoting the price in the trip "
        "home currency "
        f"<home_currency>{home_currency}</home_currency> "
        "(preference among currencies already offered — never convert).\n\n"
        f"Destination: <destination>{destination}</destination>\n"
        f"Stay: <start_date>{start_date.isoformat()}</start_date> to "
        f"<end_date>{end_date.isoformat()}</end_date> "
        f"(<nights>{nights}</nights> nights).\n"
    )


def _extraction_prompt() -> str:
    return (
        "Extract structured activities from your research above.\n"
        "Call the emit_activities tool exactly once.\n"
        "Rules:\n"
        "- Aim for 6–9 distinct activities spanning a price range.\n"
        "- Every activity MUST have at least one citation (claim_text + source_url).\n"
        "- estimated_price_amount must be a single numeric point estimate (no ranges, "
        "no currency symbols). If the source shows a range, put one representative number "
        "in estimated_price_amount and disclose the full range in description.\n"
        "- estimated_price_currency must match the source — never convert currencies.\n"
        "- title is a concise display label for a card UI.\n"
        "- suggested_timing must be one of: arrival_day, departure_day, flexible.\n"
        "- duration_minutes may be null when unknown.\n"
    )


def _correction_prompt(error_message: str) -> str:
    return (
        "Your previous emit_activities tool call was invalid and was rejected.\n"
        f"Validation error: <validation_error>{error_message}</validation_error>\n"
        "Call emit_activities again with a corrected payload. Every activity still needs "
        "≥1 citation. estimated_price_amount must be a single number (put any source range "
        "in description). Do not convert currencies."
    )


def _find_emit_tool_use(message: Message) -> ToolUseBlock | None:
    for block in message.content:
        if isinstance(block, ToolUseBlock) and block.name == _EMIT_ACTIVITIES_TOOL_NAME:
            return block
    return None


def _to_parsed(activity: _ActivityEmit) -> ParsedActivityOption:
    return ParsedActivityOption(
        title=activity.title.strip(),
        category=activity.category.strip(),
        description=activity.description.strip(),
        duration_minutes=activity.duration_minutes,
        estimated_price_amount=activity.estimated_price_amount,
        estimated_price_currency=activity.estimated_price_currency,
        citations=[
            ParsedCitation(claim_text=c.claim_text.strip(), source_url=c.source_url.strip())
            for c in activity.citations
        ],
        suggested_timing=activity.suggested_timing,
    )


def parse_emit_activities_payload(
    tool_input: object,
) -> tuple[list[ParsedActivityOption], list[str]]:
    """Validate emit_activities tool input. Drop per-activity failures; raise on batch malformation.

    Zero citations (or other schema violations) on a single activity → drop that activity.
    Missing/malformed top-level shape → ValidationError (batch-level, eligible for correction retry).
    """
    try:
        batch = _EmitActivitiesInput.model_validate(tool_input)
    except ValidationError:
        raise

    parsed: list[ParsedActivityOption] = []
    drop_reasons: list[str] = []
    for index, raw in enumerate(batch.activities):
        try:
            activity = _ActivityEmit.model_validate(raw)
        except ValidationError as exc:
            reason = exc.errors()[0].get("msg", "invalid")
            drop_reasons.append(f"activity[{index}]: {reason}")
            logger.info("activities_schema_drop index=%s reason=%s", index, reason)
            continue
        parsed.append(_to_parsed(activity))
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
            "activities_research_api_error trace_id=%s status=%s",
            trace_id,
            getattr(exc, "status_code", None),
        )
        raise ActivitiesAgentError(
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
            tools=[_EMIT_ACTIVITIES_TOOL],
            tool_choice={"type": "tool", "name": _EMIT_ACTIVITIES_TOOL_NAME},
        )
    except APIError as exc:
        logger.error(
            "activities_extraction_api_error trace_id=%s status=%s",
            trace_id,
            getattr(exc, "status_code", None),
        )
        raise ActivitiesAgentError(
            "Anthropic extraction call failed",
            details={"trace_id": trace_id, "error": str(exc)},
        ) from exc


def _extract_validated_activities(
    extraction_message: Message,
) -> tuple[list[ParsedActivityOption], dict[str, object] | None, str | None]:
    """Returns (activities, tool_input_dict_or_none, batch_error_or_none)."""
    tool_use = _find_emit_tool_use(extraction_message)
    if tool_use is None:
        return [], None, "extraction response missing emit_activities tool_use block"

    tool_input = tool_use.input
    tool_input_dict: dict[str, object] = (
        tool_input if isinstance(tool_input, dict) else {"raw": tool_input}
    )
    try:
        activities, _drop_reasons = parse_emit_activities_payload(tool_input)
    except ValidationError as exc:
        return [], tool_input_dict, f"batch schema invalid: {exc.errors()}"
    return activities, tool_input_dict, None


async def research_activities(
    *,
    destination: str,
    start_date: date,
    end_date: date,
    nights: int,
    home_currency: str,
    leg_id: UUID | None = None,
    trace_id: str | None = None,
) -> ActivitiesResearchParsed:
    """Run the two-call activities agent. Pure — never writes to the database."""
    client = _client()
    currency = home_currency.strip().upper()
    research_user_prompt = _research_prompt(
        destination=destination,
        start_date=start_date,
        end_date=end_date,
        nights=nights,
        home_currency=currency,
    )

    logger.info(
        "activities_research_start trace_id=%s leg_id=%s destination=%s home_currency=%s",
        trace_id,
        leg_id,
        destination,
        currency,
    )
    research_message = await _research_call(
        client,
        prompt=research_user_prompt,
        trace_id=trace_id,
    )

    extraction_attempts: list[dict[str, object]] = []
    activities: list[ParsedActivityOption] = []
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
        activities, tool_input_dict, batch_error = _extract_validated_activities(
            extraction_message
        )
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
            "activities_extraction_batch_invalid trace_id=%s attempt=%s error=%s",
            trace_id,
            attempt,
            batch_error,
        )
        if attempt >= max_attempts:
            break
        next_user_prompt = _correction_prompt(batch_error)

    request_params: dict[str, object] = {
        "destination": destination,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "nights": nights,
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
        "activities_research_done trace_id=%s leg_id=%s valid_count=%s extraction_failed=%s",
        trace_id,
        leg_id,
        len(activities),
        extraction_failed,
    )
    return ActivitiesResearchParsed(
        request_params=request_params,
        response_body=response_body,
        activities=activities,
        extraction_failed=extraction_failed,
        extraction_error=extraction_error,
    )
