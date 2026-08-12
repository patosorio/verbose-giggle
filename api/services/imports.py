"""URL-import and manual-entry persistence.

research/ never writes to the DB. This module owns RawApiResponse → OptionCard →
ImportedOption writes for URL-import (docs/01_architecture.md §4.4), and direct
OptionCard → ImportedOption writes for manual entry (§4.5 — no RawApiResponse).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import AppError
from db.models import (
    BudgetBand,
    ImportedOption,
    Leg,
    OptionCard,
    OptionType,
    RawApiResponse,
    RawApiSource,
    Trip,
)
from research.imports import ImportAgentError
from research.types import ImportedOptionParsed
from schemas.imports import ManualOptionIn
from schemas.options import ImportedOptionOut, ReactionSummaryOut

logger = logging.getLogger(__name__)


async def _trip_home_currency(session: AsyncSession, leg_id: UUID) -> str | None:
    result = await session.execute(
        select(Trip.home_currency).join(Leg, Leg.trip_id == Trip.id).where(Leg.id == leg_id)
    )
    return result.scalar_one_or_none()


def _card_currency_for_imported(
    *,
    price_amount: Decimal | None,
    price_currency: str | None,
    home_currency: str | None,
) -> str:
    """Price currency when priced; trip home_currency when price is null."""
    if price_amount is not None:
        assert price_currency is not None
        return price_currency
    return (home_currency or "XXX").upper()


def _imported_option_out(
    *,
    card: OptionCard,
    source_url: str | None,
    extracted_title: str,
    extracted_description: str | None,
    category_hint: str | None,
) -> ImportedOptionOut:
    return ImportedOptionOut(
        id=card.id,
        tier=card.tier,
        title=card.title,
        base_price_amount=card.base_price_amount,
        currency=card.currency,
        reaction_summary=ReactionSummaryOut(up=0, down=0, my_reaction=None),
        source_url=source_url,
        extracted_title=extracted_title,
        extracted_description=extracted_description,
        category_hint=category_hint,
    )


async def persist_imported_option(
    session: AsyncSession,
    *,
    leg_id: UUID,
    tier: BudgetBand,
    parsed: ImportedOptionParsed,
) -> ImportedOptionOut:
    """Persist RawApiResponse first, then OptionCard + ImportedOption on success.

    On extraction_failed: commit the raw row, then raise ImportAgentError(400,
    validation_error) so a failed import stays debuggable (docs/01_architecture.md §4.4).
    Tier is the caller's supplied value — not computed.
    """
    leg = await session.get(Leg, leg_id)
    if leg is None:
        raise ImportAgentError(404, "not_found", "Leg not found")

    raw = RawApiResponse(
        research_run_id=None,
        source=RawApiSource.claude_url_extract,
        request_params=parsed.request_params,
        response_body=parsed.response_body,
        fetched_at=datetime.now(UTC),
    )
    session.add(raw)
    await session.flush()

    if parsed.extraction_failed or parsed.option is None:
        await session.commit()
        raise ImportAgentError(
            400,
            "validation_error",
            "Could not extract a usable option from the URL",
            details={
                "leg_id": str(leg_id),
                "raw_response_id": str(raw.id),
                "url": parsed.source_url,
                "error": parsed.extraction_error,
            },
        )

    option = parsed.option
    home_currency = await _trip_home_currency(session, leg_id)
    card_currency = _card_currency_for_imported(
        price_amount=option.estimated_price_amount,
        price_currency=option.estimated_price_currency,
        home_currency=home_currency,
    )

    card = OptionCard(
        leg_id=leg_id,
        option_type=OptionType.imported,
        tier=tier,
        title=option.title,
        base_price_amount=option.estimated_price_amount,
        currency=card_currency,
        raw_response_id=raw.id,
        research_run_id=None,
    )
    session.add(card)
    await session.flush()
    session.add(
        ImportedOption(
            option_card_id=card.id,
            source_url=parsed.source_url,
            extracted_title=option.title,
            extracted_description=option.description,
            category_hint=option.category_hint,
            estimated_price_amount=option.estimated_price_amount,
            estimated_price_currency=option.estimated_price_currency,
        )
    )
    await session.commit()

    logger.info(
        "import_persisted leg_id=%s raw_id=%s card_id=%s tier=%s has_price=%s",
        leg_id,
        raw.id,
        card.id,
        tier.value,
        option.estimated_price_amount is not None,
    )
    return _imported_option_out(
        card=card,
        source_url=parsed.source_url,
        extracted_title=option.title,
        extracted_description=option.description,
        category_hint=option.category_hint,
    )


async def persist_manual_option(
    session: AsyncSession,
    *,
    leg_id: UUID,
    body: ManualOptionIn,
) -> ImportedOptionOut:
    """Persist a manually typed imported option — no RawApiResponse (architecture §4.5)."""
    leg = await session.get(Leg, leg_id)
    if leg is None:
        raise AppError(404, "not_found", "Leg not found")

    title = body.title.strip()
    if not title:
        raise AppError(400, "validation_error", "title must be non-empty")

    has_price = body.price_amount is not None
    has_currency = body.price_currency is not None
    if has_price != has_currency:
        raise AppError(
            400,
            "validation_error",
            "price_currency must be set iff price_amount is set",
        )

    home_currency = await _trip_home_currency(session, leg_id)
    card_currency = _card_currency_for_imported(
        price_amount=body.price_amount,
        price_currency=body.price_currency,
        home_currency=home_currency,
    )

    card = OptionCard(
        leg_id=leg_id,
        option_type=OptionType.imported,
        tier=body.tier,
        title=title,
        base_price_amount=body.price_amount,
        currency=card_currency,
        raw_response_id=None,
        research_run_id=None,
    )
    session.add(card)
    await session.flush()
    session.add(
        ImportedOption(
            option_card_id=card.id,
            source_url=None,
            extracted_title=title,
            extracted_description=body.description,
            category_hint=body.category_hint,
            estimated_price_amount=body.price_amount,
            estimated_price_currency=body.price_currency,
        )
    )
    await session.commit()

    logger.info(
        "manual_option_persisted leg_id=%s card_id=%s tier=%s has_price=%s",
        leg_id,
        card.id,
        body.tier.value,
        body.price_amount is not None,
    )
    return _imported_option_out(
        card=card,
        source_url=None,
        extracted_title=title,
        extracted_description=body.description,
        category_hint=body.category_hint,
    )
