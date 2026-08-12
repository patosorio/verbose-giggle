"""URL-import agent — plain httpx fetch + one Claude extraction call, no DB writes.

docs/01_architecture.md §4.4: fetch → tool_choice-forced emit_imported_option.
Unlike activities/transport, there is no web_search research call — page content is
already in hand from fetch_page. Raw HTML is passed through (no parsing library);
truncation is the token-cost bound.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import httpx
from anthropic import APIError, AsyncAnthropic
from anthropic.types import Message, ToolUseBlock
from pydantic import BaseModel, ValidationError, field_validator, model_validator

from core.config import settings
from core.errors import AppError
from research.types import (
    ImportedOptionParsed,
    ParsedImportedOption,
    coerce_estimated_price_amount,
)

logger = logging.getLogger(__name__)

_EMIT_IMPORTED_TOOL_NAME = "emit_imported_option"
_FETCH_TIMEOUT_SECONDS = 15.0
# Raw HTML is noisier per useful token than stripped text was, so the cap is higher
# than the old 20k stripped-text bound — truncation (not preprocessing) is what
# actually limits worst-case prompt cost (docs/01_architecture.md §4.4).
_MAX_PAGE_CHARS = 40_000

_EMIT_IMPORTED_OPTION_TOOL: dict[str, object] = {
    "name": _EMIT_IMPORTED_TOOL_NAME,
    "description": (
        "Emit one structured trip-option suggestion extracted from a fetched web page. "
        "Leave estimated_price_amount null when the page does not clearly state a price — "
        "never fabricate a price to fill the field. When a price is set, "
        "price_supporting_quote must be a literal quote from the page text that states it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short, usable name for the suggested option.",
            },
            "description": {
                "type": ["string", "null"],
                "description": "Optional short description from the page, or null.",
            },
            "category_hint": {
                "type": ["string", "null"],
                "description": (
                    "Free-text display hint only (e.g. 'restaurant', 'boat tour') — "
                    "never used for tier or pricing logic."
                ),
            },
            "estimated_price_amount": {
                "type": ["number", "string", "null"],
                "description": (
                    "A single numeric point estimate when the page clearly states a price "
                    "(no currency symbol, no commas, no ranges). Null when the page does "
                    "not clearly state one — do not invent a price."
                ),
            },
            "estimated_price_currency": {
                "type": ["string", "null"],
                "description": (
                    "ISO 4217 currency code when a price is present; null iff "
                    "estimated_price_amount is null."
                ),
            },
            "price_supporting_quote": {
                "type": ["string", "null"],
                "description": (
                    "Literal quote from the fetched page text that states the price. "
                    "Required whenever estimated_price_amount is non-null; null when "
                    "price is null."
                ),
            },
        },
        "required": ["title"],
    },
}


class ImportAgentError(AppError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(status_code, code, message, details=details)


class _ImportedEmit(BaseModel):
    title: str
    description: str | None = None
    category_hint: str | None = None
    estimated_price_amount: Decimal | None = None
    estimated_price_currency: str | None = None
    price_supporting_quote: str | None = None

    @field_validator("description", "category_hint", "price_supporting_quote", mode="before")
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
    def price_and_currency_together(self) -> _ImportedEmit:
        has_price = self.estimated_price_amount is not None
        has_currency = self.estimated_price_currency is not None
        if has_price != has_currency:
            raise ValueError(
                "estimated_price_currency must be null iff estimated_price_amount is null"
            )
        if self.estimated_price_currency is not None and len(self.estimated_price_currency) != 3:
            raise ValueError("estimated_price_currency must be a 3-letter ISO code")
        return self


async def fetch_page(url: str) -> str:
    """Fetch URL and return raw response body truncated for the Claude prompt.

    Raises ImportAgentError(502, upstream_api_error) on network/timeout/non-2xx
    (docs/01_architecture.md §4.4 — plain fetch for v1, fail clearly).
    """
    try:
        async with httpx.AsyncClient(
            timeout=_FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        logger.error("import_fetch_http_error url=%s error=%s", url, exc)
        raise ImportAgentError(
            502,
            "upstream_api_error",
            "Failed to fetch URL for import",
            details={"url": url, "error": str(exc)},
        ) from exc

    if response.status_code < 200 or response.status_code >= 300:
        logger.error(
            "import_fetch_non_2xx url=%s status=%s",
            url,
            response.status_code,
        )
        raise ImportAgentError(
            502,
            "upstream_api_error",
            f"URL fetch returned HTTP {response.status_code}",
            details={"url": url, "status_code": response.status_code},
        )

    return response.text[:_MAX_PAGE_CHARS]


def _client() -> AsyncAnthropic:
    if not settings.anthropic_api_key:
        raise ImportAgentError(
            502,
            "upstream_api_error",
            "ANTHROPIC_API_KEY is not configured",
        )
    return AsyncAnthropic(api_key=settings.anthropic_api_key)


def _message_to_dict(message: Message) -> dict[str, object]:
    return message.model_dump(mode="json")


def _extraction_prompt(*, url: str, page_content: str) -> str:
    # URL and page content are untrusted (.cursorrules §7) — wrap in delimiters.
    return (
        "Extract one structured trip-option suggestion from the fetched page content.\n"
        "Call the emit_imported_option tool exactly once.\n"
        "Rules:\n"
        "- title must be a useful non-empty name for the option.\n"
        "- Leave estimated_price_amount null when the page does not clearly state a "
        "price — never fabricate a price.\n"
        "- When estimated_price_amount is set, price_supporting_quote must be a literal "
        "quote from the page content that states that price.\n"
        "- estimated_price_currency is null iff estimated_price_amount is null; when "
        "present it must be ISO 4217 as shown on the page — never convert currencies.\n"
        "- category_hint is free text for display only.\n\n"
        f"Source URL: <source_url>{url}</source_url>\n"
        f"Page content:\n<page_content>\n{page_content}\n</page_content>\n"
    )


def _find_emit_tool_use(message: Message) -> ToolUseBlock | None:
    for block in message.content:
        if isinstance(block, ToolUseBlock) and block.name == _EMIT_IMPORTED_TOOL_NAME:
            return block
    return None


def _apply_price_quote_downgrade(emit: _ImportedEmit) -> ParsedImportedOption:
    """Drop unsupported price rather than rejecting the whole extraction.

    docs/01_architecture.md §4.4 point 3 — Python-side rule, not the model's.
    """
    amount = emit.estimated_price_amount
    currency = emit.estimated_price_currency
    quote = emit.price_supporting_quote
    if amount is not None and (quote is None or not quote.strip()):
        amount = None
        currency = None
        quote = None
    return ParsedImportedOption(
        title=emit.title.strip(),
        description=emit.description.strip() if emit.description else None,
        category_hint=emit.category_hint.strip() if emit.category_hint else None,
        estimated_price_amount=amount,
        estimated_price_currency=currency,
        price_supporting_quote=quote.strip() if quote else None,
    )


def parse_emit_imported_payload(
    tool_input: object,
) -> tuple[ParsedImportedOption | None, str | None]:
    """Validate emit_imported_option tool input.

    Returns (parsed, error). Empty/whitespace-only title → error (extraction_failed).
    Price without supporting quote is downgraded to null, not an error.
    """
    try:
        emit = _ImportedEmit.model_validate(tool_input)
    except ValidationError as exc:
        return None, f"emit schema invalid: {exc.errors()}"

    if not emit.title.strip():
        return None, "title is empty or whitespace-only"

    return _apply_price_quote_downgrade(emit), None


async def _extraction_call(
    client: AsyncAnthropic,
    *,
    prompt: str,
) -> Message:
    try:
        return await client.messages.create(
            model=settings.anthropic_activities_model,
            max_tokens=settings.anthropic_activities_max_tokens,
            messages=[{"role": "user", "content": prompt}],
            tools=[_EMIT_IMPORTED_OPTION_TOOL],
            tool_choice={"type": "tool", "name": _EMIT_IMPORTED_TOOL_NAME},
        )
    except APIError as exc:
        logger.error(
            "import_extraction_api_error status=%s",
            getattr(exc, "status_code", None),
        )
        raise ImportAgentError(
            502,
            "upstream_api_error",
            "Anthropic extraction call failed",
            details={"error": str(exc)},
        ) from exc


async def research_imported_option(url: str) -> ImportedOptionParsed:
    """Fetch page + one extraction call. Pure — never writes to the database."""
    page_content = await fetch_page(url)
    client = _client()
    prompt = _extraction_prompt(url=url, page_content=page_content)

    logger.info("import_research_start url=%s page_chars=%s", url, len(page_content))
    extraction_message = await _extraction_call(client, prompt=prompt)

    tool_use = _find_emit_tool_use(extraction_message)
    tool_input_dict: dict[str, object] | None = None
    option: ParsedImportedOption | None = None
    extraction_failed = False
    extraction_error: str | None = None

    if tool_use is None:
        extraction_failed = True
        extraction_error = "extraction response missing emit_imported_option tool_use block"
    else:
        tool_input = tool_use.input
        tool_input_dict = tool_input if isinstance(tool_input, dict) else {"raw": tool_input}
        option, extraction_error = parse_emit_imported_payload(tool_input)
        if extraction_error is not None:
            extraction_failed = True
            option = None

    request_params: dict[str, object] = {
        "research_type": "url_import",
        "url": url,
        "model": settings.anthropic_activities_model,
        "max_page_chars": _MAX_PAGE_CHARS,
    }
    response_body: dict[str, object] = {
        "page_text": page_content,
        "extraction": _message_to_dict(extraction_message),
        "tool_input": tool_input_dict,
    }

    logger.info(
        "import_research_done url=%s extraction_failed=%s has_price=%s",
        url,
        extraction_failed,
        option.estimated_price_amount is not None if option else False,
    )
    return ImportedOptionParsed(
        request_params=request_params,
        response_body=response_body,
        source_url=url,
        option=option,
        extraction_failed=extraction_failed,
        extraction_error=extraction_error,
    )
