"""Activities validation + persistence.

research/ never writes to the DB. This module owns citation/price/same-day checks
and RawApiResponse → OptionCard → ActivityOption → Citation writes
(docs/01_architecture.md §4.1, docs/04_build_plan.md Phase 3).
"""

from __future__ import annotations

import logging
import statistics
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    ActivityOption,
    BudgetBand,
    Citation,
    FlightOption,
    Leg,
    OptionCard,
    OptionType,
    RawApiResponse,
    RawApiSource,
    Trip,
)
from research.activities import ActivitiesAgentError
from research.tiering import assign_price_tiers
from research.types import ActivitiesResearchParsed, ParsedActivityOption, SuggestedTiming

logger = logging.getLogger(__name__)

# docs/04_build_plan.md Phase 3 — proxy for "not enough day left after transfer + airport time"
SAME_DAY_FLIGHT_DURATION_THRESHOLD_MINUTES = 300


def drop_missing_citations(
    activities: list[ParsedActivityOption],
) -> list[ParsedActivityOption]:
    """Hard gate: zero citations → drop (defense in depth; research schema also requires ≥1)."""
    kept: list[ParsedActivityOption] = []
    for activity in activities:
        if not activity.citations:
            logger.info(
                "activities_drop_missing_citations title=%s",
                activity.title,
            )
            continue
        kept.append(activity)
    return kept


def drop_implausible_prices(
    activities: list[ParsedActivityOption],
) -> list[ParsedActivityOption]:
    """Drop activities whose price is >10x or <1/10th the median of *other* same-currency peers.

    Per docs/04_build_plan.md Phase 3 — exclude self from the baseline median.
    Medians are never cross-currency (architecture: no FX conversion). When fewer
    than 2 other activities share this activity's currency, skip and log — do not
    silently pass or fall back to a mixed-currency comparison.
    """
    kept: list[ParsedActivityOption] = []
    for index, activity in enumerate(activities):
        currency = activity.estimated_price_currency.upper()
        others = [
            other.estimated_price_amount
            for j, other in enumerate(activities)
            if j != index and other.estimated_price_currency.upper() == currency
        ]
        if len(others) < 2:
            logger.info(
                "implausible-price check skipped, fewer than 2 same-currency peers "
                "title=%s currency=%s peer_count=%s",
                activity.title,
                currency,
                len(others),
            )
            kept.append(activity)
            continue

        median_price = Decimal(str(statistics.median(others)))
        if median_price == 0:
            # Avoid divide-by-zero; a zero median among peers is itself pathological — keep
            # only peers that are also zero rather than inventing an absolute bound.
            if activity.estimated_price_amount != 0:
                logger.info(
                    "activities_drop_implausible_price title=%s currency=%s "
                    "amount=%s median_others=0",
                    activity.title,
                    currency,
                    activity.estimated_price_amount,
                )
                continue
            kept.append(activity)
            continue

        ratio = activity.estimated_price_amount / median_price
        if ratio > 10 or ratio < Decimal("0.1"):
            logger.info(
                "activities_drop_implausible_price title=%s currency=%s "
                "amount=%s median_others=%s ratio=%s",
                activity.title,
                currency,
                activity.estimated_price_amount,
                median_price,
                ratio,
            )
            continue
        kept.append(activity)
    return kept


def drop_same_day_transfer_conflicts(
    activities: list[ParsedActivityOption],
    *,
    flight_duration_minutes: int | None,
    trace_id: str | None = None,
    leg_id: UUID | None = None,
) -> list[ParsedActivityOption]:
    """Flag/drop arrival_day/departure_day activities when flight duration > 300 minutes.

    When no FlightOption duration exists (ferry-only legs), skip entirely and log —
    do not silently treat "no data" as "check passed" (docs/04_build_plan.md Phase 3).
    """
    if flight_duration_minutes is None:
        logger.info(
            "same-day check skipped, no duration data trace_id=%s leg_id=%s",
            trace_id,
            leg_id,
        )
        return list(activities)

    if flight_duration_minutes <= SAME_DAY_FLIGHT_DURATION_THRESHOLD_MINUTES:
        return list(activities)

    kept: list[ParsedActivityOption] = []
    for activity in activities:
        if activity.suggested_timing in (
            SuggestedTiming.arrival_day,
            SuggestedTiming.departure_day,
        ):
            logger.info(
                "activities_drop_same_day_conflict title=%s timing=%s "
                "flight_duration_minutes=%s threshold=%s trace_id=%s leg_id=%s",
                activity.title,
                activity.suggested_timing.value,
                flight_duration_minutes,
                SAME_DAY_FLIGHT_DURATION_THRESHOLD_MINUTES,
                trace_id,
                leg_id,
            )
            continue
        kept.append(activity)
    return kept


def filter_activities_for_persistence(
    activities: list[ParsedActivityOption],
    *,
    flight_duration_minutes: int | None,
    trace_id: str | None = None,
    leg_id: UUID | None = None,
) -> list[ParsedActivityOption]:
    """Apply citation → price → same-day filters in that order."""
    after_citations = drop_missing_citations(activities)
    after_prices = drop_implausible_prices(after_citations)
    return drop_same_day_transfer_conflicts(
        after_prices,
        flight_duration_minutes=flight_duration_minutes,
        trace_id=trace_id,
        leg_id=leg_id,
    )


