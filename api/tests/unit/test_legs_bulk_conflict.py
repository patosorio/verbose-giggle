"""POST /trips/{id}/legs:bulk conflict on duplicate sequence_index."""

from datetime import date
from typing import Protocol

import pytest
from httpx import AsyncClient


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


@pytest.mark.asyncio
async def test_bulk_create_legs_rejects_existing_sequence_index(
    client: AsyncClient,
    email_sender: _TokenEmailSender,
) -> None:
    await _login_as(client, email_sender, "organizer-legs-conflict@example.com")

    trip_response = await client.post(
        "/trips",
        json={
            "name": "Conflict Trip",
            "home_currency": "THB",
            "budget_band": "comfort",
        },
    )
    assert trip_response.status_code == 201
    trip_id = trip_response.json()["id"]

    first_leg = {
        "sequence_index": 0,
        "origin": "BKK",
        "destination": "Phuket",
        "start_date": date(2026, 11, 10).isoformat(),
        "end_date": date(2026, 11, 11).isoformat(),
        "filters": {"flight": {}, "hotel": {}},
    }
    create_response = await client.post(
        f"/trips/{trip_id}/legs:bulk",
        json={"legs": [first_leg]},
    )
    assert create_response.status_code == 201
    assert len(create_response.json()) == 1

    conflict_response = await client.post(
        f"/trips/{trip_id}/legs:bulk",
        json={
            "legs": [
                first_leg,
                {
                    "sequence_index": 1,
                    "origin": "Phuket",
                    "destination": "Koh Yao Noi",
                    "start_date": date(2026, 11, 11).isoformat(),
                    "end_date": date(2026, 11, 15).isoformat(),
                    "filters": {"flight": {}, "hotel": {}},
                },
            ]
        },
    )
    assert conflict_response.status_code == 409
    body = conflict_response.json()
    assert body["error"]["code"] == "conflict"
    assert body["error"]["details"]["sequence_indexes"] == [0]

    list_response = await client.get(f"/trips/{trip_id}/legs")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1
