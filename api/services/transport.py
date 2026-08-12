"""Transport validation + persistence.

research/ never writes to the DB. This module owns citation checks and
RawApiResponse → OptionCard → TransportOption → Citation writes
(docs/01_architecture.md §4.1, docs/04_build_plan.md Phase 4.5).

Tiering: unpriced options get tier=NULL and never enter the pool. Priced options
pool with the leg's currently-active priced FlightOption cards
(docs/01_architecture.md §4.1).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    BudgetBand,
    Citation,
    Leg,
    OptionCard,
    OptionType,
    RawApiResponse,
    RawApiSource,
    TransportMode,
    TransportOption,
    Trip,
)
from research.tiering import assign_pooled_price_tiers, matches_home_currency
from research.transport import TransportAgentError
from research.types import ParsedTransportOption, TransportResearchParsed
from services.combined_tiering import (
    apply_option_card_tier_updates,
    build_pool_from_new_and_existing,
    load_active_priced_option_cards,
    peer_tier_updates_for_eligible,
    transport_assignments_from_pool,
    transport_untiered_from_pool,
)
from services.fx import FxConversion, new_rate_cache, resolve_home_price


logger = logging.getLogger(__name__)


def drop_missing_citations(
    options: list[ParsedTransportOption],
) -> list[ParsedTransportOption]:
    """Hard gate: zero citations → drop (defense in depth; research schema also requires ≥1)."""
    kept: list[ParsedTransportOption] = []
    for option in options:
        if not option.citations:
            logger.info(
                "transport_drop_missing_citations mode=%s departure=%s arrival=%s",
                option.mode,
                option.departure_point,
                option.arrival_point,
            )
            continue
        kept.append(option)
    return kept


def filter_transport_for_persistence(
    options: list[ParsedTransportOption],
) -> list[ParsedTransportOption]:
    """Apply citation filter only — a null price is not a validation failure."""
    return drop_missing_citations(options)


def transport_card_title(option: ParsedTransportOption) -> str:
    mode_label = option.mode.replace("_", " ")
    if option.operator_name:
        return f"{option.operator_name} · {mode_label}"
    return f"{mode_label}: {option.departure_point} → {option.arrival_point}"


async def _trip_home_currency(session: AsyncSession, leg_id: UUID) -> str | None:
    result = await session.execute(
        select(Trip.home_currency).join(Leg, Leg.trip_id == Trip.id).where(Leg.id == leg_id)
    )
    return result.scalar_one_or_none()


def _log_currency_mismatches(
    options: list[ParsedTransportOption],
    *,
    home_currency: str | None,
    leg_id: UUID,
    trace_id: str | None,
) -> None:
    if not home_currency:
        return
    expected = home_currency.upper()
    for option in options:
        if option.estimated_price_currency is None:
            continue
        if option.estimated_price_currency.upper() != expected:
            logger.warning(
                "transport_currency_mismatch leg_id=%s trace_id=%s mode=%s "
                "home=%s found=%s — storing response currency as returned",
                leg_id,
                trace_id,
                option.mode,
                expected,
                option.estimated_price_currency.upper(),
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


async def materialize_home_priced_transport(
    options: list[ParsedTransportOption],
    *,
    home_currency: str,
) -> tuple[
    list[ParsedTransportOption],
    dict[int, tuple[ParsedTransportOption, FxConversion | None]],
    list[ParsedTransportOption],
]:
    """Convert priced transport into home currency for pooling/persist.

    Returns:
      home_options: clones (or originals) priced in home_currency
      meta_by_id: id(home_option) -> (source_option, fx_or_none)
      fx_failed: originals that could not be converted (remain foreign)
    """
    expected = home_currency.strip().upper()
    rate_cache = new_rate_cache()
    home_options: list[ParsedTransportOption] = []
    meta_by_id: dict[int, tuple[ParsedTransportOption, FxConversion | None]] = {}
    fx_failed: list[ParsedTransportOption] = []

    for option in options:
        amount = option.estimated_price_amount
        currency = option.estimated_price_currency
        if amount is None or currency is None:
            continue
        home_amount, card_currency, fx = await resolve_home_price(
            amount=amount,
            currency=currency,
            home_currency=expected,
            cache=rate_cache,
        )
        if card_currency != expected:
            fx_failed.append(option)
            continue
        if fx is None:
            home_options.append(option)
            meta_by_id[id(option)] = (option, None)
        else:
            home_option = replace(
                option,
                estimated_price_amount=home_amount,
                estimated_price_currency=expected,
            )
            home_options.append(home_option)
            meta_by_id[id(home_option)] = (option, fx)

    return home_options, meta_by_id, fx_failed


async def _persist_transport_option(
    session: AsyncSession,
    *,
    leg_id: UUID,
    tier: BudgetBand | None,
    option: ParsedTransportOption,
    source_option: ParsedTransportOption,
    raw_response_id: UUID,
    research_run_id: UUID | None,
    retrieved_at: datetime,
    card_currency: str,
    fx: FxConversion | None,
) -> OptionCard:
    card = OptionCard(
        leg_id=leg_id,
        option_type=OptionType.transport,
        tier=tier,
        title=transport_card_title(source_option),
        base_price_amount=option.estimated_price_amount,
        currency=card_currency,
        original_price_amount=fx.original_amount if fx is not None else None,
        original_currency=fx.original_currency if fx is not None else None,
        fx_rate=fx.fx_rate if fx is not None else None,
        fx_rate_as_of=fx.fx_rate_as_of if fx is not None else None,
        raw_response_id=raw_response_id,
        research_run_id=research_run_id,
    )
    session.add(card)
    await session.flush()
    session.add(
        TransportOption(
            option_card_id=card.id,
            mode=TransportMode(source_option.mode),
            operator_name=source_option.operator_name,
            departure_point=source_option.departure_point,
            arrival_point=source_option.arrival_point,
            estimated_duration_minutes=source_option.estimated_duration_minutes,
            estimated_price_amount=source_option.estimated_price_amount,
            estimated_price_currency=source_option.estimated_price_currency,
            booking_url=source_option.booking_url,
        )
    )
    for citation in source_option.citations:
        session.add(
            Citation(
                option_card_id=card.id,
                claim_text=citation.claim_text,
                source_url=citation.source_url,
                retrieved_at=retrieved_at,
            )
        )
    return card


async def persist_transport_research(
    session: AsyncSession,
    *,
    leg_id: UUID,
    parsed: TransportResearchParsed,
    research_run_id: UUID | None,
    trace_id: str | None = None,
    priced_tier_assignments: list[tuple[BudgetBand, ParsedTransportOption]] | None = None,
    untiered_home_transport: list[ParsedTransportOption] | None = None,
    transport_fx_meta: dict[int, tuple[ParsedTransportOption, FxConversion | None]]
    | None = None,
    retier_existing_flights: bool = True,
) -> list[OptionCard]:
    """Persist RawApiResponse first, then surviving OptionCard/TransportOption/Citation rows.

    Writes the raw row even when zero options survive citation validation, and even when
    extraction_failed is True (then raises after the raw commit so the ResearchRun can fail).
    Unpriced survivors persist with tier=NULL; priced survivors are FX-converted into
    Trip.home_currency on the OptionCard (detail row keeps source currency), then pool
    with flights unless priced_tier_assignments is provided (full-run single pool).
    """
    raw = await _write_raw_response(
        session,
        request_params=parsed.request_params,
        response_body=parsed.response_body,
        research_run_id=research_run_id,
    )

    if parsed.extraction_failed:
        await session.commit()
        raise TransportAgentError(
            "Transport extraction failed after correction retries",
            details={
                "trace_id": trace_id,
                "leg_id": str(leg_id),
                "raw_response_id": str(raw.id),
                "error": parsed.extraction_error,
            },
        )

    survivors = filter_transport_for_persistence(parsed.options)
    home_currency = await _trip_home_currency(session, leg_id)
    _log_currency_mismatches(
        survivors,
        home_currency=home_currency,
        leg_id=leg_id,
        trace_id=trace_id,
    )

    expected = (home_currency or "XXX").upper()
    unpriced = [o for o in survivors if o.estimated_price_amount is None]
    priced = [o for o in survivors if o.estimated_price_amount is not None]

    if transport_fx_meta is not None and priced_tier_assignments is not None:
        # Full-run path: caller already converted + tiered in home currency.
        fx_meta = transport_fx_meta
        tiered_priced = priced_tier_assignments
        untiered_home = (
            untiered_home_transport
            if untiered_home_transport is not None
            else []
        )
        assigned_ids = {id(o) for _, o in tiered_priced} | {id(o) for o in untiered_home}
        priced_foreign = [
            o
            for o in priced
            if id(o) not in assigned_ids
            and id(o) not in fx_meta
            and not matches_home_currency(o.estimated_price_currency, expected)
        ]
        peer_updates = {}
        flight_pool_size = 0
    else:
        priced_home, fx_meta, priced_foreign = await materialize_home_priced_transport(
            priced,
            home_currency=expected,
        )
        peer_updates = {}
        flight_pool_size = 0
        if priced_home:
            peer_cards: list[OptionCard] = []
            if retier_existing_flights and home_currency:
                peer_cards = await load_active_priced_option_cards(
                    session,
                    leg_id=leg_id,
                    option_type=OptionType.flight,
                    home_currency=home_currency,
                )
            flight_pool_size = len(peer_cards)
            pool = build_pool_from_new_and_existing(
                home_currency=expected,
                new_priced_transport=priced_home,
                existing_priced_cards=peer_cards,
            )
            tiers_by_key = assign_pooled_price_tiers(pool)
            tiered_priced = transport_assignments_from_pool(priced_home, tiers_by_key)
            untiered_home = transport_untiered_from_pool(priced_home, tiers_by_key)
            if retier_existing_flights and peer_cards:
                peer_updates = peer_tier_updates_for_eligible(peer_cards, tiers_by_key)
        else:
            tiered_priced = []
            untiered_home = []

    retrieved_at = datetime.now(UTC)
    fallback_currency = expected
    cards: list[OptionCard] = []

    def _meta_for(
        option: ParsedTransportOption,
    ) -> tuple[ParsedTransportOption, FxConversion | None]:
        if id(option) in fx_meta:
            return fx_meta[id(option)]
        return option, None

    for option in unpriced:
        card = await _persist_transport_option(
            session,
            leg_id=leg_id,
            tier=None,
            option=option,
            source_option=option,
            raw_response_id=raw.id,
            research_run_id=research_run_id,
            retrieved_at=retrieved_at,
            card_currency=fallback_currency,
            fx=None,
        )
        cards.append(card)

    for option in priced_foreign:
        assert option.estimated_price_currency is not None
        card = await _persist_transport_option(
            session,
            leg_id=leg_id,
            tier=None,
            option=option,
            source_option=option,
            raw_response_id=raw.id,
            research_run_id=research_run_id,
            retrieved_at=retrieved_at,
            card_currency=option.estimated_price_currency,
            fx=None,
        )
        cards.append(card)

    for option in untiered_home:
        source_option, fx = _meta_for(option)
        assert option.estimated_price_currency is not None
        card = await _persist_transport_option(
            session,
            leg_id=leg_id,
            tier=None,
            option=option,
            source_option=source_option,
            raw_response_id=raw.id,
            research_run_id=research_run_id,
            retrieved_at=retrieved_at,
            card_currency=option.estimated_price_currency,
            fx=fx,
        )
        cards.append(card)

    for tier, option in tiered_priced:
        source_option, fx = _meta_for(option)
        assert option.estimated_price_currency is not None
        card = await _persist_transport_option(
            session,
            leg_id=leg_id,
            tier=tier,
            option=option,
            source_option=source_option,
            raw_response_id=raw.id,
            research_run_id=research_run_id,
            retrieved_at=retrieved_at,
            card_currency=option.estimated_price_currency,
            fx=fx,
        )
        cards.append(card)

    if peer_updates:
        await apply_option_card_tier_updates(session, peer_updates)

    await session.commit()
    logger.info(
        "transport_persisted trace_id=%s leg_id=%s raw_id=%s cards=%s "
        "extracted=%s survived=%s unpriced=%s priced_foreign=%s priced_untiered=%s "
        "priced_tiered=%s flight_pool=%s",
        trace_id,
        leg_id,
        raw.id,
        len(cards),
        len(parsed.options),
        len(survivors),
        len(unpriced),
        len(priced_foreign),
        len(untiered_home),
        len(tiered_priced),
        flight_pool_size,
    )
    return cards
