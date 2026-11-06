"""Report queries. Every figure comes from the same definitions the dashboard uses (accounting_queries)."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from application.services import accounting_queries as aq
from application.services import customer_service, inventory_service, job_service
from business.billing import PAYMENT_METHODS
from business.errors import ValidationError
from business.report_model import Column, Report, SummaryLine, dmy
from business.timeutil import ist_today, to_ist
from database.models import Bill, BillItem, Customer, Expense, JobOrder, Payment

M, I, Q, K = "money", "int", "qty", "key"  # K: the cell holds a translation key


def _span(date_from: date, date_to: date) -> tuple[str, str]:
    if date_to < date_from:
        raise ValidationError("report.range_invalid")
    return date_from.isoformat(), date_to.isoformat()


def sales_report(session: Session, date_from: date, date_to: date) -> Report:
    """One row per day. Daily, weekly, monthly and custom reports are this report over different ranges."""
    start, end = _span(date_from, date_to)
    rows, totals = [], [0] * 8
    day = date_from
    while day <= date_to:
        iso = day.isoformat()
        sm = aq.day_summary(session, iso)
        c = sm.collections
        figures = [sm.bill_count, sm.sales, c.collected["cash"], c.collected["upi"], c.collected["other"],
                   sum(c.refunded.values()), sm.expenses, sm.cash_movement]
        rows.append([dmy(iso), *figures])
        totals = [a + b for a, b in zip(totals, figures)]
        day += timedelta(days=1)
    coll = aq.collections(session, start, end)
    summary = [
        SummaryLine("report.s_sales", totals[1], emphasis=True),
        SummaryLine("report.s_received", coll.net_total, emphasis=True),
        SummaryLine("pay.cash", coll.net("cash")), SummaryLine("pay.upi", coll.net("upi")),
        SummaryLine("pay.other", coll.net("other")),
        SummaryLine("report.s_refunds", totals[5]),
        SummaryLine("report.s_expenses", totals[6]),
        SummaryLine("report.s_cash_movement", totals[7]),
        SummaryLine("report.s_profit", aq.estimated_profit(session, start, end)),
        SummaryLine("report.s_credit_now", customer_service.total_outstanding(session)),
    ]
    return Report(
        "sales", "report.sales",
        [Column("report.c_date"), Column("report.c_bills", I), Column("report.c_sales", M), Column("pay.cash", M),
         Column("pay.upi", M), Column("pay.other", M), Column("report.c_refunds", M), Column("report.c_expenses", M),
         Column("report.c_cash_movement", M)],
        rows, ["", *totals], summary, ["report.note_sales", "report.note_profit"], (start, end))


def service_sales_report(session: Session, date_from: date, date_to: date) -> Report:
    start, end = _span(date_from, date_to)
    live = ~Bill.status.in_(("cancelled", "refunded"))
    query = (select(BillItem.description, func.sum(BillItem.quantity), func.count(func.distinct(BillItem.bill_id)),
                    func.sum(BillItem.amount))
             .join(Bill, BillItem.bill_id == Bill.id)
             .where(live, Bill.bill_date >= start, Bill.bill_date <= end)
             .group_by(BillItem.description).order_by(func.sum(BillItem.amount).desc()))
    rows = [[d, q, n, a] for d, q, n, a in session.execute(query)]
    items_total = sum(r[3] for r in rows)
    discounts = session.scalar(select(func.coalesce(func.sum(Bill.discount), 0))
                               .where(live, Bill.bill_date >= start, Bill.bill_date <= end))
    return Report(
        "service_sales", "report.service_sales",
        [Column("report.c_item"), Column("report.c_qty", Q), Column("report.c_bills", I), Column("report.c_amount", M)],
        rows, ["", None, None, items_total],
        [SummaryLine("report.s_items", items_total), SummaryLine("report.s_discounts", -discounts),
         SummaryLine("report.s_sales", items_total - discounts, emphasis=True)],
        ["report.note_service"], (start, end))


def collections_report(session: Session, date_from: date, date_to: date, method: str) -> Report:
    if method not in PAYMENT_METHODS:
        raise ValidationError("bill.payment_method_invalid")
    start, end = _span(date_from, date_to)
    rows, collected, refunded = [], 0, 0
    query = (select(Payment).where(Payment.payment_method == method, Payment.payment_date >= start,
                                   Payment.payment_date <= end).order_by(Payment.payment_date, Payment.id))
    for p in session.scalars(query):
        bill = session.get(Bill, p.bill_id) if p.bill_id else None
        job = session.get(JobOrder, p.job_id) if p.job_id else None
        customer_id = bill.customer_id if bill else job.customer_id if job else None
        customer = session.get(Customer, customer_id) if customer_id else None
        signed = p.amount if p.kind == "payment" else -p.amount
        collected += p.amount if p.kind == "payment" else 0
        refunded += p.amount if p.kind == "refund" else 0
        rows.append([dmy(p.payment_date), bill.bill_number if bill else job.job_number,
                     customer.customer_name if customer else "", "report.k_" + p.kind, signed, p.reference_number or ""])
    summary = [SummaryLine("report.s_collected", collected), SummaryLine("report.s_refunds", refunded),
               SummaryLine("report.s_net", collected - refunded, emphasis=True)]
    notes = ["report.note_collections"]
    if method == "cash":
        spent = aq.expenses_total(session, start, end, "cash")
        summary += [SummaryLine("report.s_cash_expenses", spent),
                    SummaryLine("report.s_cash_movement", collected - refunded - spent, emphasis=True)]
        notes.append("report.note_cash")
    return Report(
        f"collections_{method}", f"report.collections_{method}",
        [Column("report.c_date"), Column("report.c_number"), Column("report.c_customer"), Column("report.c_kind", K),
         Column("report.c_amount", M), Column("report.c_reference")],
        rows, ["", "", "", "", collected - refunded, ""], summary, notes, (start, end))


def outstanding_report(session: Session) -> Report:
    """Who owes what right now (as of today), biggest balance first."""
    live_open = (Bill.outstanding_amount > 0) & Bill.status.in_(("unpaid", "partial"))
    open_bills = {cid: (n, oldest) for cid, n, oldest in session.execute(
        select(Bill.customer_id, func.count(Bill.id), func.min(Bill.bill_date)).where(live_open)
        .group_by(Bill.customer_id))}
    rows = []
    for c in customer_service.list_with_balances(session, only_owing=True):
        n, oldest = open_bills.get(c.id, (0, None))
        rows.append([c.name, c.phone, n, dmy(oldest) if oldest else "", c.balance])
    total = sum(r[4] for r in rows)
    return Report(
        "outstanding", "report.outstanding",
        [Column("report.c_customer"), Column("report.c_phone"), Column("report.c_open_bills", I),
         Column("report.c_oldest"), Column("report.c_balance", M)],
        rows, ["", "", None, "", total],
        [SummaryLine("report.s_credit_now", total, emphasis=True),
         SummaryLine("report.s_customers_owing", len(rows), "int")],
        ["report.note_outstanding"], (ist_today().isoformat(), ist_today().isoformat()))


def expense_report(session: Session, date_from: date, date_to: date) -> Report:
    start, end = _span(date_from, date_to)
    query = (select(Expense).where(Expense.is_voided.is_(False), Expense.expense_date >= start,
                                   Expense.expense_date <= end).order_by(Expense.expense_date, Expense.id))
    expenses = list(session.scalars(query))
    rows = [[dmy(e.expense_date), e.category, e.description, "pay." + e.payment_method, e.amount] for e in expenses]
    by_category: dict[str, int] = {}
    for e in expenses:
        by_category[e.category] = by_category.get(e.category, 0) + e.amount
    total = sum(by_category.values())
    summary = [SummaryLine("report.s_expenses", total, emphasis=True)]
    summary += [SummaryLine(cat, amount, translate=False) for cat, amount in sorted(by_category.items())]
    return Report(
        "expenses", "report.expenses",
        [Column("report.c_date"), Column("report.c_category"), Column("report.c_description"), Column("report.c_method", K),
         Column("report.c_amount", M)],
        rows, ["", "", "", "", total], summary, ["report.note_expenses"], (start, end))


def inventory_report(session: Session) -> Report:
    stock = inventory_service.list_stock(session)
    rows = [[r.name, r.category, r.stock, r.minimum, r.purchase_price, r.selling_price, r.value,
             "report.k_low" if r.low else ""] for r in stock]
    value = sum(r.value for r in stock)
    return Report(
        "inventory", "report.inventory",
        [Column("report.c_product"), Column("report.c_category"), Column("report.c_stock", Q),
         Column("report.c_minimum", Q), Column("report.c_purchase_price", M), Column("report.c_selling_price", M),
         Column("report.c_value", M), Column("report.c_status", K)],
        rows, ["", "", None, None, None, None, value, ""],
        [SummaryLine("report.s_stock_value", value, emphasis=True),
         SummaryLine("report.s_low_items", sum(1 for r in stock if r.low), "int")],
        ["report.note_inventory"], (ist_today().isoformat(), ist_today().isoformat()))


def job_status_report(session: Session, date_from: date, date_to: date) -> Report:
    """Jobs received in the period, with where each one stands."""
    start, end = _span(date_from, date_to)
    today = ist_today().isoformat()
    created = {j.id: to_ist(j.created_at).date().isoformat()
               for j in session.scalars(select(JobOrder))}
    jobs = [j for j in job_service.list_jobs(session) if start <= created[j.id] <= end]
    jobs.reverse()  # oldest first
    counts = {s: 0 for s in job_service.STATUSES}
    overdue = 0
    rows = []
    for j in jobs:
        counts[j.status] += 1
        if j.status in job_service.OPEN and j.expected_delivery and j.expected_delivery < today:
            overdue += 1
        rows.append([j.number, j.customer, j.phone, j.description, j.total, j.advance, j.balance,
                     dmy(j.expected_delivery) if j.expected_delivery else "", "jobs.status_" + j.status])
    summary = [SummaryLine(f"jobs.status_{s}", n, "int") for s, n in counts.items()]
    summary.append(SummaryLine("report.s_overdue", overdue, "int"))
    return Report(
        "jobs", "report.jobs",
        [Column("jobs.number"), Column("report.c_customer"), Column("report.c_phone"), Column("report.c_description"),
         Column("report.c_total", M), Column("jobs.col_advance", M), Column("report.c_balance", M),
         Column("jobs.col_delivery"), Column("report.c_status", K)],
        rows, ["", "", "", "", sum(j.total for j in jobs), sum(j.advance for j in jobs), sum(j.balance for j in jobs), "", ""],
        summary, ["report.note_jobs"], (start, end))
