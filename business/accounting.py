"""Pure accounting rules. Sales, collections, credit, expenses and cash movement are kept separate on purpose."""
from __future__ import annotations

from business.billing import PAYMENT_METHODS
from business.errors import ValidationError


def allocate_payment(amount: int, outstanding_bills: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Spread a customer payment over bills in the order given (oldest first).

    `outstanding_bills` = [(bill_id, outstanding paise)]. Returns [(bill_id, paise)] summing to `amount`.
    A payment larger than everything owed is refused (no advance balances in v1).
    """
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise ValidationError("bill.payment_positive")
    if amount > sum(owed for _, owed in outstanding_bills):
        raise ValidationError("payment.exceeds_outstanding")
    out, remaining = [], amount
    for bill_id, owed in outstanding_bills:
        if remaining == 0:
            break
        take = min(owed, remaining)
        out.append((bill_id, take))
        remaining -= take
    return out


def check_method(method: str) -> None:
    if method not in PAYMENT_METHODS:
        raise ValidationError("bill.payment_method_invalid")


def cash_movement(cash_collected: int, cash_refunded: int, cash_expenses: int) -> int:
    """Net change in the cash drawer. This is NOT sales minus expenses."""
    return cash_collected - cash_refunded - cash_expenses


def expected_drawer(opening_cash: int, movement: int) -> int:
    return opening_cash + movement


def estimated_profit(sales: int, cost_of_goods: int, operating_expenses: int) -> int:
    """Sales - stationery cost at sale time - operating expenses. An estimate: paper/toner per page is not costed."""
    return sales - cost_of_goods - operating_expenses


def closing_difference(counted_cash: int, expected_cash: int) -> int:
    """Positive = more cash than the books expect, negative = short."""
    return counted_cash - expected_cash