async def _shortest_flight_duration_minutes(
    session: AsyncSession,
    leg_id: UUID,
) -> int | None:
    result = await session.execute(
        select(FlightOption.duration_minutes)
        .join(OptionCard, OptionCard.id == FlightOption.option_card_id)
        .where(
            OptionCard.leg_id == leg_id,
            OptionCard.option_type == OptionType.flight,
        )
    )
    durations = list(result.scalars().all())
    if not durations:
        return None
    return min(durations)


async def _trip_home_currency(session: AsyncSession, leg_id: UUID) -> str | None:
    result = await session.execute(
        select(Trip.home_currency).join(Leg, Leg.trip_id == Trip.id).where(Leg.id == leg_id)
    )
    return result.scalar_one_or_none()


def _log_currency_mismatches(
    activities: list[ParsedActivityOption],
    *,
    home_currency: str | None,
    leg_id: UUID,
    trace_id: str | None,
) -> None:
    if not home_currency:
        return
    expected = home_currency.upper()
    for activity in activities:
        if activity.estimated_price_currency.upper() != expected:
            logger.warning(
                "activities_currency_mismatch leg_id=%s trace_id=%s title=%s "
                "home=%s found=%s — storing response currency as returned",
                leg_id,
                trace_id,
                activity.title,
                expected,
                activity.estimated_price_currency.upper(),
            )


async def _write_raw_response(
    session: AsyncSession,
    *,
    request_params: dict[str, object],
    response_body: dict[str, object],
    research_run_id: UUID | None,
) -> RawApiResponse:
    raw = RawApiResponse(
        research_run_id=research_run_id,
        source=RawApiSource.claude_web_search,
        request_params=request_params,
        response_body=response_body,
        fetched_at=datetime.now(UTC),
    )
    session.add(raw)
    await session.flush()
    return raw


async def _persist_activity_option(
    session: AsyncSession,
    *,
    leg_id: UUID,
    tier: BudgetBand,
    activity: ParsedActivityOption,
    raw_response_id: UUID,
    retrieved_at: datetime,
) -> OptionCard:
    card = OptionCard(
        leg_id=leg_id,
        option_type=OptionType.activity,
        tier=tier,
        title=activity.title,
        base_price_amount=activity.estimated_price_amount,
        currency=activity.estimated_price_currency,
        raw_response_id=raw_response_id,
    )
    session.add(card)
    await session.flush()
    session.add(
        ActivityOption(
            option_card_id=card.id,
            category=activity.category,
            description=activity.description,
            duration_minutes=activity.duration_minutes,
            estimated_price_amount=activity.estimated_price_amount,
            estimated_price_currency=activity.estimated_price_currency,
        )
    )
    for citation in activity.citations:
        session.add(
            Citation(
                activity_option_id=card.id,
                claim_text=citation.claim_text,
                source_url=citation.source_url,
                retrieved_at=retrieved_at,
            )
        )
    return card


async def persist_activities_research(
    session: AsyncSession,
    *,
    leg_id: UUID,
    parsed: ActivitiesResearchParsed,
    research_run_id: UUID | None,
    trace_id: str | None = None,
) -> list[OptionCard]:
    """Persist RawApiResponse first, then surviving OptionCard/ActivityOption/Citation rows.

    Writes the raw row even when zero activities survive filters, and even when
    extraction_failed is True (then raises after the raw commit so the ResearchRun can fail).
    """
    raw = await _write_raw_response(
        session,
        request_params=parsed.request_params,
        response_body=parsed.response_body,
        research_run_id=research_run_id,
    )

    if parsed.extraction_failed:
        await session.commit()
        raise ActivitiesAgentError(
            "Activities extraction failed after correction retries",
            details={
                "trace_id": trace_id,
                "leg_id": str(leg_id),
                "raw_response_id": str(raw.id),
                "error": parsed.extraction_error,
            },
        )

    flight_duration = await _shortest_flight_duration_minutes(session, leg_id)
    survivors = filter_activities_for_persistence(
        parsed.activities,
        flight_duration_minutes=flight_duration,
        trace_id=trace_id,
        leg_id=leg_id,
    )

    home_currency = await _trip_home_currency(session, leg_id)
    _log_currency_mismatches(
        survivors,
        home_currency=home_currency,
        leg_id=leg_id,
        trace_id=trace_id,
    )

    retrieved_at = datetime.now(UTC)
    cards: list[OptionCard] = []
    for tier, activity in assign_price_tiers(survivors):
        card = await _persist_activity_option(
            session,
            leg_id=leg_id,
            tier=tier,
            activity=activity,
            raw_response_id=raw.id,
            retrieved_at=retrieved_at,
        )
        cards.append(card)

    await session.commit()
    logger.info(
        "activities_persisted trace_id=%s leg_id=%s raw_id=%s cards=%s "
        "extracted=%s survived=%s",
        trace_id,
        leg_id,
        raw.id,
        len(cards),
        len(parsed.activities),
        len(survivors),
    )
    return cards
