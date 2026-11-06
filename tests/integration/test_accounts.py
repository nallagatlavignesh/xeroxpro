from datetime import date
from decimal import Decimal

import pytest

from application.services import accounting_queries as aq
from application.services import customer_service, expense_service
from application.use_cases.cancel_bill import cancel_bill
from application.use_cases.close_day import close_day, preview
from application.use_cases.record_payment import preview_allocation, record_customer_payment
from application.use_cases.save_bill import BillRequest, LineRequest, save_bill
from business.accounting import allocate_payment
from business.billing import PaymentInput
from business.errors import ValidationError
from database.connection import session_scope
from database.models import (
    AuditLog, Bill, BillItem, DailyClosing, InventoryTransaction, JobOrder, Payment, Product,
)

D = Decimal
DAY = "2026-02-10"
NOW = "2026-02-10T08:00:00"  # 13:30 IST on DAY


def at(iso):
    return lambda: iso


def bill(s, ids, key, pages, customer_id=None, paid=0, method="cash", when=NOW, product=None):
    """pages x Rs2 xerox bill (so 50 pages = Rs100)."""
    lines = [LineRequest(D(pages), "page", 200, service_id=ids["Xerox / Photocopy"])]
    if product:
        lines.append(product)
    pay = [PaymentInput(paid, method)] if paid else []
    return save_bill(s, BillRequest(key, lines, payments=pay, customer_id=customer_id), at(when))


def customer(s, name="Ramu"):
    return customer_service.create_customer(s, name, "9848012345").id


# ---- pure allocation ----------------------------------------------------------------------

def test_allocate_oldest_first_and_exact_amounts():
    assert allocate_payment(150, [(1, 100), (2, 100)]) == [(1, 100), (2, 50)]
    assert allocate_payment(40, [(1, 100), (2, 100)]) == [(1, 40)]
    assert allocate_payment(200, [(1, 100), (2, 100)]) == [(1, 100), (2, 100)]


@pytest.mark.parametrize("amount", [0, -5, 201])
def test_allocate_rejects_bad_amounts(amount):
    with pytest.raises(ValidationError):
        allocate_payment(amount, [(1, 100), (2, 100)])


# ---- customer credit (prompt §12) -------------------------------------------------------

