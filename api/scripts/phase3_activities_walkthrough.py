"""Phase 3 exit-criteria walkthrough — live Anthropic activities agent.

Prerequisite: ANTHROPIC_API_KEY set in api/.env (Phase 0/1). No new key required.

Invoke from api/:

    uv run python scripts/phase3_activities_walkthrough.py

This is intentionally NOT a pytest test — a bare `uv run pytest` must never
hit the live Anthropic API (same split as scripts/phase2_serpapi_walkthrough.py).

Expect ~1–2 minutes per leg (web_search research + extraction). Five legs
often take 6–10 minutes total — silence between "research_start" and
"research_done" is normal, not a hang.

Exit criteria (docs/04_build_plan.md Phase 3 / docs/10_phase3_cursor_prompts.md):
- 3 flight-based legs: extraction succeeds, ≥1 activity survives the gates,
  same-day check actually ran (no skip log). Citation/price/same-day *drops*
  are the gates working — logged as info, not walkthrough failures.
- 2 ferry-based legs: clean "same-day check skipped, no duration data" log
  line (not a silent false pass), plus ≥1 surviving activity.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parents[1]
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from core.config import settings
from core.logging import setup_logging
from research.activities import research_activities
from research.types import ParsedActivityOption
from services.activities import (
    drop_implausible_prices,
    drop_missing_citations,
    drop_same_day_transfer_conflicts,
)

logger = logging.getLogger("phase3_walkthrough")

SKIP_LOG_FRAGMENT = "same-day check skipped, no duration data"


@dataclass(frozen=True, slots=True)
class ReferenceActivityLeg:
    label: str
    destination: str
    start_date: date
    end_date: date
    nights: int
    # Shortest realistic flight duration for this transfer, or None for ferry-only.
    flight_duration_minutes: int | None


# Same 5 reference legs as Phase 2 walkthrough / docs/04_build_plan.md.
# Ferry island hops have no FlightOption duration anywhere in the system.
REFERENCE_LEGS: tuple[ReferenceActivityLeg, ...] = (
    ReferenceActivityLeg(
        label="BKK→Phuket",
        destination="Phuket",
        start_date=date(2026, 11, 10),
        end_date=date(2026, 11, 11),
        nights=1,
        flight_duration_minutes=80,
    ),
    ReferenceActivityLeg(
        label="Phuket→Koh Yao Noi (4n)",
        destination="Koh Yao Noi",
        start_date=date(2026, 11, 11),
        end_date=date(2026, 11, 15),
        nights=4,
        flight_duration_minutes=None,
    ),
    ReferenceActivityLeg(
        label="Koh Yao Noi→Koh Lanta (2n)",
        destination="Koh Lanta",
        start_date=date(2026, 11, 15),
        end_date=date(2026, 11, 17),
        nights=2,
        flight_duration_minutes=None,
    ),
    ReferenceActivityLeg(
        label="Koh Lanta→Krabi (1n)",
        destination="Krabi",
        start_date=date(2026, 11, 17),
        end_date=date(2026, 11, 18),
        nights=1,
        flight_duration_minutes=45,
    ),
    ReferenceActivityLeg(
        label="Krabi→BKK",
        destination="Bangkok",
        start_date=date(2026, 11, 18),
        end_date=date(2026, 11, 19),
        nights=1,
        flight_duration_minutes=75,
    ),
)


def _titles(activities: list[ParsedActivityOption]) -> list[str]:
    return [a.title for a in activities]


async def _run_leg(ref: ReferenceActivityLeg, *, index: int, total: int) -> bool:
    """Return True if this leg meets exit criteria."""
    is_ferry = ref.flight_duration_minutes is None
    logger.info(
        "=== leg %s/%s %s destination=%s mode=%s "
        "(Anthropic web_search often 1–2 min of silence here) ===",
        index,
        total,
        ref.label,
        ref.destination,
        "ferry" if is_ferry else "flight",
    )
    parsed = await research_activities(
        destination=ref.destination,
        start_date=ref.start_date,
        end_date=ref.end_date,
        nights=ref.nights,
        home_currency="THB",
        trace_id=f"phase3-walkthrough:{ref.label}",
    )

    if parsed.extraction_failed:
        logger.error(
            "extraction_failed leg=%s error=%s",
            ref.label,
            parsed.extraction_error,
        )
        return False

    extracted = parsed.activities
    if not extracted:
        logger.error("leg %s extracted zero schema-valid activities", ref.label)
        return False
    logger.info("extracted_count=%s titles=%s", len(extracted), _titles(extracted))

    after_citations = drop_missing_citations(extracted)
    citation_drops = [t for t in _titles(extracted) if t not in _titles(after_citations)]

    after_prices = drop_implausible_prices(after_citations)
    price_drops = [t for t in _titles(after_citations) if t not in _titles(after_prices)]

    # Capture same-day skip/conflict logs from the services logger.
    services_logger = logging.getLogger("services.activities")
    skip_records: list[str] = []

    class _SkipHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            msg = record.getMessage()
            if SKIP_LOG_FRAGMENT in msg:
                skip_records.append(msg)

    handler = _SkipHandler()
    handler.setLevel(logging.INFO)
    services_logger.addHandler(handler)
    try:
        after_same_day = drop_same_day_transfer_conflicts(
            after_prices,
            flight_duration_minutes=ref.flight_duration_minutes,
            trace_id=f"phase3-walkthrough:{ref.label}",
        )
    finally:
        services_logger.removeHandler(handler)

    same_day_drops = [t for t in _titles(after_prices) if t not in _titles(after_same_day)]

    logger.info(
        "filter_summary leg=%s citation_drops=%s price_drops=%s same_day_drops=%s "
        "survived=%s",
        ref.label,
        citation_drops,
        price_drops,
        same_day_drops,
        _titles(after_same_day),
    )
    if citation_drops or price_drops or same_day_drops:
        logger.info(
            "gate_drops_are_expected (filters working) leg=%s — not an exit failure "
            "unless zero survivors remain",
            ref.label,
        )

    if not after_same_day:
        logger.error("leg %s produced zero surviving activities after filters", ref.label)
        return False

    if is_ferry:
        if not skip_records:
            logger.error(
                "ferry leg %s missing skip log %r — would be a silent false pass",
                ref.label,
                SKIP_LOG_FRAGMENT,
            )
            return False
        logger.info("ferry PASS leg=%s log=%s", ref.label, skip_records[0])
        return True

    if skip_records:
        logger.error(
            "flight leg %s unexpectedly logged same-day skip: %s",
            ref.label,
            skip_records,
        )
        return False
    logger.info("flight PASS leg=%s survivors=%s", ref.label, len(after_same_day))
    return True


async def main() -> int:
    setup_logging()
    if not settings.anthropic_api_key:
        logger.error("ANTHROPIC_API_KEY is not set — cannot run live walkthrough")
        return 1

    logger.info(
        "Starting Phase 3 walkthrough (%s legs). Each Anthropic call can take "
        "1–2+ minutes — progress resumes at activities_research_done.",
        len(REFERENCE_LEGS),
    )
    results: list[tuple[str, bool]] = []
    for index, ref in enumerate(REFERENCE_LEGS, start=1):
        ok = await _run_leg(ref, index=index, total=len(REFERENCE_LEGS))
        results.append((ref.label, ok))

    logger.info("--- Phase 3 walkthrough summary ---")
    all_ok = True
    for label, ok in results:
        logger.info("%s: %s", label, "PASS" if ok else "FAIL")
        all_ok = all_ok and ok

    if all_ok:
        logger.info("All 5 reference legs met Phase 3 exit criteria")
        return 0
    logger.error("One or more legs failed Phase 3 exit criteria")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
