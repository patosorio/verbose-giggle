"""Activities overflow persistence (Prompt 4 Bug 3)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    BudgetBand,
    Leg,
    LegStatus,
    ResearchRun,
    ResearchRunStatus,
    ResearchRunType,
    Trip,
    TripStatus,
    User,
)
from research.types import (
    ActivitiesResearchParsed,
    ParsedActivityOption,
    ParsedCitation,
    SuggestedTiming,
)
from services.activities import persist_activities_research


def _activity(price: int) -> ParsedActivityOption:
    return ParsedActivityOption(
        title=f"Activity {price}",
        category="tour",
        description=f"Desc {price}",
        duration_minutes=60,
        estimated_price_amount=Decimal(price),
        estimated_price_currency="THB",
        citations=[
            ParsedCitation(
                claim_text=f"Claim {price}",
                source_url=f"https://example.com/{price}",
            )
        ],
        suggested_timing=SuggestedTiming.flexible,
    )


@pytest.mark.asyncio
async def test_persist_activities_keeps_overflow_with_null_tier(
    db_session: AsyncSession,
) -> None:
    user = User(email=f"{uuid4()}@example.com", display_name="Organizer")
    db_session.add(user)
    await db_session.flush()
    trip = Trip(
        name="Reference",
        organizer_id=user.id,
        home_currency="THB",
        budget_band=BudgetBand.comfort,
        status=TripStatus.planning,
    )
    db_session.add(trip)
    await db_session.flush()
    leg = Leg(
        trip_id=trip.id,
        sequence_index=0,
        origin="Bangkok",
        destination="Phuket",
        start_date=date(2026, 11, 10),
        end_date=date(2026, 11, 14),
        nights=4,
        filters={},
        status=LegStatus.pending,
    )
    db_session.add(leg)
    await db_session.flush()
    run = ResearchRun(
        leg_id=leg.id,
        run_type=ResearchRunType.activities,
        status=ResearchRunStatus.running,
        attempt_count=1,
        trace_id=str(uuid4()),
        started_at=datetime.now(UTC),
    )
    db_session.add(run)
    await db_session.commit()

    activities = [_activity(100 * i) for i in range(1, 12)]
    cards = await persist_activities_research(
        db_session,
        leg_id=leg.id,
        parsed=ActivitiesResearchParsed(
            request_params={"destination": "Phuket"},
            response_body={},
            activities=activities,
            extraction_failed=False,
            extraction_error=None,
        ),
        research_run_id=run.id,
        trace_id=run.trace_id,
    )
    assert len(cards) == 11
    by_price = {int(c.base_price_amount or 0): c.tier for c in cards}
    assert by_price[100] == BudgetBand.budget
    assert by_price[900] == BudgetBand.premium
    assert by_price[1000] is None
    assert by_price[1100] is None
    assert sum(1 for t in by_price.values() if t is None) == 2
