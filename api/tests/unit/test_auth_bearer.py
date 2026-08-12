"""Bearer JWT transport — docs/01_architecture.md §6 / docs/03_api_contracts.md §1."""

from typing import Protocol

import pytest
from httpx import AsyncClient


class _TokenEmailSender(Protocol):
    @property
    def last_token(self) -> str: ...


@pytest.mark.asyncio
async def test_verify_returns_bearer_access_token(
    client: AsyncClient,
    email_sender: _TokenEmailSender,
) -> None:
    request_response = await client.post(
        "/auth/magic-link/request",
        json={"email": "bearer-verify@example.com"},
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
    assert "user" in body
    assert "set-cookie" not in verify_response.headers


@pytest.mark.asyncio
async def test_me_without_authorization_returns_401(client: AsyncClient) -> None:
    response = await client.get("/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_me_with_garbage_bearer_token_returns_401(client: AsyncClient) -> None:
    response = await client.get(
        "/auth/me",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_me_with_valid_bearer_token(
    client: AsyncClient,
    email_sender: _TokenEmailSender,
) -> None:
    await client.post(
        "/auth/magic-link/request",
        json={"email": "bearer-me@example.com"},
    )
    verify_response = await client.post(
        "/auth/magic-link/verify",
        json={"token": email_sender.last_token},
    )
    access_token = verify_response.json()["access_token"]

    me = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "bearer-me@example.com"
