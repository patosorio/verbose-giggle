"""Phase 4 Prompt 2 — research enqueue + options listing API wiring."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    BudgetBand,
    FlightOption,
    Lock,
    OptionCard,
    OptionType,
    RawApiResponse,
    RawApiSource,
)
from services import task_queue


class _TokenEmailSender(Protocol):
    @property
    def last_token(self) -> str: ...


async def _login_as(client: AsyncClient, email_sender: _TokenEmailSender, email: str) -> None:
    request_response = await client.post(
        "/auth/magic-link/request",
        json={"email": email},
    )
    assert request_response.status_code == 202
    verify_response = await client.post(
        "/auth/magic-link/verify",
        json={"token": email_sender.last_token},
    )
    assert verify_response.status_code == 200
    body = verify_response.json()
    assert isinstance(body["access_token"], str) and body["access_token"]
    assert body["token_type"] == "bearer"
    client.headers["Authorization"] = f"Bearer {body['access_token']}"


@pytest.mark.asyncio
async def test_leg_research_forbidden_when_only_trip_member_role_is_organizer(
    client: AsyncClient,
    email_sender: _TokenEmailSender,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reproduce the hand-SQL pitfall: trip_members.role=organizer is NOT enough.

    require_leg_organizer checks trips.organizer_id only (docs/01_architecture.md §6 /
    core/security.py). A trip_members row with role=organizer that doesn't match
    trips.organizer_id must still 403 — same failure mode as the Phase 4 walkthrough
    when organizer_id wasn't actually updated on the trip the API reads.
    """
    from datetime import UTC, datetime
    from uuid import UUID

    from db.models import (
        BudgetBand,
        Leg,
        LegStatus,
        Trip,
        TripMember,
        TripMemberRole,
        TripStatus,
        User,
    )

    async def fake_enqueue(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(task_queue, "enqueue_leg_research", fake_enqueue)

    await _login_as(client, email_sender, "walkthrough-fixer@example.com")
    me = await client.get("/auth/me")
    assert me.status_code == 200
    session_user_id = UUID(me.json()["id"])

    # Simulate Phase 2 walkthrough seed: trip owned by a different user.
    walkthrough_owner = User(
        email="phase2-owner@example.com",
        display_name="Phase2 Owner",
    )
    db_session.add(walkthrough_owner)
    await db_session.flush()

    trip = Trip(
        name="Phase 2 SerpApi walkthrough",
        organizer_id=walkthrough_owner.id,
        home_currency="THB",
        budget_band=BudgetBand.comfort,
        status=TripStatus.planning,
    )
    db_session.add(trip)
    await db_session.flush()

    # Hand-SQL pitfall: insert trip_members organizer row for the logged-in user
    # WITHOUT updating trips.organizer_id.
    db_session.add(
        TripMember(
            trip_id=trip.id,
            user_id=session_user_id,
            invited_email=me.json()["email"],
            role=TripMemberRole.organizer,
            joined_at=datetime.now(UTC),
        )
    )
    leg = Leg(
        trip_id=trip.id,
        sequence_index=0,
        origin="Bangkok",
        destination="Phuket",
        origin_iata="BKK",
        destination_iata="HKT",
        start_date=date(2026, 11, 10),
        end_date=date(2026, 11, 11),
        nights=1,
        filters={"flight": {}, "hotel": {}},
        status=LegStatus.pending,
    )
    db_session.add(leg)
    await db_session.commit()

    forbidden = await client.post(
        f"/legs/{leg.id}/research",
        json={"run_type": "full"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"

    # Correct the authoritative column — then the same session user is allowed.
    trip.organizer_id = session_user_id
    await db_session.commit()

    allowed = await client.post(
        f"/legs/{leg.id}/research",
        json={"run_type": "full"},
    )
    assert allowed.status_code == 202
    assert allowed.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_start_research_returns_202_queued(
    client: AsyncClient,
    email_sender: _TokenEmailSender,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enqueued: list[tuple[object, object, object]] = []

    async def fake_enqueue(leg_id: object, run_id: object, run_type: object) -> None:
        enqueued.append((leg_id, run_id, run_type))

    monkeypatch.setattr(task_queue, "enqueue_leg_research", fake_enqueue)

    await _login_as(client, email_sender, "organizer-research@example.com")
    trip_response = await client.post(
        "/trips",
        json={"name": "Research Trip", "home_currency": "THB", "budget_band": "comfort"},
    )
    assert trip_response.status_code == 201
    trip_id = trip_response.json()["id"]

    legs_response = await client.post(
        f"/trips/{trip_id}/legs:bulk",
        json={
            "legs": [
                {
                    "sequence_index": 0,
                    "origin": "Bangkok",
                    "destination": "Phuket",
                    "origin_iata": "BKK",
                    "destination_iata": "HKT",
                    "start_date": date(2026, 11, 10).isoformat(),
                    "end_date": date(2026, 11, 11).isoformat(),
                    "filters": {"flight": {}, "hotel": {}},
                }
            ]
        },
    )
    assert legs_response.status_code == 201
    leg_id = legs_response.json()[0]["id"]

    start = await client.post(
        f"/legs/{leg_id}/research",
        json={"run_type": "full"},
    )
    assert start.status_code == 202
    body = start.json()
    assert body["status"] == "queued"
    assert enqueued and str(enqueued[0][0]) == leg_id

    status = await client.get(f"/legs/{leg_id}/research/{body['run_id']}")
    assert status.status_code == 200
    assert status.json()["status"] == "queued"
    assert status.json()["error_message"] is None


@pytest.mark.asyncio
async def test_list_options_hides_superseded_except_locked(
    client: AsyncClient,
    email_sender: _TokenEmailSender,
    db_session: AsyncSession,
) -> None:
    await _login_as(client, email_sender, "organizer-options@example.com")
    me = await client.get("/auth/me")
    assert me.status_code == 200
    user_id = me.json()["id"]

    trip_response = await client.post(
        "/trips",
        json={"name": "Options Trip", "home_currency": "THB", "budget_band": "comfort"},
    )
    trip_id = trip_response.json()["id"]
    legs_response = await client.post(
        f"/trips/{trip_id}/legs:bulk",
        json={
            "legs": [
                {
                    "sequence_index": 0,
                    "origin": "Bangkok",
                    "destination": "Phuket",
                    "start_date": date(2026, 11, 10).isoformat(),
                    "end_date": date(2026, 11, 11).isoformat(),
                    "filters": {"flight": {}, "hotel": {}},
                }
            ]
        },
    )
    leg_id = legs_response.json()[0]["id"]

    # Seed cards directly — this test is about listing filters, not research.
    raw = RawApiResponse(
        research_run_id=None,
        source=RawApiSource.serpapi_flights_search,
        request_params={},
        response_body={},
        fetched_at=datetime.now(UTC),
    )
    db_session.add(raw)
    await db_session.flush()

    active = OptionCard(
        leg_id=leg_id,
        option_type=OptionType.flight,
        tier=BudgetBand.budget,
        title="Active Flight",
        base_price_amount=Decimal("1000"),
        currency="THB",
        raw_response_id=raw.id,
    )
    superseded = OptionCard(
        leg_id=leg_id,
        option_type=OptionType.flight,
        tier=BudgetBand.comfort,
        title="Superseded Flight",
        base_price_amount=Decimal("2000"),
        currency="THB",
        raw_response_id=raw.id,
        superseded_at=datetime.now(UTC),
    )
    locked_superseded = OptionCard(
        leg_id=leg_id,
        option_type=OptionType.flight,
        tier=BudgetBand.premium,
        title="Locked Superseded Flight",
        base_price_amount=Decimal("3000"),
        currency="THB",
        raw_response_id=raw.id,
        superseded_at=datetime.now(UTC),
    )
    db_session.add_all([active, superseded, locked_superseded])
    await db_session.flush()

    for card in (active, superseded, locked_superseded):
        db_session.add(
            FlightOption(
                option_card_id=card.id,
                booking_token=f"token-{card.title}",
                departure_airport="BKK",
                arrival_airport="HKT",
                departure_time=datetime(2026, 11, 10, 8, 0, tzinfo=UTC),
                arrival_time=datetime(2026, 11, 10, 9, 30, tzinfo=UTC),
                duration_minutes=90,
                stops=0,
                airlines=["TG"],
                layovers=[],
                bags_included=True,
                emissions_grams=None,
            )
        )
    await db_session.flush()

    db_session.add(
        Lock(
            leg_id=leg_id,
            option_card_id=locked_superseded.id,
            locked_by_user_id=user_id,
            locked_price_amount=Decimal("3000"),
            locked_currency="THB",
            locked_at=datetime.now(UTC),
            unlocked_at=None,
            is_booked=False,
        )
    )
    await db_session.commit()

    response = await client.get(f"/legs/{leg_id}/options")
    assert response.status_code == 200
    titles = {item["title"] for item in response.json()}
    assert titles == {"Active Flight", "Locked Superseded Flight"}
    assert "Superseded Flight" not in titles
