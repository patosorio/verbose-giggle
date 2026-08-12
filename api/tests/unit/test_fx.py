"""FX convert-at-persist — Frankfurter via httpx (no extra deps)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from services.fx import fetch_fx_rate, resolve_home_price


@pytest.mark.asyncio
async def test_resolve_home_price_same_currency_no_snapshot() -> None:
    amount, currency, fx = await resolve_home_price(
        amount=Decimal("450.00"),
        currency="THB",
        home_currency="THB",
    )
    assert amount == Decimal("450.00")
    assert currency == "THB"
    assert fx is None


@pytest.mark.asyncio
async def test_resolve_home_price_converts_and_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_rate(
        *,
        from_currency: str,
        to_currency: str,
        client: httpx.AsyncClient | None = None,
    ) -> tuple[Decimal, date]:
        assert from_currency == "USD"
        assert to_currency == "THB"
        return Decimal("35.5"), date(2026, 8, 11)

    monkeypatch.setattr("services.fx.fetch_fx_rate", fake_rate)

    amount, currency, fx = await resolve_home_price(
        amount=Decimal("22.00"),
        currency="USD",
        home_currency="THB",
    )
    assert currency == "THB"
    assert amount == Decimal("781.00")  # 22 * 35.5
    assert fx is not None
    assert fx.original_amount == Decimal("22.00")
    assert fx.original_currency == "USD"
    assert fx.fx_rate == Decimal("35.5")
    assert fx.fx_rate_as_of == date(2026, 8, 11)


@pytest.mark.asyncio
async def test_fetch_fx_rate_parses_frankfurter_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "amount": 1.0,
        "base": "USD",
        "date": "2026-08-11",
        "rates": {"THB": 35.123456},
    }

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    rate, as_of = await fetch_fx_rate(
        from_currency="USD",
        to_currency="THB",
        client=mock_client,
    )
    assert rate == Decimal("35.123456")
    assert as_of == date(2026, 8, 11)
    mock_client.get.assert_awaited_once()
