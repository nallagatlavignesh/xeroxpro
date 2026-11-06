"""Daily closing: compare the cash the books say should be in the drawer with what was counted."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from application.services import accounting_queries
from business.accounting import closing_difference, expected_drawer
from business.errors import ValidationError
from business.timeutil import ist_today, utc_now_iso
from database.models import AuditLog, DailyClosing


@dataclass(frozen=True)
class ClosingPreview:
    day: str
    opening_cash: int  # last closing's counted cash, unless the owner overrides it
    cash_movement: int
    expected_cash: int
    existing: DailyClosing | None


def preview(session: Session, day: str, opening_cash: int | None = None) -> ClosingPreview:
    existing = session.scalar(select(DailyClosing).where(DailyClosing.closing_date == day))
    if opening_cash is None:
        previous = session.scalar(select(DailyClosing).where(DailyClosing.closing_date < day)
                                  .order_by(DailyClosing.closing_date.desc()).limit(1))
        opening_cash = existing.opening_cash if existing else (previous.counted_cash if previous else 0)
    movement = accounting_queries.cash_movement(session, day)
    return ClosingPreview(day, opening_cash, movement, expected_drawer(opening_cash, movement), existing)


def close_day(session: Session, day: str, counted_cash: int, opening_cash: int, notes: str = "",
              clock: Callable[[], str] = utc_now_iso) -> DailyClosing:
    """Record (or correct, with an audit row) the closing for `day`."""
    if counted_cash < 0 or opening_cash < 0:
        raise ValidationError("closing.negative")
    if date.fromisoformat(day) > ist_today():
        raise ValidationError("expense.date_future")
    p = preview(session, day, opening_cash)
    difference = closing_difference(counted_cash, p.expected_cash)
    closing = p.existing
    if closing is None:
        closing = DailyClosing(closing_date=day, created_at=clock())
        session.add(closing)
    else:
        session.add(AuditLog(action="closing_corrected", entity_type="daily_closing", entity_id=closing.id, at=clock(),
                             reason="closing re-saved", details=json.dumps({
                                 "before": {"counted": closing.counted_cash, "expected": closing.expected_cash}})))
    closing.opening_cash, closing.expected_cash = opening_cash, p.expected_cash
    closing.counted_cash, closing.difference, closing.notes = counted_cash, difference, notes.strip()
    session.flush()
    return closing
