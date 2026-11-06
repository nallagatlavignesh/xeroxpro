"""Money helpers. All amounts are integer paise; quantities are Decimal."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def to_paise(value: str | int | Decimal) -> int:
    """Rupees (e.g. "12.50") -> paise. Floats are refused; more than 2 decimals is an error."""
    if isinstance(value, (float, bool)):
        raise TypeError("money must be str, int or Decimal, not float")
    try:
        rupees = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValueError(f"not a valid amount: {value!r}") from None
    paise = rupees * 100
    if paise != paise.to_integral_value():
        raise ValueError("amount has more than 2 decimal places")
    return int(paise)


def round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def line_amount(quantity: Decimal, unit_rate: int) -> int:
    """quantity x rate in paise, rounded half-up (same rule as the bill_items CHECK constraint)."""
    return round_half_up(Decimal(quantity) * unit_rate)


def format_inr(paise: int, symbol: bool = True) -> str:
    """Indian digit grouping: 12345678 paise -> ₹1,23,456.78."""
    sign = "-" if paise < 0 else ""
    rupees, pc = divmod(abs(paise), 100)
    digits = str(rupees)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    return f"{sign}{'₹' if symbol else ''}{digits}.{pc:02d}"
