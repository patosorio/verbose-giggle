"""Leg research orchestrator — docs/01_architecture.md §5 / §4.1, docs/04_build_plan.md Phase 4/4.5.

research/ never writes to the DB. This module owns ResearchRun status transitions,
call construction from Leg, sequential persistence, and the supersede-with-lock-exception
rule (one helper, two call sites).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Collection, Sequence
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import AppError
from db.models import (
    AgeCategory,
    Leg,
    Lock,
    OptionCard,
    OptionType,
    ResearchRun,
    ResearchRunStatus,
    ResearchRunType,
    Traveler,
    Trip,
)
from research.activities import research_activities
from research.serpapi import search_flights, search_hotels
from research.transport import research_transport
from research.types import (
    ActivitiesResearchParsed,
    FlightSearchParsed,
    HotelSearchParsed,
    TransportResearchParsed,
)
from schemas.research import ResearchRunOut, ResearchStartOut
from services import activities as activities_service
from services import options as options_service
from services import task_queue
from services import transport as transport_service
from services.combined_tiering import compute_combined_candidate_tiers


logger = logging.getLogger(__name__)

# docs/02_data_model.md Leg entry — known v1 limitation (no Traveler.age yet).
HOTEL_CHILD_AGE_PLACEHOLDER = 10
HOTEL_MAX_TRAVELERS = 6

FetchKind = Literal["flights", "hotels", "activities", "transport"]
FetchResult = (
    FlightSearchParsed
    | HotelSearchParsed
    | ActivitiesResearchParsed
    | TransportResearchParsed
)


async def start_leg_research(
    session: AsyncSession,
    *,
    leg_id: UUID,
    run_type: ResearchRunType,
) -> ResearchStartOut:
    """Create a queued ResearchRun and enqueue work. Returns immediately (202 path)."""
    leg = await session.get(Leg, leg_id)
    if leg is None:
        raise AppError(404, "not_found", "Leg not found")

    run = ResearchRun(
        leg_id=leg_id,
        run_type=run_type,
        status=ResearchRunStatus.queued,
        attempt_count=0,
        trace_id=str(uuid4()),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    await task_queue.enqueue_leg_research(leg_id, run.id, run_type)
    return ResearchStartOut(run_id=run.id, status=ResearchRunStatus.queued)


async def get_leg_research_run(
    session: AsyncSession,
    *,
    leg_id: UUID,
    run_id: UUID,
) -> ResearchRunOut:
    run = await session.get(ResearchRun, run_id)
    if run is None or run.leg_id != leg_id:
        raise AppError(404, "not_found", "Research run not found")
    return ResearchRunOut.model_validate(run)


def option_types_for_run_type(run_type: ResearchRunType) -> list[OptionType]:
    if run_type == ResearchRunType.full:
        return [
            OptionType.flight,
            OptionType.hotel,
            OptionType.activity,
            OptionType.transport,
        ]
    if run_type == ResearchRunType.flights:
        return [OptionType.flight]
    if run_type == ResearchRunType.hotels:
        return [OptionType.hotel]
    if run_type == ResearchRunType.activities:
        return [OptionType.activity]
    if run_type == ResearchRunType.transport:
        return [OptionType.transport]
    raise ValueError(f"Unsupported research run_type: {run_type!r}")


def hotel_party_counts(adults: int, children: int) -> tuple[int, int]:
    """Reduce adults (never children) until adults + children <= 6."""
    trimmed_adults = adults
    while trimmed_adults + children > HOTEL_MAX_TRAVELERS and trimmed_adults > 0:
        trimmed_adults -= 1
    return trimmed_adults, children


async def _active_lock_option_card_id(
    session: AsyncSession,
    leg_id: UUID,
) -> UUID | None:
    result = await session.execute(
        select(Lock.option_card_id).where(
            Lock.leg_id == leg_id,
            Lock.unlocked_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def supersede_option_cards(
    session: AsyncSession,
    *,
    leg_id: UUID,
    option_types: Collection[OptionType],
    only_research_run_id: UUID | None = None,
    exclude_research_run_id: UUID | None = None,
) -> int:
    """Soft-delete active OptionCards matching the filter, skipping the active Lock target.

    Shared helper for both same-run retry cleanup (`only_research_run_id`) and
    post-completion cross-run supersede (`exclude_research_run_id`).
    """
    if only_research_run_id is not None and exclude_research_run_id is not None:
        raise ValueError(
            "Pass only_research_run_id or exclude_research_run_id, not both"
        )
    if not option_types:
        return 0

    locked_card_id = await _active_lock_option_card_id(session, leg_id)
    now = datetime.now(UTC)

    conditions = [
        OptionCard.leg_id == leg_id,
        OptionCard.option_type.in_(list(option_types)),
        OptionCard.superseded_at.is_(None),
    ]
    if only_research_run_id is not None:
        conditions.append(OptionCard.research_run_id == only_research_run_id)
    if exclude_research_run_id is not None:
        conditions.append(
            OptionCard.research_run_id.is_distinct_from(exclude_research_run_id)
        )
    if locked_card_id is not None:
        conditions.append(OptionCard.id != locked_card_id)

    result = await session.execute(
        update(OptionCard).where(*conditions).values(superseded_at=now)
    )
    await session.flush()
    return int(result.rowcount or 0)


async def _traveler_counts(
    session: AsyncSession,
    trip_id: UUID,
) -> tuple[int, int]:
    result = await session.execute(
        select(Traveler.age_category).where(Traveler.trip_id == trip_id)
    )
    adults = 0
    children = 0
    for category in result.scalars().all():
        if category == AgeCategory.adult:
            adults += 1
        else:
            children += 1
    return adults, children


def _includes(run_type: ResearchRunType, kind: FetchKind) -> bool:
    if run_type == ResearchRunType.full:
        return True
    return run_type.value == kind


async def _persist_flight_and_transport(
    session: AsyncSession,
    *,
    leg_id: UUID,
    run_id: UUID,
    trace_id: str,
    home_currency: str,
    flight_parsed: FlightSearchParsed | None,
    transport_parsed: TransportResearchParsed | None,
) -> None:
    """Persist flights and/or transport with combined tiering when both are present.

    Full run with both successful results: one pool over fresh priced candidates, no
    peer re-tier (prior peers of either type are superseded after this run).
    One-sided: pool with the other type's currently-active priced cards and UPDATE peers.
    """
    if (
        flight_parsed is not None
        and transport_parsed is not None
        and not transport_parsed.extraction_failed
    ):
        survivors = transport_service.filter_transport_for_persistence(
            transport_parsed.options
        )
        priced = [o for o in survivors if o.estimated_price_amount is not None]
        (
            flight_assignments,
            flight_untiered,
            transport_assignments,
            transport_untiered,
        ) = compute_combined_candidate_tiers(
            flights=flight_parsed.flights,
            priced_transport=priced,
            home_currency=home_currency,
        )
        await options_service.persist_flight_search(
            session,
            leg_id=leg_id,
            parsed=flight_parsed,
            research_run_id=run_id,
            tier_assignments=flight_assignments,
            untiered_home_flights=flight_untiered,
            retier_existing_transport=False,
        )
        await transport_service.persist_transport_research(
            session,
            leg_id=leg_id,
            parsed=transport_parsed,
            research_run_id=run_id,
            trace_id=trace_id,
            priced_tier_assignments=transport_assignments,
            untiered_home_transport=transport_untiered,
            retier_existing_flights=False,
        )
        return

    if flight_parsed is not None:
        await options_service.persist_flight_search(
            session,
            leg_id=leg_id,
            parsed=flight_parsed,
            research_run_id=run_id,
            retier_existing_transport=True,
        )

    if transport_parsed is not None:
        await transport_service.persist_transport_research(
            session,
            leg_id=leg_id,
            parsed=transport_parsed,
            research_run_id=run_id,
            trace_id=trace_id,
            retier_existing_flights=True,
        )


async def run_leg_research(
    session: AsyncSession,
    leg_id: UUID,
    run_id: UUID,
    run_type: ResearchRunType,
) -> None:
    """Fan out research network calls, persist sequentially, supersede, update ResearchRun."""
    run = await session.get(ResearchRun, run_id)
    if run is None:
        raise ValueError(f"ResearchRun not found: {run_id}")
    if run.leg_id != leg_id:
        raise ValueError(
            f"ResearchRun {run_id} belongs to leg {run.leg_id}, not {leg_id}"
        )
    if run.run_type != run_type:
        raise ValueError(
            f"ResearchRun {run_id} run_type is {run.run_type.value}, not {run_type.value}"
        )

    # Idempotent against Cloud Tasks at-least-once redelivery of a finished job.
    if run.status == ResearchRunStatus.completed:
        logger.info(
            "run_leg_research_noop_completed trace_id=%s run_id=%s leg_id=%s",
            run.trace_id,
            run_id,
            leg_id,
        )
        return

    leg = await session.get(Leg, leg_id)
    if leg is None:
        raise ValueError(f"Leg not found: {leg_id}")
    trip = await session.get(Trip, leg.trip_id)
    if trip is None:
        raise ValueError(f"Trip not found for leg: {leg_id}")

    adults, children = await _traveler_counts(session, trip.id)
    if adults + children == 0:
        adults = 1
    scoped_types = option_types_for_run_type(run_type)
    trace_id = run.trace_id

    run.status = ResearchRunStatus.running
    run.attempt_count = (run.attempt_count or 0) + 1
    run.started_at = datetime.now(UTC)
    run.error_message = None
    run.completed_at = None
    await session.commit()

    # Same-run retry: wipe this run's prior-attempt cards before writing fresh ones.
    if run.attempt_count > 1:
        superseded = await supersede_option_cards(
            session,
            leg_id=leg_id,
            option_types=scoped_types,
            only_research_run_id=run_id,
        )
        await session.commit()
        logger.info(
            "run_leg_research_retry_supersede trace_id=%s run_id=%s leg_id=%s "
            "attempt_count=%s superseded=%s",
            trace_id,
            run_id,
            leg_id,
            run.attempt_count,
            superseded,
        )

    fetch_kinds: list[FetchKind] = []
    fetch_coros: list[Awaitable[FetchResult]] = []

    if _includes(run_type, "flights"):
        if leg.origin_iata and leg.destination_iata:
            fetch_kinds.append("flights")
            fetch_coros.append(
                search_flights(
                    departure_id=leg.origin_iata,
                    arrival_id=leg.destination_iata,
                    outbound_date=leg.start_date,
                    currency=trip.home_currency,
                    adults=adults,
                    children=children,
                    leg_id=leg_id,
                )
            )
        else:
            logger.info(
                "flight search skipped, missing IATA codes trace_id=%s leg_id=%s "
                "origin_iata=%s destination_iata=%s",
                trace_id,
                leg_id,
                leg.origin_iata,
                leg.destination_iata,
            )

    if _includes(run_type, "hotels"):
        hotel_adults, hotel_children = hotel_party_counts(adults, children)
        children_ages = (
            [HOTEL_CHILD_AGE_PLACEHOLDER] * hotel_children if hotel_children else None
        )
        fetch_kinds.append("hotels")
        fetch_coros.append(
            search_hotels(
                q=f"{leg.destination} hotels",
                check_in_date=leg.start_date,
                check_out_date=leg.end_date,
                currency=trip.home_currency,
                adults=hotel_adults,
                children=hotel_children,
                children_ages=children_ages,
                leg_id=leg_id,
            )
        )

    if _includes(run_type, "activities"):
        fetch_kinds.append("activities")
        fetch_coros.append(
            research_activities(
                destination=leg.destination,
                start_date=leg.start_date,
                end_date=leg.end_date,
                nights=leg.nights,
                home_currency=trip.home_currency,
                leg_id=leg_id,
                trace_id=trace_id,
            )
        )

    if _includes(run_type, "transport"):
        fetch_kinds.append("transport")
        fetch_coros.append(
            research_transport(
                origin=leg.origin,
                destination=leg.destination,
                start_date=leg.start_date,
                end_date=leg.end_date,
                home_currency=trip.home_currency,
                leg_id=leg_id,
                trace_id=trace_id,
            )
        )

    try:
        raw_results: Sequence[FetchResult | BaseException] = ()
        if fetch_coros:
            raw_results = await asyncio.gather(*fetch_coros, return_exceptions=True)

        by_kind: dict[FetchKind, FetchResult | BaseException] = dict(
            zip(fetch_kinds, raw_results, strict=True)
        )

        first_error: BaseException | None = None
        for kind, result in by_kind.items():
            if isinstance(result, BaseException):
                if first_error is None:
                    first_error = result
                logger.error(
                    "run_leg_research_fetch_failed trace_id=%s run_id=%s leg_id=%s kind=%s",
                    trace_id,
                    run_id,
                    leg_id,
                    kind,
                    exc_info=result,
                )

        # Hotels / activities are independent of the flight+transport pool.
        hotels_result = by_kind.get("hotels")
        if isinstance(hotels_result, HotelSearchParsed):
            await options_service.persist_hotel_search(
                session,
                leg_id=leg_id,
                parsed=hotels_result,
                research_run_id=run_id,
            )

        activities_result = by_kind.get("activities")
        if isinstance(activities_result, ActivitiesResearchParsed):
            await activities_service.persist_activities_research(
                session,
                leg_id=leg_id,
                parsed=activities_result,
                research_run_id=run_id,
                trace_id=trace_id,
            )

        flights_result = by_kind.get("flights")
        transport_result = by_kind.get("transport")
        flight_parsed = (
            flights_result if isinstance(flights_result, FlightSearchParsed) else None
        )
        transport_parsed = (
            transport_result
            if isinstance(transport_result, TransportResearchParsed)
            else None
        )
        if flight_parsed is not None or transport_parsed is not None:
            await _persist_flight_and_transport(
                session,
                leg_id=leg_id,
                run_id=run_id,
                trace_id=trace_id,
                home_currency=trip.home_currency,
                flight_parsed=flight_parsed,
                transport_parsed=transport_parsed,
            )

        if first_error is not None:
            raise first_error

        await supersede_option_cards(
            session,
            leg_id=leg_id,
            option_types=scoped_types,
            exclude_research_run_id=run_id,
        )

        run.status = ResearchRunStatus.completed
        run.completed_at = datetime.now(UTC)
        run.error_message = None
        await session.commit()
        logger.info(
            "run_leg_research_completed trace_id=%s run_id=%s leg_id=%s run_type=%s",
            trace_id,
            run_id,
            leg_id,
            run_type.value,
        )
    except Exception as exc:
        await session.rollback()
        # Re-load after rollback so status write isn't on a poisoned session state.
        run = await session.get(ResearchRun, run_id)
        if run is not None and run.status != ResearchRunStatus.completed:
            run.status = ResearchRunStatus.failed
            run.completed_at = datetime.now(UTC)
            run.error_message = str(exc)
            await session.commit()
        logger.exception(
            "run_leg_research_failed trace_id=%s run_id=%s leg_id=%s",
            trace_id,
            run_id,
            leg_id,
        )
        raise
