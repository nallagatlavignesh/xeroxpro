"""Aggregations behind the dashboard and reports. Each figure has one definition; see DATABASE_DESIGN §4.

All dates are IST business dates (YYYY-MM-DD strings).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from application.services import customer_service
from business import accounting
from business.billing import PAYMENT_METHODS
from database.models import Bill, BillItem, Expense, JobOrder, Payment, Product

LIVE = ~Bill.status.in_(("cancelled", "refunded"))
OPEN_JOB_STATUSES = ("received", "pending", "in_progress")


@dataclass(frozen=True)
class Collections:
    """Money that actually changed hands, by method. `net` = collected - refunded."""

    collected: dict[str, int]
    refunded: dict[str, int]

    def net(self, method: str) -> int:
        return self.collected[method] - self.refunded[method]

    @property
    def net_total(self) -> int:
        return sum(self.net(m) for m in PAYMENT_METHODS)


@dataclass(frozen=True)
class DaySummary:
    day: str
    sales: int  # billed today (grand_total of live bills), whether or not paid
    bill_count: int
    collections: Collections  # includes udhar recovered for older bills and job advances
    expenses: int
    cash_movement: int  # cash collected - cash refunded - cash expenses
    outstanding_credit: int  # all customers, as of now
    pending_jobs: int
    low_stock: int


def sales_total(session: Session, date_from: str, date_to: str) -> int:
    return session.scalar(select(func.coalesce(func.sum(Bill.grand_total), 0))
                          .where(LIVE, Bill.bill_date >= date_from, Bill.bill_date <= date_to))


def collections(session: Session, date_from: str, date_to: str) -> Collections:
    rows = session.execute(select(Payment.kind, Payment.payment_method, func.sum(Payment.amount))
                           .where(Payment.payment_date >= date_from, Payment.payment_date <= date_to)
                           .group_by(Payment.kind, Payment.payment_method))
    collected = {m: 0 for m in PAYMENT_METHODS}
    refunded = {m: 0 for m in PAYMENT_METHODS}
    for kind, method, total in rows:
        (collected if kind == "payment" else refunded)[method] = total
    return Collections(collected, refunded)


def expenses_total(session: Session, date_from: str, date_to: str, method: str | None = None) -> int:
    query = select(func.coalesce(func.sum(Expense.amount), 0)).where(
        Expense.is_voided.is_(False), Expense.expense_date >= date_from, Expense.expense_date <= date_to)
    if method:
        query = query.where(Expense.payment_method == method)
    return session.scalar(query)


def cash_movement(session: Session, day: str) -> int:
    c = collections(session, day, day)
    return accounting.cash_movement(c.collected["cash"], c.refunded["cash"], expenses_total(session, day, day, "cash"))


def day_summary(session: Session, day: str) -> DaySummary:
    count = session.scalar(select(func.count(Bill.id)).where(LIVE, Bill.bill_date == day))
    jobs = session.scalar(select(func.count(JobOrder.id)).where(JobOrder.job_status.in_(OPEN_JOB_STATUSES)))
    low = session.scalar(select(func.count(Product.id)).where(
        Product.is_active.is_(True), Product.stock_quantity <= Product.minimum_stock))
    return DaySummary(day, sales_total(session, day, day), count, collections(session, day, day),
                      expenses_total(session, day, day), cash_movement(session, day),
                      customer_service.total_outstanding(session), jobs, low)


def sales_by_day(session: Session, date_from: date, date_to: date) -> list[tuple[date, int]]:
    """One entry per calendar day in the range (zero-filled)."""
    rows = dict(session.execute(select(Bill.bill_date, func.sum(Bill.grand_total))
                                .where(LIVE, Bill.bill_date >= date_from.isoformat(), Bill.bill_date <= date_to.isoformat())
                                .group_by(Bill.bill_date)).all())
    days = (date_to - date_from).days + 1
    return [(d, rows.get(d.isoformat(), 0)) for d in (date_from + timedelta(i) for i in range(days))]


def cost_of_goods_sold(session: Session, date_from: str, date_to: str) -> int:
    """Purchase cost (captured at sale time) of stationery on live bills. Stock purchases themselves are NOT here."""
    rows = session.execute(select(BillItem.unit_cost, BillItem.quantity).join(Bill, BillItem.bill_id == Bill.id)
                           .where(LIVE, Bill.bill_date >= date_from, Bill.bill_date <= date_to,
                                  BillItem.unit_cost.isnot(None)))
    return sum(int((cost * qty).to_integral_value()) for cost, qty in rows)


def estimated_profit(session: Session, date_from: str, date_to: str) -> int:
    """sales - stationery cost sold - operating expenses. A 'Stationery purchases' expense is excluded because the
    same stock is already counted through cost of goods sold (REQUIREMENTS A5/A7)."""
    from application.services.expense_service import STOCK_CATEGORY

    operating = session.scalar(select(func.coalesce(func.sum(Expense.amount), 0)).where(
        Expense.is_voided.is_(False), Expense.category != STOCK_CATEGORY,
        Expense.expense_date >= date_from, Expense.expense_date <= date_to))
    return accounting.estimated_profit(sales_total(session, date_from, date_to),
                                       cost_of_goods_sold(session, date_from, date_to), operating)


@dataclass(frozen=True)
class RecentItem:
    at: str  # UTC iso
    kind: str  # bill | payment | refund | expense
    text: str
    amount: int


def recent_transactions(session: Session, limit: int = 12) -> list[RecentItem]:
    items: list[RecentItem] = []
    for b in session.scalars(select(Bill).order_by(Bill.id.desc()).limit(limit)):
        items.append(RecentItem(b.created_at, "bill", b.bill_number, b.grand_total))
    for p, number in session.execute(select(Payment, Bill.bill_number).join(Bill, Payment.bill_id == Bill.id, isouter=True)
                                     .order_by(Payment.id.desc()).limit(limit)):
        items.append(RecentItem(p.created_at, p.kind, f"{number or 'job'} · {p.payment_method}", p.amount))
    for e in session.scalars(select(Expense).where(Expense.is_voided.is_(False)).order_by(Expense.id.desc()).limit(limit)):
        items.append(RecentItem(e.created_at, "expense", f"{e.category} · {e.payment_method}", e.amount))
    return sorted(items, key=lambda i: i.at, reverse=True)[:limit]
