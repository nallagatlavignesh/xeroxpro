"""Print page/sheet/cost maths. Pure functions.

Vocabulary: a *page* is one side of a document page; a *sheet* is one physical piece of paper
(two pages when printing double-sided). Copies are separate, so sheets are never shared between copies.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from business.errors import ValidationError
from business.money import line_amount

_RANGE = re.compile(r"(\d+)(?:\s*-\s*(\d+))?")


def parse_page_ranges(spec: str, page_count: int) -> list[int]:
    """'1-3, 7, 9-10' -> [1, 2, 3, 7, 9, 10] (1-based, unique, in document order). Blank means every page."""
    if page_count < 1:
        raise ValidationError("print.range_out_of_bounds", pages=page_count)
    if not spec.strip():
        return list(range(1, page_count + 1))
    pages: set[int] = set()
    for part in spec.split(","):
        m = _RANGE.fullmatch(part.strip())
        if not m:
            raise ValidationError("print.range_invalid")
        first, last = int(m[1]), int(m[2] or m[1])
        if first < 1 or last < first:
            raise ValidationError("print.range_invalid")
        if last > page_count:
            raise ValidationError("print.range_out_of_bounds", pages=page_count)
        pages.update(range(first, last + 1))
    return sorted(pages)


def sheets_for(pages: int, duplex: bool) -> int:
    return (pages + 1) // 2 if duplex else pages


@dataclass(frozen=True)
class PrintEstimate:
    pages_per_copy: int
    copies: int
    duplex: bool
    sheets_per_copy: int
    total_pages: int
    total_sheets: int
    billing_unit: str
    quantity_per_copy: int  # what goes on the bill line (with `copies` as the multiplier)
    rate: int  # paise per billing unit
    cost: int  # paise


def estimate_print(pages_per_copy: int, copies: int, duplex: bool, rate: int, billing_unit: str) -> PrintEstimate:
    """Cost = rate x (pages, or sheets when the service is billed per sheet) x copies.

    `pages_per_copy` is the number of pages to bill: the owner can override the selected page count when
    reality differs from the document.
    """
    if not isinstance(pages_per_copy, int) or pages_per_copy < 1:
        raise ValidationError("print.pages_positive")
    if not isinstance(copies, int) or copies < 1:
        raise ValidationError("bill.copies_positive")
    if not isinstance(rate, int) or isinstance(rate, bool) or rate < 0:
        raise ValidationError("bill.rate_invalid")
    sheets = sheets_for(pages_per_copy, duplex)
    per_copy = sheets if billing_unit == "sheet" else pages_per_copy
    return PrintEstimate(pages_per_copy, copies, duplex, sheets, pages_per_copy * copies, sheets * copies,
                         billing_unit, per_copy, rate, line_amount(Decimal(per_copy * copies), rate))
