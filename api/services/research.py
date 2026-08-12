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
    Leg,
    LegStatus,
    Lock,
    OptionCard,
    OptionType,
    ResearchRun,
    ResearchRunStatus,
    ResearchRunType,
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
from schemas.legs import LegFiltersIn, RoomOccupancyIn
from schemas.research import ResearchRunOut, ResearchStartOut
from services import activities as activities_service
from services import options as options_service
from services import task_queue
from services import transport as transport_service
from services.combined_tiering import compute_combined_candidate_tiers


logger = logging.getLogger(__name__)

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
    leg.status = LegStatus.researching
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


async def _active_lock_option_card_ids(
    session: AsyncSession,
    leg_id: UUID,
) -> list[UUID]:
    result = await session.execute(
        select(Lock.option_card_id).where(
            Lock.leg_id == leg_id,
            Lock.unlocked_at.is_(None),
        )
    )
    return list(result.scalars().all())


async def supersede_option_cards(
    session: AsyncSession,
    *,
    leg_id: UUID,
    option_types: Collection[OptionType],
    only_research_run_id: UUID | None = None,
    exclude_research_run_id: UUID | None = None,
) -> int:
    """Soft-delete active OptionCards matching the filter, skipping active Lock targets.

    Shared helper for both same-run retry cleanup (`only_research_run_id`) and
    post-completion cross-run supersede (`exclude_research_run_id`).
    """
    if only_research_run_id is not None and exclude_research_run_id is not None:
        raise ValueError(
            "Pass only_research_run_id or exclude_research_run_id, not both"
        )
    if not option_types:
        return 0

    locked_card_ids = await _active_lock_option_card_ids(session, leg_id)
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
    if locked_card_ids:
        conditions.append(OptionCard.id.not_in(locked_card_ids))

    result = await session.execute(
        update(OptionCard).where(*conditions).values(superseded_at=now)
    )
    await session.flush()
    return int(result.rowcount or 0)


def _format_room_label(room_numbers: list[int], spec: RoomOccupancyIn) -> str:
    if len(room_numbers) == 1:
        rooms_part = f"Room {room_numbers[0]}"
    else:
        rooms_part = f"Rooms {', '.join(str(n) for n in room_numbers)}"

    parts: list[str] = []
    if spec.adults == 1:
        parts.append("1 adult")
    else:
        parts.append(f"{spec.adults} adults")

    if spec.children == 1:
        age = spec.children_ages[0]
        parts.append(f"1 child (age {age})")
    elif spec.children > 1:
        ages = ", ".join(str(age) for age in spec.children_ages)
        parts.append(f"{spec.children} children (ages {ages})")

    return f"{rooms_part} · {', '.join(parts)}"


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
        home_priced, fx_meta, _fx_failed = (
            await transport_service.materialize_home_priced_transport(
                priced,
                home_currency=home_currency,
            )
        )
        (
            flight_assignments,
            flight_untiered,
            transport_assignments,
            transport_untiered,
        ) = compute_combined_candidate_tiers(
            flights=flight_parsed.flights,
            priced_transport=home_priced,
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
            transport_fx_meta=fx_meta,
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

    parsed_filters = LegFiltersIn.model_validate(leg.filters)
    rooms = parsed_filters.occupancy.rooms
    adults = sum(r.adults for r in rooms)
    children = sum(r.children for r in rooms)
    scoped_types = option_types_for_run_type(run_type)
    trace_id = run.trace_id

    run.status = ResearchRunStatus.running
    run.attempt_count = (run.attempt_count or 0) + 1
    run.started_at = datetime.now(UTC)
    run.error_message = None
    run.completed_at = None
    leg.status = LegStatus.researching
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

    if _includes(run_type, "flights") and not leg.skip_flight:
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
                    max_stops=parsed_filters.flight.max_stops,
                    max_price=parsed_filters.flight.max_price,
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
    elif _includes(run_type, "flights") and leg.skip_flight:
        logger.info(
            "flight_search_skipped skip_flight=true trace_id=%s leg_id=%s",
            trace_id,
            leg_id,
        )

    hotel_room_specs: list[tuple[list[int], RoomOccupancyIn]] = []
    if _includes(run_type, "hotels") and not leg.skip_hotel:
        seen: dict[tuple[int, int, tuple[int, ...]], list[int]] = {}
        for i, room in enumerate(rooms, start=1):
            key = (room.adults, room.children, tuple(sorted(room.children_ages)))
            seen.setdefault(key, []).append(i)
        for key, room_numbers in seen.items():
            adults_, children_, ages_ = key
            spec = RoomOccupancyIn(
                adults=adults_,
                children=children_,
                children_ages=list(ages_),
            )
            hotel_room_specs.append((room_numbers, spec))
        logger.info(
            "hotel_room_search trace_id=%s leg_id=%s rooms_requested=%s "
            "distinct_compositions=%s",
            trace_id,
            leg_id,
            len(rooms),
            len(hotel_room_specs),
        )
    elif _includes(run_type, "hotels") and leg.skip_hotel:
        logger.info(
            "hotel_search_skipped skip_hotel=true trace_id=%s leg_id=%s",
            trace_id,
            leg_id,
        )

    hotel_coros = [
        search_hotels(
            q=f"{leg.destination} hotels",
            check_in_date=leg.start_date,
            check_out_date=leg.end_date,
            currency=trip.home_currency,
            adults=spec.adults,
            children=spec.children,
            children_ages=spec.children_ages or None,
            leg_id=leg_id,
            hotel_class=parsed_filters.hotel.star_class,
            free_cancellation=parsed_filters.hotel.free_cancellation_only,
            min_price=(
                parsed_filters.hotel.price_range.min
                if parsed_filters.hotel.price_range
                else None
            ),
            max_price=(
                parsed_filters.hotel.price_range.max
                if parsed_filters.hotel.price_range
                else None
            ),
        )
        for _, spec in hotel_room_specs
    ]

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
        all_coros: list[Awaitable[FetchResult]] = [*fetch_coros, *hotel_coros]
        all_raw: Sequence[FetchResult | BaseException] = ()
        if all_coros:
            all_raw = await asyncio.gather(*all_coros, return_exceptions=True)

        raw_results = all_raw[: len(fetch_coros)]
        hotel_raw_results = all_raw[len(fetch_coros) :]

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

        for (room_numbers, spec), hotel_result in zip(
            hotel_room_specs, hotel_raw_results, strict=True
        ):
            if isinstance(hotel_result, BaseException):
                if first_error is None:
                    first_error = hotel_result
                logger.error(
                    "run_leg_research_fetch_failed trace_id=%s run_id=%s leg_id=%s "
                    "kind=hotels room_label=%s",
                    trace_id,
                    run_id,
                    leg_id,
                    _format_room_label(room_numbers, spec),
                    exc_info=hotel_result,
                )
                continue
            if isinstance(hotel_result, HotelSearchParsed):
                await options_service.persist_hotel_search(
                    session,
                    leg_id=leg_id,
                    parsed=hotel_result,
                    research_run_id=run_id,
                    room_label=_format_room_label(room_numbers, spec),
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
        # Reload leg after commits in the persist path so status write is on a live instance.
        leg = await session.get(Leg, leg_id)
        if leg is not None:
            leg.status = LegStatus.ready
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
            leg = await session.get(Leg, leg_id)
            if leg is not None:
                leg.status = LegStatus.failed
            await session.commit()
        logger.exception(
            "run_leg_research_failed trace_id=%s run_id=%s leg_id=%s",
            trace_id,
            run_id,
            leg_id,
        )
        raise
