"""One-off cleanup: duplicate legs on the reference trip (throwaway).

Not a migration. Dry-run by default; pass --confirm to execute deletes/updates.

Invoke from api/:

    uv run python scripts/fix_reference_trip_legs.py --trip-id <UUID>
    uv run python scripts/fix_reference_trip_legs.py --trip-id <UUID> --confirm

Omit --trip-id to print a diagnostic of trips that still have duplicate
sequence_index rows (helps find the right UUID).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_API_ROOT = Path(__file__).resolve().parents[1]
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from core.config import settings
from db.models import (
    ActivityOption,
    BookingSource,
    Citation,
    FlightOption,
    HotelOption,
    ImportedOption,
    Leg,
    Lock,
    LockEvent,
    OptionCard,
    RawApiResponse,
    Reaction,
    ResearchRun,
    TransportOption,
    Trip,
)

CANONICAL_LEGS: dict[int, dict[str, str | None]] = {
    0: {
        "origin": "Bangkok",
        "destination": "Phuket",
        "origin_iata": "BKK",
        "destination_iata": "HKT",
    },
    1: {
        "origin": "Phuket",
        "destination": "Koh Yao Noi",
        "origin_iata": None,
        "destination_iata": None,
    },
    2: {
        "origin": "Koh Yao Noi",
        "destination": "Koh Lanta",
        "origin_iata": None,
        "destination_iata": None,
    },
    3: {
        "origin": "Koh Lanta",
        "destination": "Krabi",
        "origin_iata": "HKT",
        "destination_iata": "KBV",
    },
    4: {
        "origin": "Krabi",
        "destination": "Bangkok",
        "origin_iata": "KBV",
        "destination_iata": "BKK",
    },
}


@dataclass(frozen=True, slots=True)
class LegDupStats:
    leg: Leg
    option_card_count: int
    research_run_count: int
    has_active_lock: bool
    active_lock_id: UUID | None


@dataclass(frozen=True, slots=True)
class SequencePlan:
    sequence_index: int
    keeper: LegDupStats
    to_delete: list[LegDupStats]


async def _option_card_counts(
    session: AsyncSession,
    leg_ids: list[UUID],
) -> dict[UUID, int]:
    if not leg_ids:
        return {}
    result = await session.execute(
        select(OptionCard.leg_id, func.count())
        .where(OptionCard.leg_id.in_(leg_ids))
        .group_by(OptionCard.leg_id)
    )
    return {leg_id: count for leg_id, count in result.all()}


async def _research_run_counts(
    session: AsyncSession,
    leg_ids: list[UUID],
) -> dict[UUID, int]:
    if not leg_ids:
        return {}
    result = await session.execute(
        select(ResearchRun.leg_id, func.count())
        .where(ResearchRun.leg_id.in_(leg_ids))
        .group_by(ResearchRun.leg_id)
    )
    return {leg_id: count for leg_id, count in result.all()}


async def _active_locks_by_leg(
    session: AsyncSession,
    leg_ids: list[UUID],
) -> dict[UUID, UUID]:
    if not leg_ids:
        return {}
    result = await session.execute(
        select(Lock.leg_id, Lock.id).where(
            Lock.leg_id.in_(leg_ids),
            Lock.unlocked_at.is_(None),
        )
    )
    return {leg_id: lock_id for leg_id, lock_id in result.all()}


async def _load_dup_stats(
    session: AsyncSession,
    legs: list[Leg],
) -> list[LegDupStats]:
    leg_ids = [leg.id for leg in legs]
    card_counts = await _option_card_counts(session, leg_ids)
    run_counts = await _research_run_counts(session, leg_ids)
    active_locks = await _active_locks_by_leg(session, leg_ids)
    return [
        LegDupStats(
            leg=leg,
            option_card_count=card_counts.get(leg.id, 0),
            research_run_count=run_counts.get(leg.id, 0),
            has_active_lock=leg.id in active_locks,
            active_lock_id=active_locks.get(leg.id),
        )
        for leg in legs
    ]


def _pick_keeper(stats: list[LegDupStats]) -> LegDupStats:
    locked = [row for row in stats if row.has_active_lock]
    if len(locked) > 1:
        ids = ", ".join(str(row.leg.id) for row in locked)
        raise SystemExit(
            f"ABORT sequence_index={stats[0].leg.sequence_index}: "
            f"{len(locked)} legs have an active Lock ({ids}). "
            "Needs a manual decision — refusing to guess."
        )
    if len(locked) == 1:
        return locked[0]
    return sorted(
        stats,
        key=lambda row: (-row.option_card_count, str(row.leg.id)),
    )[0]


async def _diagnose_duplicate_trips(session: AsyncSession) -> None:
    result = await session.execute(
        text(
            """
            SELECT t.id, t.name, l.sequence_index, COUNT(*) AS leg_count
            FROM trips t
            JOIN legs l ON l.trip_id = t.id
            GROUP BY t.id, t.name, l.sequence_index
            HAVING COUNT(*) > 1
            ORDER BY t.name, l.sequence_index
            """
        )
    )
    rows = list(result.all())
    if not rows:
        print("No trips have duplicate (trip_id, sequence_index) legs.")
        return
    print("Trips with duplicate sequence_index rows:")
    for trip_id, name, sequence_index, leg_count in rows:
        print(
            f"  trip_id={trip_id} name={name!r} "
            f"sequence_index={sequence_index} legs={leg_count}"
        )
    print("\nRe-run with --trip-id <UUID> from the list above.")


async def _print_trip_diagnostic(session: AsyncSession, trip_id: UUID) -> list[SequencePlan]:
    trip = await session.get(Trip, trip_id)
    if trip is None:
        raise SystemExit(f"Trip not found: {trip_id}")

    legs_result = await session.execute(
        select(Leg).where(Leg.trip_id == trip_id).order_by(Leg.sequence_index, Leg.id)
    )
    legs = list(legs_result.scalars().all())
    by_seq: dict[int, list[Leg]] = defaultdict(list)
    for leg in legs:
        by_seq[leg.sequence_index].append(leg)

    print(f"Trip {trip.id} name={trip.name!r}")
    print(f"Total leg rows: {len(legs)}")
    print()

    plans: list[SequencePlan] = []
    for sequence_index in sorted(by_seq):
        group = by_seq[sequence_index]
        stats = await _load_dup_stats(session, group)
        print(f"=== sequence_index={sequence_index} ({len(stats)} rows) ===")
        for row in sorted(stats, key=lambda s: str(s.leg.id)):
            lock_note = (
                f" ACTIVE_LOCK={row.active_lock_id}" if row.has_active_lock else ""
            )
            print(
                f"  leg_id={row.leg.id} origin={row.leg.origin!r} "
                f"destination={row.leg.destination!r} "
                f"origin_iata={row.leg.origin_iata!r} "
                f"destination_iata={row.leg.destination_iata!r} "
                f"option_cards={row.option_card_count} "
                f"research_runs={row.research_run_count}{lock_note}"
            )

        if len(stats) == 1:
            keeper = stats[0]
            to_delete: list[LegDupStats] = []
        else:
            keeper = _pick_keeper(stats)
            to_delete = [row for row in stats if row.leg.id != keeper.leg.id]

        plans.append(
            SequencePlan(
                sequence_index=sequence_index,
                keeper=keeper,
                to_delete=to_delete,
            )
        )
        print(
            f"  → KEEPER leg_id={keeper.leg.id} "
            f"(option_cards={keeper.option_card_count}, "
            f"active_lock={keeper.has_active_lock})"
        )
        if to_delete:
            for row in to_delete:
                print(
                    f"  → DELETE  leg_id={row.leg.id} "
                    f"(option_cards={row.option_card_count}, "
                    f"research_runs={row.research_run_count})"
                )
        else:
            print("  → no duplicates to delete")
        print()

    return plans


async def _delete_leg_cascade(session: AsyncSession, leg_id: UUID) -> None:
    """FK-safe delete for one leg and its research/options subtree."""
    card_ids_result = await session.execute(
        select(OptionCard.id).where(OptionCard.leg_id == leg_id)
    )
    card_ids = list(card_ids_result.scalars().all())

    run_ids_result = await session.execute(
        select(ResearchRun.id).where(ResearchRun.leg_id == leg_id)
    )
    run_ids = list(run_ids_result.scalars().all())

    # Collect raw response ids before tearing down cards/booking sources.
    raw_ids: set[UUID] = set()
    if card_ids:
        card_raw = await session.execute(
            select(OptionCard.raw_response_id).where(OptionCard.id.in_(card_ids))
        )
        raw_ids.update(card_raw.scalars().all())
        booking_raw = await session.execute(
            select(BookingSource.raw_response_id).where(
                BookingSource.option_card_id.in_(card_ids)
            )
        )
        raw_ids.update(booking_raw.scalars().all())
    if run_ids:
        run_raw = await session.execute(
            select(RawApiResponse.id).where(RawApiResponse.research_run_id.in_(run_ids))
        )
        raw_ids.update(run_raw.scalars().all())

    lock_ids_result = await session.execute(select(Lock.id).where(Lock.leg_id == leg_id))
    lock_ids = list(lock_ids_result.scalars().all())
    if lock_ids:
        await session.execute(delete(LockEvent).where(LockEvent.lock_id.in_(lock_ids)))
        await session.execute(delete(Lock).where(Lock.id.in_(lock_ids)))

    if card_ids:
        await session.execute(
            delete(Reaction).where(Reaction.option_card_id.in_(card_ids))
        )
        await session.execute(
            delete(BookingSource).where(BookingSource.option_card_id.in_(card_ids))
        )
        await session.execute(
            delete(Citation).where(Citation.option_card_id.in_(card_ids))
        )
        await session.execute(
            delete(FlightOption).where(FlightOption.option_card_id.in_(card_ids))
        )
        await session.execute(
            delete(HotelOption).where(HotelOption.option_card_id.in_(card_ids))
        )
        await session.execute(
            delete(ActivityOption).where(ActivityOption.option_card_id.in_(card_ids))
        )
        await session.execute(
            delete(TransportOption).where(TransportOption.option_card_id.in_(card_ids))
        )
        await session.execute(
            delete(ImportedOption).where(ImportedOption.option_card_id.in_(card_ids))
        )
        await session.execute(delete(OptionCard).where(OptionCard.id.in_(card_ids)))

    if raw_ids:
        await session.execute(delete(RawApiResponse).where(RawApiResponse.id.in_(raw_ids)))

    if run_ids:
        await session.execute(delete(ResearchRun).where(ResearchRun.id.in_(run_ids)))

    await session.execute(delete(Leg).where(Leg.id == leg_id))


async def _apply_canonical(session: AsyncSession, keeper_leg_id: UUID, sequence_index: int) -> None:
    fields = CANONICAL_LEGS.get(sequence_index)
    if fields is None:
        print(
            f"  skip canonical update for unexpected sequence_index={sequence_index}"
        )
        return
    await session.execute(
        update(Leg)
        .where(Leg.id == keeper_leg_id)
        .values(
            origin=fields["origin"],
            destination=fields["destination"],
            origin_iata=fields["origin_iata"],
            destination_iata=fields["destination_iata"],
        )
    )
    print(
        f"  update keeper {keeper_leg_id}: "
        f"origin={fields['origin']!r} destination={fields['destination']!r} "
        f"origin_iata={fields['origin_iata']!r} "
        f"destination_iata={fields['destination_iata']!r}"
    )


async def _verify_one_per_sequence(session: AsyncSession, trip_id: UUID) -> None:
    result = await session.execute(
        select(Leg.sequence_index, func.count())
        .where(Leg.trip_id == trip_id)
        .group_by(Leg.sequence_index)
        .order_by(Leg.sequence_index)
    )
    print("Post-cleanup counts:")
    for sequence_index, count in result.all():
        print(f"  sequence_index={sequence_index} legs={count}")
        if count != 1:
            raise SystemExit(
                f"ABORT: sequence_index={sequence_index} still has {count} legs"
            )


async def main(*, trip_id: UUID | None, confirm: bool) -> None:
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is empty")

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        if trip_id is None:
            await _diagnose_duplicate_trips(session)
            await engine.dispose()
            return

        plans = await _print_trip_diagnostic(session, trip_id)
        delete_count = sum(len(plan.to_delete) for plan in plans)
        print("--- plan summary ---")
        print(f"keepers to update: {len(plans)}")
        print(f"duplicate legs to delete: {delete_count}")
        for plan in plans:
            if plan.sequence_index in CANONICAL_LEGS:
                fields = CANONICAL_LEGS[plan.sequence_index]
                print(
                    f"  seq {plan.sequence_index}: keep {plan.keeper.leg.id}, "
                    f"delete {[row.leg.id for row in plan.to_delete]}, "
                    f"set {fields}"
                )

        if not confirm:
            print()
            print("DRY-RUN only — no changes written.")
            print("Re-run with the same --trip-id and --confirm to execute.")
            await engine.dispose()
            return

        print()
        print("CONFIRM: applying deletes and canonical updates…")
        try:
            for plan in plans:
                for row in plan.to_delete:
                    print(f"deleting leg {row.leg.id} (seq {plan.sequence_index})…")
                    await _delete_leg_cascade(session, row.leg.id)
                await _apply_canonical(session, plan.keeper.leg.id, plan.sequence_index)
            await _verify_one_per_sequence(session, trip_id)
            await session.commit()
            print("Done. Committed.")
        except Exception:
            await session.rollback()
            raise

    await engine.dispose()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean duplicate reference-trip legs (dry-run unless --confirm)."
    )
    parser.add_argument(
        "--trip-id",
        type=UUID,
        default=None,
        help="Trip UUID to clean. Omit to list trips that still have duplicates.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually delete duplicates and apply canonical origin/IATA updates.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(trip_id=args.trip_id, confirm=args.confirm))
