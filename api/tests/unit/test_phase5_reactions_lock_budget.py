"""Phase 5 Prompt 1 — reactions, lock/unlock/booked, budget aggregation."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    BudgetBand,
    Lock,
    LockEvent,
    LockEventType,
    OptionCard,
    OptionType,
    RawApiResponse,
    RawApiSource,
    Reaction,
    ReactionType,
)


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


async def _create_trip_with_legs(
    client: AsyncClient,
    *,
    name: str,
    leg_count: int = 1,
) -> tuple[str, list[str]]:
    trip_response = await client.post(
        "/trips",
        json={"name": name, "home_currency": "THB", "budget_band": "comfort"},
    )
    assert trip_response.status_code == 201
    trip_id = trip_response.json()["id"]

    legs_payload = {
        "legs": [
            {
                "sequence_index": i,
                "origin": f"Origin {i}",
                "destination": f"Destination {i}",
                "start_date": date(2026, 11, 10 + i).isoformat(),
                "end_date": date(2026, 11, 11 + i).isoformat(),
                "filters": {"flight": {}, "hotel": {}},
            }
            for i in range(leg_count)
        ]
    }
    legs_response = await client.post(f"/trips/{trip_id}/legs:bulk", json=legs_payload)
    assert legs_response.status_code == 201
    leg_ids = [leg["id"] for leg in legs_response.json()]
    return trip_id, leg_ids


async def _seed_option_card(
    db_session: AsyncSession,
    *,
    leg_id: str | UUID,
    title: str,
    base_price_amount: Decimal | None,
    currency: str = "THB",
    option_type: OptionType = OptionType.flight,
    tier: BudgetBand | None = BudgetBand.budget,
) -> OptionCard:
    raw = RawApiResponse(
        research_run_id=None,
        source=RawApiSource.serpapi_flights_search,
        request_params={},
        response_body={},
        fetched_at=datetime.now(UTC),
    )
    db_session.add(raw)
    await db_session.flush()

    card = OptionCard(
        leg_id=leg_id,
        option_type=option_type,
        tier=tier,
        title=title,
        base_price_amount=base_price_amount,
        currency=currency,
        raw_response_id=raw.id,
    )
    db_session.add(card)
    await db_session.commit()
    await db_session.refresh(card)
    return card


@pytest.mark.asyncio
async def test_reaction_upsert_updates_not_duplicates(
    client: AsyncClient,
    email_sender: _TokenEmailSender,
    db_session: AsyncSession,
) -> None:
    await _login_as(client, email_sender, "react-upsert@example.com")
    _, leg_ids = await _create_trip_with_legs(client, name="Reaction Upsert Trip")
    card = await _seed_option_card(
        db_session,
        leg_id=leg_ids[0],
        title="Reactable Flight",
        base_price_amount=Decimal("1500.00"),
    )

    first = await client.post(
        f"/options/{card.id}/reactions",
        json={"reaction_type": "up"},
    )
    assert first.status_code == 200
    assert first.json() == {"up": 1, "down": 0, "my_reaction": "up"}

    second = await client.post(
        f"/options/{card.id}/reactions",
        json={"reaction_type": "down"},
    )
    assert second.status_code == 200
    assert second.json() == {"up": 0, "down": 1, "my_reaction": "down"}

    count_result = await db_session.execute(
        select(func.count()).select_from(Reaction).where(Reaction.option_card_id == card.id)
    )
    assert count_result.scalar_one() == 1

    row_result = await db_session.execute(
        select(Reaction).where(Reaction.option_card_id == card.id)
    )
    row = row_result.scalar_one()
    assert row.reaction_type == ReactionType.down


@pytest.mark.asyncio
async def test_reaction_delete_is_idempotent(
    client: AsyncClient,
    email_sender: _TokenEmailSender,
    db_session: AsyncSession,
) -> None:
    await _login_as(client, email_sender, "react-delete@example.com")
    _, leg_ids = await _create_trip_with_legs(client, name="Reaction Delete Trip")
    card = await _seed_option_card(
        db_session,
        leg_id=leg_ids[0],
        title="Deletable Reaction Flight",
        base_price_amount=Decimal("1200.00"),
    )

    created = await client.post(
        f"/options/{card.id}/reactions",
        json={"reaction_type": "up"},
    )
    assert created.status_code == 200
    assert created.json()["my_reaction"] == "up"

    first_delete = await client.delete(f"/options/{card.id}/reactions")
    assert first_delete.status_code == 200
    assert first_delete.json() == {"up": 0, "down": 0, "my_reaction": None}

    second_delete = await client.delete(f"/options/{card.id}/reactions")
    assert second_delete.status_code == 200
    assert second_delete.json() == {"up": 0, "down": 0, "my_reaction": None}


@pytest.mark.asyncio
async def test_lock_rejects_null_price_card(
    client: AsyncClient,
    email_sender: _TokenEmailSender,
    db_session: AsyncSession,
) -> None:
    await _login_as(client, email_sender, "lock-null-price@example.com")
    _, leg_ids = await _create_trip_with_legs(client, name="Null Price Lock Trip")
    card = await _seed_option_card(
        db_session,
        leg_id=leg_ids[0],
        title="Priceless Transport",
        base_price_amount=None,
        currency="THB",
        option_type=OptionType.transport,
        tier=None,
    )

    response = await client.post(
        f"/legs/{leg_ids[0]}/lock",
        json={"option_card_id": str(card.id)},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.asyncio
async def test_lock_rejects_foreign_currency_card(
    client: AsyncClient,
    email_sender: _TokenEmailSender,
    db_session: AsyncSession,
) -> None:
    await _login_as(client, email_sender, "lock-fx@example.com")
    _, leg_ids = await _create_trip_with_legs(client, name="Foreign Currency Lock Trip")
    card = await _seed_option_card(
        db_session,
        leg_id=leg_ids[0],
        title="USD Ferry",
        base_price_amount=Decimal("45.00"),
        currency="USD",
        option_type=OptionType.transport,
        tier=None,
    )

    response = await client.post(
        f"/legs/{leg_ids[0]}/lock",
        json={"option_card_id": str(card.id)},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"]["option_currency"] == "USD"
    assert body["error"]["details"]["home_currency"] == "THB"


@pytest.mark.asyncio
async def test_lock_rejects_second_active_lock(
    client: AsyncClient,
    email_sender: _TokenEmailSender,
    db_session: AsyncSession,
) -> None:
    await _login_as(client, email_sender, "lock-conflict@example.com")
    _, leg_ids = await _create_trip_with_legs(client, name="Lock Conflict Trip")
    first = await _seed_option_card(
        db_session,
        leg_id=leg_ids[0],
        title="First Lockable",
        base_price_amount=Decimal("1000.00"),
    )
    second = await _seed_option_card(
        db_session,
        leg_id=leg_ids[0],
        title="Second Lockable",
        base_price_amount=Decimal("2000.00"),
        tier=BudgetBand.comfort,
    )

    locked = await client.post(
        f"/legs/{leg_ids[0]}/lock",
        json={"option_card_id": str(first.id)},
    )
    assert locked.status_code == 200
    assert locked.json()["option_card_id"] == str(first.id)

    conflict = await client.post(
        f"/legs/{leg_ids[0]}/lock",
        json={"option_card_id": str(second.id)},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "conflict"


@pytest.mark.asyncio
async def test_unlock_then_relock_writes_lock_events(
    client: AsyncClient,
    email_sender: _TokenEmailSender,
    db_session: AsyncSession,
) -> None:
    await _login_as(client, email_sender, "lock-relock@example.com")
    _, leg_ids = await _create_trip_with_legs(client, name="Unlock Relock Trip")
    first = await _seed_option_card(
        db_session,
        leg_id=leg_ids[0],
        title="Lock A",
        base_price_amount=Decimal("1100.00"),
    )
    second = await _seed_option_card(
        db_session,
        leg_id=leg_ids[0],
        title="Lock B",
        base_price_amount=Decimal("2200.00"),
        tier=BudgetBand.comfort,
    )

    lock_one = await client.post(
        f"/legs/{leg_ids[0]}/lock",
        json={"option_card_id": str(first.id)},
    )
    assert lock_one.status_code == 200

    unlock = await client.delete(f"/legs/{leg_ids[0]}/lock")
    assert unlock.status_code == 204

    lock_two = await client.post(
        f"/legs/{leg_ids[0]}/lock",
        json={"option_card_id": str(second.id)},
    )
    assert lock_two.status_code == 200
    assert lock_two.json()["option_card_id"] == str(second.id)

    events_result = await db_session.execute(
        select(LockEvent.event_type)
        .join(Lock, Lock.id == LockEvent.lock_id)
        .where(Lock.leg_id == leg_ids[0])
        .order_by(LockEvent.occurred_at.asc(), LockEvent.event_type.asc())
    )
    event_types = list(events_result.scalars().all())
    assert event_types == [
        LockEventType.locked,
        LockEventType.unlocked,
        LockEventType.locked,
    ]


@pytest.mark.asyncio
async def test_booked_toggle_404_without_active_lock(
    client: AsyncClient,
    email_sender: _TokenEmailSender,
) -> None:
    await _login_as(client, email_sender, "booked-404@example.com")
    _, leg_ids = await _create_trip_with_legs(client, name="Booked Without Lock Trip")

    response = await client.patch(
        f"/legs/{leg_ids[0]}/lock/booked",
        json={"is_booked": True},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_budget_running_total_matches_locked_sum(
    client: AsyncClient,
    email_sender: _TokenEmailSender,
    db_session: AsyncSession,
) -> None:
    await _login_as(client, email_sender, "budget-sum@example.com")
    trip_id, leg_ids = await _create_trip_with_legs(
        client,
        name="Budget Sum Trip",
        leg_count=3,
    )

    card0 = await _seed_option_card(
        db_session,
        leg_id=leg_ids[0],
        title="Leg0 Flight",
        base_price_amount=Decimal("1000.00"),
    )
    card1 = await _seed_option_card(
        db_session,
        leg_id=leg_ids[1],
        title="Leg1 Flight",
        base_price_amount=Decimal("2500.50"),
    )
    await _seed_option_card(
        db_session,
        leg_id=leg_ids[2],
        title="Leg2 Unlocked Flight",
        base_price_amount=Decimal("9999.00"),
    )

    lock0 = await client.post(
        f"/legs/{leg_ids[0]}/lock",
        json={"option_card_id": str(card0.id)},
    )
    assert lock0.status_code == 200
    lock1 = await client.post(
        f"/legs/{leg_ids[1]}/lock",
        json={"option_card_id": str(card1.id)},
    )
    assert lock1.status_code == 200

    expected_total = Decimal("1000.00") + Decimal("2500.50")
    response = await client.get(f"/trips/{trip_id}/budget")
    assert response.status_code == 200
    body = response.json()
    assert body["home_currency"] == "THB"
    assert body["budget_band"] == "comfort"
    assert Decimal(body["running_total"]) == expected_total
    assert len(body["by_leg"]) == 3

    by_leg = {entry["leg_id"]: entry for entry in body["by_leg"]}
    assert by_leg[leg_ids[0]]["locked_option_id"] == str(card0.id)
    assert Decimal(by_leg[leg_ids[0]]["amount"]) == Decimal("1000.00")
    assert by_leg[leg_ids[1]]["locked_option_id"] == str(card1.id)
    assert Decimal(by_leg[leg_ids[1]]["amount"]) == Decimal("2500.50")
    assert by_leg[leg_ids[2]]["locked_option_id"] is None
    assert by_leg[leg_ids[2]]["amount"] is None
