"""Expenses. Edits are audited; removal is voiding with a reason. Nothing is deleted."""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from business.accounting import check_method
from business.errors import ValidationError
from business.timeutil import ist_today, utc_now_iso
from database.models import AuditLog, Expense

STOCK_CATEGORY = "Stationery purchases"  # stock bought for resale belongs in Inventory (see REQUIREMENTS A7)


def _validated(category: str, description: str, amount: int, method: str, expense_date: str, notes: str) -> dict:
    category = category.strip()
    if not category:
        raise ValidationError("validation.required", field_key="expense.category")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise ValidationError("expense.amount_positive")
    check_method(method)
    try:
        when = date.fromisoformat(expense_date)
    except ValueError:
        raise ValidationError("expense.date_invalid") from None
    if when > ist_today():
        raise ValidationError("expense.date_future")
    return dict(category=category, description=description.strip(), amount=amount, payment_method=method,
                expense_date=when.isoformat(), notes=notes.strip())


def add_expense(session: Session, category: str, description: str, amount: int, method: str, expense_date: str,
                notes: str = "") -> Expense:
    expense = Expense(**_validated(category, description, amount, method, expense_date, notes))
    session.add(expense)
    session.flush()
    return expense


def edit_expense(session: Session, expense_id: int, category: str, description: str, amount: int, method: str,
                 expense_date: str, notes: str = "", clock: Callable[[], str] = utc_now_iso) -> Expense:
    expense = session.get(Expense, expense_id)
    if expense is None or expense.is_voided:
        raise ValidationError("expense.not_editable")
    new = _validated(category, description, amount, method, expense_date, notes)
    before = {k: getattr(expense, k) for k in new}
    for k, v in new.items():
        setattr(expense, k, v)
    session.add(AuditLog(action="expense_edited", entity_type="expense", entity_id=expense.id, at=clock(),
                         reason="edited", details=json.dumps({"before": before, "after": new})))
    return expense


def void_expense(session: Session, expense_id: int, reason: str, clock: Callable[[], str] = utc_now_iso) -> None:
    reason = reason.strip()
    if not reason:
        raise ValidationError("validation.required", field_key="bill.cancel_reason")
    expense = session.get(Expense, expense_id)
    if expense is None or expense.is_voided:
        raise ValidationError("expense.not_editable")
    expense.is_voided, expense.void_reason = True, reason
    session.add(AuditLog(action="expense_voided", entity_type="expense", entity_id=expense.id, at=clock(),
                         reason=reason, details=json.dumps({"amount": expense.amount, "category": expense.category})))


def list_expenses(session: Session, date_from: date | None = None, date_to: date | None = None,
                  category: str | None = None) -> list[Expense]:
    query = select(Expense).order_by(Expense.expense_date.desc(), Expense.id.desc())
    if date_from:
        query = query.where(Expense.expense_date >= date_from.isoformat())
    if date_to:
        query = query.where(Expense.expense_date <= date_to.isoformat())
    if category:
        query = query.where(Expense.category == category)
    return list(session.scalars(query))


def totals_by_category(session: Session, date_from: date | None = None, date_to: date | None = None) -> dict[str, int]:
    """Voided expenses excluded."""
    query = select(Expense.category, func.sum(Expense.amount)).where(Expense.is_voided.is_(False)).group_by(Expense.category)
    if date_from:
        query = query.where(Expense.expense_date >= date_from.isoformat())
    if date_to:
        query = query.where(Expense.expense_date <= date_to.isoformat())
    return {c: t for c, t in session.execute(query)}
