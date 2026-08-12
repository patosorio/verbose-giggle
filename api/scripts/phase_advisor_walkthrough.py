"""Live Anthropic advisor walkthrough — NOT a pytest test.

Prerequisite: ANTHROPIC_API_KEY set; ANTHROPIC_ADVISOR_MODEL verified against the
Anthropic console; `uv add airportsdata` already applied.

Invoke from api/ ONLY when you choose to spend real API budget:

    uv run python scripts/phase_advisor_walkthrough.py

A bare `uv run pytest` must never hit the live Anthropic API.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parents[1]
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from core.config import settings
from core.logging import setup_logging
from schemas.advisor import AdvisorMessageIn, AdvisorTurnIn
from services.advisor import run_advisor_turn

logger = logging.getLogger("advisor_walkthrough")


async def main() -> int:
    setup_logging()
    if not settings.anthropic_api_key:
        logger.error("ANTHROPIC_API_KEY is not set — aborting without calling Anthropic")
        return 1

    logger.info(
        "advisor_walkthrough_start model=%s max_tokens=%s max_turns=%s",
        settings.anthropic_advisor_model,
        settings.anthropic_advisor_max_tokens,
        settings.anthropic_advisor_max_turns,
    )

    turn = AdvisorTurnIn(
        messages=[
            AdvisorMessageIn(
                role="user",
                content="planning a trip to Thailand",
            )
        ],
        current_legs=[],
        trip_name=None,
        home_currency=None,
        budget_band="comfort",
        budget_target_amount=None,
    )
    result = await run_advisor_turn(turn, trace_id="advisor-walkthrough-1")
    logger.info("reply=%s", result.reply)
    logger.info("legs_count=%s trip_name=%s budget_band=%s", len(result.legs), result.trip_name, result.budget_band)
    for index, leg in enumerate(result.legs):
        logger.info(
            "leg[%s] %s -> %s dates=%s/%s origin_iata=%s dest_iata=%s dest_candidates=%s",
            index,
            leg.origin,
            leg.destination,
            leg.start_date,
            leg.end_date,
            leg.origin_iata,
            leg.destination_iata,
            [c.iata for c in leg.destination_candidates],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
