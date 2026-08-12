"""Home-currency FX conversion for agent-researched prices (activities/transport).

Uses the Frankfurter API (ECB reference rates) via httpx — no extra dependency.
Flights/hotels stay SerpApi-forced home currency; this path only covers Claude-extracted
fares that arrive in a source currency (docs/01_architecture.md §9.1 exception).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

_MONEY = Decimal("0.01")
_RATE_QUANT = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class FxConversion:
    """Snapshot of a conversion applied at research persist."""

    home_amount: Decimal
    home_currency: str
    original_amount: Decimal
    original_currency: str
    fx_rate: Decimal  # home units per 1 original unit
    fx_rate_as_of: date


@dataclass
class _RateCache:
    rates: dict[tuple[str, str], tuple[Decimal, date]]

    def __init__(self) -> None:
        self.rates = {}


async def fetch_fx_rate(
    *,
    from_currency: str,
    to_currency: str,
    client: httpx.AsyncClient | None = None,
) -> tuple[Decimal, date]:
    """Return (rate, as_of_date) where rate is `to` units per 1 `from` unit."""
    base = from_currency.strip().upper()
    quote = to_currency.strip().upper()
    if base == quote:
        return Decimal("1"), date.today()

    url = f"{settings.fx_api_base_url.rstrip('/')}/latest"
    params = {"from": base, "to": quote}

    async def _get(http: httpx.AsyncClient) -> tuple[Decimal, date]:
        response = await http.get(url, params=params, timeout=10.0)
        response.raise_for_status()
        body = response.json()
        rates = body.get("rates")
        if not isinstance(rates, dict) or quote not in rates:
            raise ValueError(f"FX response missing rate {base}->{quote}: {body!r}")
        rate = Decimal(str(rates[quote])).quantize(_RATE_QUANT)
        as_of_raw = body.get("date")
        as_of = date.fromisoformat(str(as_of_raw)) if as_of_raw else date.today()
        return rate, as_of

    if client is not None:
        return await _get(client)
    async with httpx.AsyncClient() as http:
        return await _get(http)


async def resolve_home_price(
    *,
    amount: Decimal,
    currency: str,
    home_currency: str,
    cache: _RateCache | None = None,
    client: httpx.AsyncClient | None = None,
) -> tuple[Decimal, str, FxConversion | None]:
    """Convert `amount`/`currency` into trip home currency.

    Returns (home_amount, home_currency, conversion_or_none).
    On FX failure, returns the original amount/currency unchanged (caller keeps
    foreign-currency / non-lockable behavior) and logs.
    """
    home = home_currency.strip().upper()
    source = currency.strip().upper()
    if source == home:
        return amount.quantize(_MONEY), home, None

    rate_cache = cache if cache is not None else _RateCache()
    key = (source, home)
    try:
        if key not in rate_cache.rates:
            rate_cache.rates[key] = await fetch_fx_rate(
                from_currency=source,
                to_currency=home,
                client=client,
            )
        rate, as_of = rate_cache.rates[key]
        home_amount = (amount * rate).quantize(_MONEY, rounding=ROUND_HALF_UP)
        conversion = FxConversion(
            home_amount=home_amount,
            home_currency=home,
            original_amount=amount.quantize(_MONEY),
            original_currency=source,
            fx_rate=rate,
            fx_rate_as_of=as_of,
        )
        logger.info(
            "fx_converted from=%s to=%s amount=%s rate=%s home_amount=%s as_of=%s",
            source,
            home,
            amount,
            rate,
            home_amount,
            as_of.isoformat(),
        )
        return home_amount, home, conversion
    except Exception:
        logger.exception(
            "fx_convert_failed from=%s to=%s amount=%s — keeping source currency",
            source,
            home,
            amount,
        )
        return amount.quantize(_MONEY), source, None


def new_rate_cache() -> _RateCache:
    return _RateCache()
