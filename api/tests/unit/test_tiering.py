import json
from decimal import Decimal
from pathlib import Path

from db.models import BudgetBand
from research.tiering import assign_price_tiers, matches_home_currency
from research.types import ParsedFlightOption


def _flight(price: int, token: str = "t", currency: str = "THB") -> ParsedFlightOption:
    from datetime import datetime

    return ParsedFlightOption(
        booking_token=token,
        title=f"Flight {price}",
        price_amount=Decimal(price),
        currency=currency,
        departure_airport="BKK",
        arrival_airport="HKT",
        departure_time=datetime(2026, 11, 10, 7, 0),
        arrival_time=datetime(2026, 11, 10, 8, 20),
        duration_minutes=80,
        stops=0,
        airlines=["Thai Airways"],
        layovers=[],
        bags_included=False,
        emissions_grams=None,
    )


def test_matches_home_currency() -> None:
    assert matches_home_currency("THB", "THB") is True
    assert matches_home_currency("thb", "THB") is True
    assert matches_home_currency("USD", "THB") is False
    assert matches_home_currency(None, "THB") is False


def test_tiering_nine_results_three_buckets_of_three() -> None:
    items = [_flight(p, token=f"t{p}") for p in (90, 10, 50, 20, 80, 30, 70, 40, 60)]
    tiered = assign_price_tiers(items)
    assert len(tiered) == 9
    prices = [item.price_amount for _, item in tiered]
    assert prices == [Decimal(p) for p in (10, 20, 30, 40, 50, 60, 70, 80, 90)]
    tiers = [tier for tier, _ in tiered]
    assert tiers == [
        BudgetBand.budget,
        BudgetBand.budget,
        BudgetBand.budget,
        BudgetBand.comfort,
        BudgetBand.comfort,
        BudgetBand.comfort,
        BudgetBand.premium,
        BudgetBand.premium,
        BudgetBand.premium,
    ]


def test_tiering_caps_at_nine_cheapest() -> None:
    items = [_flight(p) for p in range(1, 15)]
    tiered = assign_price_tiers(items)
    assert len(tiered) == 9
    assert [item.price_amount for _, item in tiered] == [Decimal(p) for p in range(1, 10)]


def test_tiering_partial_groups() -> None:
    items = [_flight(p) for p in (5, 1, 3, 2)]
    tiered = assign_price_tiers(items)
    assert [(tier, item.price_amount) for tier, item in tiered] == [
        (BudgetBand.budget, Decimal(1)),
        (BudgetBand.budget, Decimal(2)),
        (BudgetBand.budget, Decimal(3)),
        (BudgetBand.comfort, Decimal(5)),
    ]


def test_partition_price_tiers_returns_overflow() -> None:
    from research.tiering import partition_price_tiers

    items = [_flight(p) for p in range(1, 12)]
    tiered, overflow = partition_price_tiers(items)
    assert len(tiered) == 9
    assert [item.price_amount for _, item in tiered] == [Decimal(p) for p in range(1, 10)]
    assert [item.price_amount for item in overflow] == [Decimal(10), Decimal(11)]


def test_pooled_tiers_interleave_keys() -> None:
    from research.tiering import PooledPriceItem, assign_pooled_price_tiers

    pool = [
        PooledPriceItem(key="f:100", price_amount=Decimal(100)),
        PooledPriceItem(key="t:200", price_amount=Decimal(200)),
        PooledPriceItem(key="f:400", price_amount=Decimal(400)),
        PooledPriceItem(key="t:300", price_amount=Decimal(300)),
    ]
    tiers = assign_pooled_price_tiers(pool)
    assert tiers["f:100"] == BudgetBand.budget
    assert tiers["t:200"] == BudgetBand.budget
    assert tiers["t:300"] == BudgetBand.budget
    assert tiers["f:400"] == BudgetBand.comfort


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "serpapi"


def test_parse_flights_fixture_sorted_by_price_for_tiering() -> None:
    from research.serpapi import parse_flight_options

    body = json.loads((FIXTURES / "flights_search.json").read_text())
    flights = parse_flight_options(body, currency="THB")
    assert len(flights) == 10
    tiered = assign_price_tiers(flights)
    assert len(tiered) == 9
    assert tiered[0][1].price_amount == Decimal("1650")
    assert tiered[-1][1].price_amount == Decimal("4200")
    assert sum(1 for tier, _ in tiered if tier == BudgetBand.budget) == 3
    assert sum(1 for tier, _ in tiered if tier == BudgetBand.comfort) == 3
    assert sum(1 for tier, _ in tiered if tier == BudgetBand.premium) == 3
