from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol, TypeVar

from db.models import BudgetBand


class Priced(Protocol):
    price_amount: Decimal


T = TypeVar("T", bound=Priced)


def assign_price_tiers(items: Sequence[T], *, limit: int = 9) -> list[tuple[BudgetBand, T]]:
    """Cheapest `limit` items, ascending, split into up to 3 groups of up to 3.

    Per docs/01_architecture.md §4.1: cheapest third → budget, middle → comfort,
    priciest → premium. Fewer than 9 results still get consecutive groups of up to 3.
    """
    priced = sorted(items, key=lambda item: item.price_amount)
    selected = priced[:limit]
    if not selected:
        return []

    result: list[tuple[BudgetBand, T]] = []
    tiers = (BudgetBand.budget, BudgetBand.comfort, BudgetBand.premium)
    for index, item in enumerate(selected):
        result.append((tiers[index // 3], item))
    return result
