from datetime import date
from typing import Protocol

import pytest
from httpx import AsyncClient

ORGANIZER_EMAIL = "organizer@example.com"


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

MEMBER_EMAILS = [
    "member1@example.com",
    "member2@example.com",
    "member3@example.com",
    "member4@example.com",
    "member5@example.com",
    "member6@example.com",
]
TRAVELERS = [
    ("Adult 1", "adult"),
    ("Adult 2", "adult"),
    ("Adult 3", "adult"),
    ("Adult 4", "adult"),
    ("Adult 5", "adult"),
    ("Adult 6", "adult"),
    ("Child 1", "child"),
]
REFERENCE_LEGS = [
    {
        "sequence_index": 0,
        "origin": "BKK",
        "destination": "Phuket",
        "start_date": date(2026, 3, 1).isoformat(),
        "end_date": date(2026, 3, 1).isoformat(),
        "filters": {},
    },
    {
        "sequence_index": 1,
        "origin": "Phuket",
        "destination": "Koh Yao Noi",
        "start_date": date(2026, 3, 2).isoformat(),
        "end_date": date(2026, 3, 6).isoformat(),
        "filters": {},
    },
    {
        "sequence_index": 2,
        "origin": "Koh Yao Noi",
        "destination": "Koh Lanta",
        "start_date": date(2026, 3, 6).isoformat(),
        "end_date": date(2026, 3, 8).isoformat(),
        "filters": {},
    },
    {
        "sequence_index": 3,
        "origin": "Koh Lanta",
        "destination": "Krabi",
        "start_date": date(2026, 3, 8).isoformat(),
        "end_date": date(2026, 3, 9).isoformat(),
        "filters": {},
    },
    {
        "sequence_index": 4,
        "origin": "Krabi",
        "destination": "BKK",
        "start_date": date(2026, 3, 9).isoformat(),
        "end_date": date(2026, 3, 9).isoformat(),
        "filters": {},
    },
]


@pytest.mark.asyncio
async def test_phase1_reference_trip_via_api(
    client: AsyncClient,
    email_sender: _TokenEmailSender,
) -> None:
    await _login_as(client, email_sender, ORGANIZER_EMAIL)

    create_trip_response = await client.post(
        "/trips",
        json={
            "name": "Thailand 2026",
            "home_currency": "USD",
            "budget_band": "comfort",
            "budget_target_amount": "12000.00",
        },
    )
    assert create_trip_response.status_code == 201
    trip = create_trip_response.json()
    trip_id = trip["id"]
    assert trip["name"] == "Thailand 2026"
    assert trip["status"] == "planning"

    for email in MEMBER_EMAILS:
        invite_response = await client.post(
            f"/trips/{trip_id}/members",
            json={"email": email},
        )
        assert invite_response.status_code == 201
        member = invite_response.json()
        assert member["invited_email"] == email
        assert member["role"] == "member"
        assert member["user_id"] is None

    travelers_created = []
    for name, age_category in TRAVELERS:
        traveler_response = await client.post(
            f"/trips/{trip_id}/travelers",
            json={"name": name, "age_category": age_category},
        )
        assert traveler_response.status_code == 201
        travelers_created.append(traveler_response.json())

    assert len(travelers_created) == 7
    assert sum(1 for t in travelers_created if t["age_category"] == "adult") == 6
    assert sum(1 for t in travelers_created if t["age_category"] == "child") == 1

    list_travelers_response = await client.get(f"/trips/{trip_id}/travelers")
    assert list_travelers_response.status_code == 200
    assert len(list_travelers_response.json()) == 7

    legs_response = await client.post(
        f"/trips/{trip_id}/legs:bulk",
        json={"legs": REFERENCE_LEGS},
    )
    assert legs_response.status_code == 201
    legs = legs_response.json()
    assert len(legs) == 5
    assert [leg["origin"] for leg in legs] == [
        "BKK",
        "Phuket",
        "Koh Yao Noi",
        "Koh Lanta",
        "Krabi",
    ]
    assert [leg["destination"] for leg in legs] == [
        "Phuket",
        "Koh Yao Noi",
        "Koh Lanta",
        "Krabi",
        "BKK",
    ]
    assert [leg["nights"] for leg in legs] == [0, 4, 2, 1, 0]
    assert all(leg["status"] == "pending" for leg in legs)

    list_legs_response = await client.get(f"/trips/{trip_id}/legs")
    assert list_legs_response.status_code == 200
    assert len(list_legs_response.json()) == 5