def test_100_bill_60_paid_leaves_40_then_40_clears_it(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        cid = customer(s)
        b = bill(s, ids, "b1", 50, cid, paid=6000)
        assert customer_service.balance_of(s, cid) == 4000
        assert s.get(Bill, b.bill_id).outstanding_amount == 4000
        result = record_customer_payment(s, cid, 4000, "upi", "p1", "UTR9", clock=at("2026-02-11T08:00:00"))
        assert result.created and result.allocations == [(b.bill_id, 4000)]
        bl = s.get(Bill, b.bill_id)
        assert (bl.total_paid, bl.outstanding_amount, bl.status) == (10000, 0, "paid")
        assert customer_service.balance_of(s, cid) == 0
        assert s.query(Payment).filter_by(bill_id=b.bill_id).count() == 2


def test_partial_payment_updates_ledger_and_history_is_accurate(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        cid = customer(s)
        bill(s, ids, "b1", 50, cid, paid=3000)
        record_customer_payment(s, cid, 1000, "cash", "p1", clock=at("2026-02-11T08:00:00"))
        rows = customer_service.ledger(s, cid)
        assert [(r.type, r.debit, r.credit, r.balance) for r in rows] == [
            ("bill", 10000, 0, 10000), ("payment", 0, 3000, 7000), ("payment", 0, 1000, 6000)]
        assert rows[-1].date == "2026-02-11"
        assert [r.detail for r in rows] == ["2026-000001|", "2026-000001|cash", "2026-000001|cash"]
        hist = customer_service.payment_history(s, cid)
        assert [(h[2], h[3], h[4]) for h in hist] == [("cash", 1000, "payment"), ("cash", 3000, "payment")]
        assert s.query(Bill).one().status == "partial"


def test_duplicate_payment_is_ignored(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        cid = customer(s)
        bill(s, ids, "b1", 50, cid)
        first = record_customer_payment(s, cid, 4000, "cash", "same")
        again = record_customer_payment(s, cid, 4000, "cash", "same")
        assert first.created and not again.created and again.allocations == first.allocations
        assert customer_service.balance_of(s, cid) == 6000
        assert s.query(Payment).count() == 1


def test_overpayment_and_nothing_due_rejected(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        cid = customer(s)
        bill(s, ids, "b1", 50, cid, paid=10000)  # fully paid
        with pytest.raises(ValidationError) as e:
            record_customer_payment(s, cid, 100, "cash", "x")
        assert e.value.key == "payment.exceeds_outstanding"
        bill(s, ids, "b2", 50, cid)
        with pytest.raises(ValidationError):
            record_customer_payment(s, cid, 10001, "cash", "y")
        with pytest.raises(ValidationError):
            record_customer_payment(s, cid, 100, "cheque", "z")
        assert customer_service.balance_of(s, cid) == 10000


def test_payment_spreads_over_oldest_bills_or_a_chosen_bill(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        cid = customer(s)
        b1 = bill(s, ids, "b1", 50, cid, when="2026-02-01T08:00:00")
        b2 = bill(s, ids, "b2", 50, cid, when="2026-02-02T08:00:00")
        assert preview_allocation(s, cid, 15000) == [(b1.bill_number, 10000), (b2.bill_number, 5000)]
        record_customer_payment(s, cid, 15000, "cash", "p1")
        assert (s.get(Bill, b1.bill_id).status, s.get(Bill, b2.bill_id).status) == ("paid", "partial")
        record_customer_payment(s, cid, 1000, "cash", "p2", bill_id=b2.bill_id)
        assert s.get(Bill, b2.bill_id).outstanding_amount == 4000
        with pytest.raises(ValidationError) as e:
            record_customer_payment(s, cid, 100, "cash", "p3", bill_id=b1.bill_id)  # already paid
        assert e.value.key == "payment.nothing_due"
        assert customer_service.balance_of(s, cid) == 4000


def test_balances_list_report_and_search(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        a, b = customer(s, "Anil"), customer(s, "Bhanu")
        customer(s, "Chitra")
        bill(s, ids, "b1", 50, a)
        bill(s, ids, "b2", 100, b, paid=5000)
        owing = customer_service.list_with_balances(s, only_owing=True)
        assert [(c.name, c.balance) for c in owing] == [("Bhanu", 15000), ("Anil", 10000)]
        assert len(customer_service.list_with_balances(s)) == 3
        assert [c.name for c in customer_service.list_with_balances(s, "chit")] == ["Chitra"]
        assert customer_service.total_outstanding(s) == 25000


def test_customer_edit_and_validation(db):
    _, factory = db
    with session_scope(factory) as s:
        c = customer_service.create_customer(s, "Ramu", "9848012345", "Guntur", "regular")
        customer_service.update_customer(s, c.id, "Ramu Naidu", "9848012346", "", "")
        assert (c.customer_name, c.address, c.notes) == ("Ramu Naidu", None, "")
        with pytest.raises(ValidationError):
            customer_service.update_customer(s, c.id, " ")


# ---- sales / collections / credit / expenses are different numbers ---------------------------

def test_sales_collections_and_credit_are_kept_apart(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        cid = customer(s)
        bill(s, ids, "credit", 50, cid)  # Rs100 sale, nothing collected
        bill(s, ids, "cash", 25, paid=5000)  # Rs50 sale, collected in cash
        bill(s, ids, "upi", 25, paid=5000, method="upi")
        bill(s, ids, "upi2", 25, cid, paid=2000, method="upi")
        sm = aq.day_summary(s, DAY)
        assert sm.sales == 10000 + 5000 + 5000 + 5000
        assert sm.bill_count == 4
        assert (sm.collections.net("cash"), sm.collections.net("upi"), sm.collections.net("other")) == (5000, 7000, 0)
        assert sm.collections.net_total == 12000  # Rs250 sold, but the Rs130 left on credit is NOT money received
        assert sm.outstanding_credit == 10000 + 3000


def test_collections_use_the_payment_date_not_the_bill_date(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        cid = customer(s)
        bill(s, ids, "old", 50, cid, when="2026-02-01T08:00:00")
        record_customer_payment(s, cid, 4000, "cash", "p", clock=at("2026-02-10T08:00:00"))
        today, first = aq.day_summary(s, DAY), aq.day_summary(s, "2026-02-01")
        assert (today.sales, today.collections.net("cash")) == (0, 4000)  # udhar recovery, no new sale
        assert (first.sales, first.collections.net_total) == (10000, 0)


def test_expense_totals_per_day_and_method(shop):
    factory, _ = shop
    with session_scope(factory) as s:
        expense_service.add_expense(s, "Paper", "A4 ream", 45000, "cash", DAY)
        expense_service.add_expense(s, "Electricity", "bill", 120000, "upi", DAY)
        expense_service.add_expense(s, "Rent", "", 500000, "cash", "2026-02-09")
        gone = expense_service.add_expense(s, "Other", "typo", 999, "cash", DAY)
        expense_service.void_expense(s, gone.id, "entered twice")
        assert aq.expenses_total(s, DAY, DAY) == 165000
        assert aq.expenses_total(s, DAY, DAY, "cash") == 45000
        assert aq.expenses_total(s, "2026-02-01", "2026-02-28") == 665000
        assert expense_service.totals_by_category(s, date(2026, 2, 10), date(2026, 2, 10)) == {
            "Paper": 45000, "Electricity": 120000}
        assert s.query(AuditLog).filter_by(action="expense_voided").one().reason == "entered twice"
        assert len(expense_service.list_expenses(s, date(2026, 2, 10), date(2026, 2, 10))) == 3  # voided still listed


def test_expense_validation_edit_and_audit(db):
    _, factory = db
    with session_scope(factory) as s:
        for kw in [dict(amount=0), dict(amount=-5), dict(category=" "), dict(method="cheque"),
                   dict(expense_date="not-a-date"), dict(expense_date="2999-01-01")]:
            args = dict(category="Paper", description="x", amount=100, method="cash", expense_date=DAY)
            args.update({"category" if k == "category" else k: v for k, v in kw.items()})
            with pytest.raises(ValidationError):
                expense_service.add_expense(s, args["category"], args["description"], args["amount"],
                                            args["method"], args["expense_date"])
        e = expense_service.add_expense(s, "Paper", "x", 100, "cash", DAY)
        expense_service.edit_expense(s, e.id, "Toner and ink", "y", 250, "upi", DAY, "n")
        assert (e.category, e.amount, e.payment_method) == ("Toner and ink", 250, "upi")
        assert s.query(AuditLog).filter_by(action="expense_edited").count() == 1
        expense_service.void_expense(s, e.id, "wrong")
        with pytest.raises(ValidationError):
            expense_service.edit_expense(s, e.id, "Paper", "x", 100, "cash", DAY)


# ---- cash movement, closing -------------------------------------------------------------------

def test_cash_movement_is_not_sales_minus_expenses(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        cid = customer(s)
        bill(s, ids, "a", 50, cid)  # Rs100 sale on credit
        bill(s, ids, "b", 50, paid=10000)  # Rs100 cash
        bill(s, ids, "c", 50, paid=10000, method="upi")
        bill(s, ids, "d", 25, paid=5000)  # Rs50 cash, cancelled below
        expense_service.add_expense(s, "Paper", "", 3000, "cash", DAY)
        expense_service.add_expense(s, "Rent", "", 2000, "upi", DAY)
        cancel_bill(s, s.query(Bill).filter_by(idempotency_key="d").one().id, "oops", clock=at(NOW))
        sm = aq.day_summary(s, DAY)
        assert sm.sales == 10000 + 10000 + 10000  # cancelled bill is not a sale
        assert sm.cash_movement == 10000 + 5000 - 5000 - 3000 == 7000  # cash in - cash refund - cash expense
        assert sm.sales - sm.expenses != sm.cash_movement


def test_daily_closing_uses_previous_count_and_records_difference(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        bill(s, ids, "a", 50, paid=10000, when="2026-02-09T08:00:00")
        c1 = close_day(s, "2026-02-09", counted_cash=10000, opening_cash=0, clock=at("2026-02-09T15:00:00"))
        assert (c1.expected_cash, c1.difference) == (10000, 0)
        bill(s, ids, "b", 25, paid=5000)
        expense_service.add_expense(s, "Paper", "", 1000, "cash", DAY)
        p = preview(s, DAY)
        assert (p.opening_cash, p.cash_movement, p.expected_cash) == (10000, 4000, 14000)
        c2 = close_day(s, DAY, counted_cash=13800, opening_cash=p.opening_cash, notes="short", clock=at(NOW))
        assert c2.difference == -200
        close_day(s, DAY, counted_cash=14000, opening_cash=10000, clock=at(NOW))  # correction
        assert s.query(DailyClosing).count() == 2 and s.query(DailyClosing).filter_by(closing_date=DAY).one().difference == 0
        assert s.query(AuditLog).filter_by(action="closing_corrected").count() == 1
        with pytest.raises(ValidationError):
            close_day(s, DAY, counted_cash=-1, opening_cash=0)


# ---- profit estimate / inventory ----------------------------------------------------------------

def test_inventory_purchase_is_not_double_counted_in_profit(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        p = Product(product_name="Pen", selling_price=1000, purchase_price=600, stock_quantity=D(10))
        s.add(p)
        s.flush()
        # stock bought earlier for Rs60 x 10 = Rs600 sits in inventory_transactions, not in expenses
        s.add(InventoryTransaction(product_id=p.id, transaction_type="purchase", quantity=D(10), unit_cost=600,
                                   transaction_date="2026-02-01"))
        save_bill(s, BillRequest("k", [LineRequest(D(4), "item", 1000, product_id=p.id)],
                                 payments=[PaymentInput(4000, "cash")]), at(NOW))
        expense_service.add_expense(s, "Electricity", "", 500, "cash", DAY)
        expense_service.add_expense(s, "Stationery purchases", "pens", 600, "cash", DAY)  # would double count
        assert aq.cost_of_goods_sold(s, DAY, DAY) == 4 * 600
        assert aq.estimated_profit(s, DAY, DAY) == 4000 - 2400 - 500
        assert aq.expenses_total(s, DAY, DAY) == 1100  # it is still a recorded expense, just not in the profit sum


def test_dashboard_counts_pending_jobs_and_low_stock(shop):
    factory, _ = shop
    with session_scope(factory) as s:
        cid = customer(s)
        for n, status in enumerate(["received", "pending", "in_progress", "completed", "delivered", "cancelled"]):
            s.add(JobOrder(job_number=f"J{n}", customer_id=cid, job_description="x", job_status=status))
        s.add(Product(product_name="A", stock_quantity=D(2), minimum_stock=D(5)))
        s.add(Product(product_name="B", stock_quantity=D(5), minimum_stock=D(5)))
        s.add(Product(product_name="C", stock_quantity=D(9), minimum_stock=D(5)))
        s.add(Product(product_name="D", stock_quantity=D(0), minimum_stock=D(5), is_active=False))
        sm = aq.day_summary(s, DAY)
        assert (sm.pending_jobs, sm.low_stock) == (3, 2)


def test_sales_by_day_is_zero_filled_and_skips_cancelled(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        bill(s, ids, "a", 50, paid=10000, when="2026-02-08T08:00:00")
        gone = bill(s, ids, "b", 50, paid=10000, when="2026-02-09T08:00:00")
        cancel_bill(s, gone.bill_id, "x")
        series = aq.sales_by_day(s, date(2026, 2, 7), date(2026, 2, 10))
        assert series == [(date(2026, 2, 7), 0), (date(2026, 2, 8), 10000), (date(2026, 2, 9), 0), (date(2026, 2, 10), 0)]


def test_recent_transactions_mixes_kinds_newest_first(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        bill(s, ids, "a", 50, paid=10000)
        expense_service.add_expense(s, "Paper", "", 1000, "cash", DAY)
        kinds = [i.kind for i in aq.recent_transactions(s)]
        assert set(kinds) == {"bill", "payment", "expense"}
