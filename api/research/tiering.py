from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, TypeVar

from db.models import BudgetBand


class Priced(Protocol):
    price_amount: Decimal


T = TypeVar("T", bound=Priced)


def matches_home_currency(currency: str | None, home_currency: str) -> bool:
    """True when currency is present and equals the trip home currency (case-insensitive).

    Used to gate every tiering pool (docs/01_architecture.md §9.12). No conversion.
    """
    if currency is None:
        return False
    return currency.strip().upper() == home_currency.strip().upper()


def assign_price_tiers(items: Sequence[T], *, limit: int = 9) -> list[tuple[BudgetBand, T]]:
    """Cheapest `limit` items, ascending, split into up to 3 groups of up to 3.

    Per docs/01_architecture.md §4.1: cheapest third → budget, middle → comfort,
    priciest → premium. Fewer than 9 results still get consecutive groups of up to 3.
    Callers must currency-gate the input first (§9.12).
    """
    tiered, _overflow = partition_price_tiers(items, limit=limit)
    return tiered


def partition_price_tiers(
    items: Sequence[T],
    *,
    limit: int = 9,
) -> tuple[list[tuple[BudgetBand, T]], list[T]]:
    """Same cheapest-`limit` split as assign_price_tiers, plus the overflow list.

    Overflow items are home-currency-priced candidates that did not make the top-N cut;
    callers persist them with tier=NULL rather than dropping them (§9 / Prompt 4 Bug 3).
    """
    priced = sorted(items, key=lambda item: item.price_amount)
    selected = priced[:limit]
    overflow = list(priced[limit:])
    if not selected:
        return [], overflow

    result: list[tuple[BudgetBand, T]] = []
    tiers = (BudgetBand.budget, BudgetBand.comfort, BudgetBand.premium)
    for index, item in enumerate(selected):
        result.append((tiers[index // 3], item))
    return result, overflow


@dataclass(frozen=True, slots=True)
class PooledPriceItem:
    """Keyed priced member for flight+transport combined tiering (architecture §4.1)."""

    key: str
    price_amount: Decimal


def assign_pooled_price_tiers(
    items: Sequence[PooledPriceItem],
    *,
    limit: int = 9,
) -> dict[str, BudgetBand]:
    """Cheapest-9 / three-way split over a mixed pool; return {key: tier} for selected items.

    Used for combined flight+transport tiering (docs/01_architecture.md §4.1). Keys are
    caller-defined (e.g. flight index, transport index, or option_card_id).
    """
    return {item.key: tier for tier, item in assign_price_tiers(items, limit=limit)}
