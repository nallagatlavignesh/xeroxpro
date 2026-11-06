"""Pure bill calculations. Money is integer paise, quantities are Decimal. No DB, no Qt."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from business.errors import ValidationError
from business.money import line_amount

PAYMENT_METHODS = ("cash", "upi", "other")


@dataclass(frozen=True)
class LineInput:
    """One bill line as the cashier enters it. Effective quantity = quantity x copies."""

    quantity: Decimal
    unit_rate: int  # paise
    copies: int = 1

    @property
    def effective_quantity(self) -> Decimal:
        return Decimal(self.quantity) * self.copies

    @property
    def amount(self) -> int:
        return line_amount(self.effective_quantity, self.unit_rate)


@dataclass(frozen=True)
class PaymentInput:
    amount: int  # paise
    method: str
    reference: str | None = None


@dataclass(frozen=True)
class Totals:
    subtotal: int
    discount: int
    grand_total: int
    total_paid: int
    outstanding: int
    status: str  # unpaid | partial | paid


def validate_line(line: LineInput) -> None:
    if line.quantity is None or Decimal(line.quantity) <= 0:
        raise ValidationError("bill.quantity_positive")
    if not isinstance(line.copies, int) or isinstance(line.copies, bool) or line.copies < 1:
        raise ValidationError("bill.copies_positive")
    if not isinstance(line.unit_rate, int) or isinstance(line.unit_rate, bool) or line.unit_rate < 0:
        raise ValidationError("bill.rate_invalid")


def discount_from_percent(subtotal: int, percent: Decimal) -> int:
    if not (Decimal(0) <= percent <= 100):
        raise ValidationError("bill.discount_invalid")
    return int((Decimal(subtotal) * percent / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def compute_totals(lines: list[LineInput], discount: int = 0, payments: list[PaymentInput] | None = None) -> Totals:
    """Validate and total a bill. Raises ValidationError (with a translation key) on bad input."""
    if not lines:
        raise ValidationError("bill.no_lines")
    for line in lines:
        validate_line(line)
    subtotal = sum(line.amount for line in lines)
    if not isinstance(discount, int) or discount < 0 or discount > subtotal:
        raise ValidationError("bill.discount_invalid")
    grand_total = subtotal - discount
    total_paid = 0
    for p in payments or []:
        if p.amount <= 0:
            raise ValidationError("bill.payment_positive")
        if p.method not in PAYMENT_METHODS:
            raise ValidationError("bill.payment_method_invalid")
        total_paid += p.amount
    if total_paid > grand_total:
        raise ValidationError("bill.overpayment")
    outstanding = grand_total - total_paid
    status = "paid" if outstanding == 0 else "partial" if total_paid > 0 else "unpaid"
    return Totals(subtotal, discount, grand_total, total_paid, outstanding, status)
