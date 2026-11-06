"""Shape shared by every report so one screen, one PDF writer and one Excel writer can show them all."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from business.errors import ValidationError
from business.money import format_inr


@dataclass(frozen=True)
class Column:
    label: str  # translation key
    kind: str = "text"  # text | money | qty | int | key (cell value is a translation key)


@dataclass(frozen=True)
class SummaryLine:
    label: str
    value: Any
    kind: str = "money"  # money | int | text
    translate: bool = True  # False when `label` is data (e.g. an expense category name)
    emphasis: bool = False


@dataclass(frozen=True)
class Report:
    key: str
    title: str  # translation key
    columns: list[Column]
    rows: list[list[Any]]  # raw values: paise for money, Decimal for qty, int, str
    total_row: list[Any] | None = None  # same shape as a row; None cells are left blank
    summary: list[SummaryLine] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # translation keys
    period: tuple[str, str] | None = None  # ISO dates, inclusive


def format_value(value: Any, kind: str, tr=None) -> str:
    """Display text for a cell. kind 'key' cells hold a translation key (needs `tr`)."""
    if value is None or value == "":
        return ""
    if kind == "key":
        return tr(value)
    if kind == "money":
        return format_inr(value)
    if kind == "qty":
        return f"{Decimal(value).normalize():f}"
    return str(value)


def dmy(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}-{m}-{y}"


def period_range(kind: str, anchor: date) -> tuple[date, date]:
    """day = the date; week = Monday..Sunday containing it; month = the calendar month."""
    if kind == "day":
        return anchor, anchor
    if kind == "week":
        start = anchor - timedelta(days=anchor.weekday())
        return start, start + timedelta(days=6)
    if kind == "month":
        start = anchor.replace(day=1)
        next_month = (start + timedelta(days=32)).replace(day=1)
        return start, next_month - timedelta(days=1)
    raise ValidationError("report.period_invalid")
