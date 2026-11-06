"""Job orders, inventory, applications, printer defaults."""
from datetime import date
from decimal import Decimal

import pytest

from application.services import (
    accounting_queries as aq, application_service, auth_service, customer_service, inventory_service, job_service,
    printer_service,
)
from application.use_cases.cancel_bill import cancel_bill
from application.use_cases.save_bill import BillRequest, LineRequest, save_bill
from business.billing import PaymentInput
from business.errors import AuthorizationError, StockError, ValidationError
from business.timeutil import ist_today
from database.connection import session_scope
from database.models import AuditLog, JobOrder, Payment, Product

D = Decimal
NOW = "2026-02-10T08:00:00"  # 13:30 IST on 2026-02-10


def at(iso):
    return lambda: iso


def cust(s, name="Ramu"):
    return customer_service.create_customer(s, name, "9848012345").id


def job(s, cid, total=50000, advance=20000, key="j1", method="cash", **kw):
    return job_service.create_job(s, cid, "100 wedding cards", "Printing", total, advance, method, key,
                                  clock=at(NOW), **kw)


# ---- jobs --------------------------------------------------------------------------------------

def test_new_job_with_advance(db):
    _, f = db
    with session_scope(f) as s:
        j = job(s, cust(s), expected_delivery="2026-02-15")
        assert (j.job_number, j.job_status, j.total_amount, j.advance_amount, j.balance_amount) == (
            "J2026-00001", "received", 50000, 20000, 30000)
        p = s.query(Payment).one()
        assert (p.job_id, p.bill_id, p.amount, p.kind, p.payment_date) == (j.id, None, 20000, "payment", "2026-02-10")
        hist = job_service.status_history(s, j.id)
        assert [(h.previous_status, h.new_status) for h in hist] == [(None, "received")]
        j2 = job(s, cust(s, "B"), key="j2", advance=0)
        assert j2.job_number == "J2026-00002" and s.query(Payment).count() == 1


def test_job_create_is_idempotent_and_validated(db):
    _, f = db
    with session_scope(f) as s:
        c = cust(s)
        a, b = job(s, c), job(s, c)
        assert a.id == b.id and s.query(JobOrder).count() == 1 and s.query(Payment).count() == 1
        for kw in (dict(total=1000, advance=2000, key="x1"), dict(total=-1, advance=0, key="x2")):
            with pytest.raises(ValidationError):
                job(s, c, **kw)
        with pytest.raises(ValidationError):
            job_service.create_job(s, c, "  ", "x", 100, 0, "cash", "k")
        with pytest.raises(ValidationError):
            job_service.create_job(s, 9999, "x", "x", 100, 0, "cash", "k2")
        with pytest.raises(ValidationError):
            job_service.create_job(s, c, "x", "x", 100, 0, "cash", "k3", expected_delivery="soon")


def test_collect_balance_then_deliver(db):
    _, f = db
    with session_scope(f) as s:
        j = job(s, cust(s))
        job_service.change_status(s, j.id, "in_progress", clock=at(NOW))
        job_service.change_status(s, j.id, "completed", clock=at(NOW))
        with pytest.raises(ValidationError) as e:
            job_service.change_status(s, j.id, "delivered")
        assert e.value.key == "jobs.balance_due"
        with pytest.raises(ValidationError):
            job_service.collect_payment(s, j.id, 30001, "cash", "p0")
        job_service.collect_payment(s, j.id, 10000, "upi", "p1")
        job_service.collect_payment(s, j.id, 10000, "upi", "p1")  # duplicate key: ignored
        assert (j.advance_amount, j.balance_amount) == (30000, 20000)
        job_service.collect_payment(s, j.id, 20000, "cash", "p2")
        job_service.change_status(s, j.id, "delivered", "handed over", clock=at(NOW))
        assert j.balance_amount == 0 and j.advance_amount == 50000
        assert [h.new_status for h in job_service.status_history(s, j.id)] == [
            "received", "in_progress", "completed", "delivered"]
        with pytest.raises(ValidationError) as e:
            job_service.change_status(s, j.id, "pending")
        assert e.value.key == "jobs.already_closed"
        with pytest.raises(ValidationError):
            job_service.collect_payment(s, j.id, 1, "cash", "p3")


def test_cancel_job_refunds_advance_and_is_audited(db):
    _, f = db
    with session_scope(f) as s:
        j = job(s, cust(s))
        job_service.collect_payment(s, j.id, 5000, "upi", "p1", clock=at(NOW))
        with pytest.raises(ValidationError):
            job_service.change_status(s, j.id, "cancelled", " ")
        job_service.change_status(s, j.id, "cancelled", "customer changed mind", clock=at(NOW))
        refunds = s.query(Payment).filter_by(kind="refund").order_by(Payment.id).all()
        assert [(r.amount, r.payment_method) for r in refunds] == [(20000, "cash"), (5000, "upi")]
        assert (j.job_status, j.advance_amount, j.balance_amount) == ("cancelled", 0, 0)
        assert s.query(AuditLog).filter_by(action="job_cancelled").one().reason == "customer changed mind"
        assert s.query(Payment).filter_by(kind="payment").count() == 2  # nothing deleted
        c = aq.collections(s, "2026-02-10", "2026-02-10")
        assert c.net_total == 0


def test_job_money_shows_in_collections_but_not_in_sales(db):
    _, f = db
    with session_scope(f) as s:
        job(s, cust(s))
        sm = aq.day_summary(s, "2026-02-10")
        assert sm.collections.net("cash") == 20000 and sm.sales == 0 and sm.bill_count == 0
        assert sm.pending_jobs == 1


def test_update_job_rules(db):
    _, f = db
    with session_scope(f) as s:
        j = job(s, cust(s))
        job_service.update_job(s, j.id, "cards + envelopes", "Printing", 60000, "2026-03-01", "n")
        assert (j.total_amount, j.balance_amount, j.expected_delivery) == (60000, 40000, "2026-03-01")
        with pytest.raises(ValidationError) as e:
            job_service.update_job(s, j.id, "x", "y", 10000, None, "")
        assert e.value.key == "jobs.total_below_advance"
        job_service.change_status(s, j.id, "cancelled", "x")
        with pytest.raises(ValidationError):
            job_service.update_job(s, j.id, "x", "y", 60000, None, "")


def test_job_search_and_filters(db):
    _, f = db
    with session_scope(f) as s:
        a, b = cust(s, "Anil"), cust(s, "Bhanu")
        j1 = job(s, a, key="a")
        j2 = job(s, b, key="b")
        job_service.change_status(s, j2.id, "in_progress", clock=at(NOW))
        assert [r.customer for r in job_service.list_jobs(s, "bhan")] == ["Bhanu"]
        assert [r.number for r in job_service.list_jobs(s, status="received")] == [j1.job_number]
        assert len(job_service.list_jobs(s, only_open=True)) == 2
        assert job_service.list_jobs(s, "J2026-00002")[0].phone == "9848012345"


# ---- inventory ---------------------------------------------------------------------------------

def make_product(s, name="Notebook", stock="0", minimum="5"):
    p = inventory_service.create_product(s, name, "Books", "item", 1800, 2500, D(minimum))
    if D(stock):
        inventory_service.purchase(s, p.id, D(stock), 1800)
    return p


def test_product_rules_and_purchase(db):
    _, f = db
    with session_scope(f) as s:
        p = make_product(s)
        assert p.stock_quantity == 0
        with pytest.raises(ValidationError):
            make_product(s)  # duplicate name
        for bad in (dict(name=" "), dict(purchase_price=-1)):
            args = dict(name="X", category="", unit="item", purchase_price=1, selling_price=1) | bad
            with pytest.raises(ValidationError):
                inventory_service.create_product(s, **args)
        inventory_service.purchase(s, p.id, D(10), 2000, "supplier A")
        assert (p.stock_quantity, p.purchase_price) == (10, 2000)  # latest cost becomes the purchase price
        with pytest.raises(ValidationError):
            inventory_service.purchase(s, p.id, D(0), 100)


def test_selling_two_from_ten_then_stock_purchase_and_return(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        p = make_product(s, stock="10")
        bill = save_bill(s, BillRequest("k", [LineRequest(D(2), "item", 2500, product_id=p.id)],
                                        payments=[PaymentInput(5000, "cash")]), at(NOW))
        assert p.stock_quantity == 8
        inventory_service.purchase(s, p.id, D(5), 1800)
        assert p.stock_quantity == 13
        inventory_service.customer_return(s, p.id, D(1), "wrong size")
        assert p.stock_quantity == 14
        cancel_bill(s, bill.bill_id, "x")  # puts the 2 back
        assert p.stock_quantity == 16
        assert inventory_service.ledger_total(s, p.id) == p.stock_quantity  # shelf == sum of movements


def test_adjustment_is_audited_and_negative_needs_permission(db):
    _, f = db
    with session_scope(f) as s:
        p = make_product(s, stock="3")
        inventory_service.adjust(s, p.id, D(-1), "found damaged")
        assert p.stock_quantity == 2 and s.query(AuditLog).filter_by(action="stock_adjusted").count() == 1
        with pytest.raises(ValidationError):
            inventory_service.adjust(s, p.id, D(1), " ")
        with pytest.raises(StockError) as e:
            inventory_service.adjust(s, p.id, D(-5), "recount")
        assert e.value.key == "inventory.negative_blocked" and p.stock_quantity == 2
        auth_service.set_pin(s, "1234")
        with pytest.raises(AuthorizationError):
            inventory_service.adjust(s, p.id, D(-5), "recount", allow_negative=True, pin="0000")
        assert p.stock_quantity == 2
        inventory_service.adjust(s, p.id, D(-5), "recount", allow_negative=True, pin="1234")
        assert p.stock_quantity == -3
        assert inventory_service.ledger_total(s, p.id) == -3


def test_low_stock_and_valuation_and_edit_keeps_stock(db):
    _, f = db
    with session_scope(f) as s:
        a = make_product(s, "A", stock="2", minimum="5")
        make_product(s, "B", stock="9", minimum="5")
        make_product(s, "C", stock="0", minimum="0")
        assert [r.name for r in inventory_service.list_stock(s, low_only=True)] == ["A", "C"]
        assert inventory_service.stock_value(s) == 2 * 1800 + 9 * 1800
        inventory_service.update_product(s, a.id, "A2", "x", "box", 1000, 1500, D(1), True)
        assert (a.stock_quantity, a.product_name, a.purchase_price) == (2, "A2", 1000)
        inventory_service.update_product(s, a.id, "A2", "x", "box", 1000, 1500, D(1), False)
        assert [r.name for r in inventory_service.list_stock(s)] == ["B", "C"]
        with pytest.raises(ValidationError):
            inventory_service.update_product(s, a.id, "B", "", "item", 1, 1, D(0))  # name taken


# ---- applications ------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["aadhaar 1234 5678 9012", "no 123456789012 given", "1234-5678-9012",
                                  "password: abc123", "OTP=482910", "pwd - hello"])
def test_secrets_in_notes_are_refused(db, text):
    _, f = db
    with session_scope(f) as s:
        c = cust(s)
        with pytest.raises(ValidationError) as e:
            application_service.save_application(s, c, "PAN Card", 10000, "2026-02-10", notes=text)
        assert e.value.key == "applications.sensitive"
        assert s.query(application_service.ApplicationRecord).count() == 0


@pytest.mark.parametrize("text", ["called 9848012345", "ref 2026-000001", "waiting for the OTP message", "pin code 522001"])
def test_normal_notes_are_accepted(db, text):
    _, f = db
    with session_scope(f) as s:
        application_service.save_application(s, cust(s), "PAN Card", 10000, "2026-02-10", notes=text)


def test_application_payment_status_comes_from_the_bill(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        c = cust(s)
        bill = save_bill(s, BillRequest("k", [LineRequest(D(50), "page", 200, service_id=ids["Xerox / Photocopy"])],
                                        customer_id=c, payments=[PaymentInput(4000, "cash")]), at(NOW))
        a = application_service.save_application(s, c, "PAN Card", 10000, "2026-02-10", "REF99", "ok",
                                                 "submitted", bill.bill_number)
        row = application_service.list_applications(s)[0]
        assert (row.payment_status, row.bill_number, row.status, row.reference) == ("partial", bill.bill_number, "submitted", "REF99")
        from application.use_cases.record_payment import record_customer_payment
        record_customer_payment(s, c, 6000, "cash", "p")
        assert application_service.list_applications(s)[0].payment_status == "paid"
        unbilled = application_service.save_application(s, c, "Passport", 0, "2026-02-11")
        assert [r.payment_status for r in application_service.list_applications(s)] == ["not_billed", "paid"]
        other = cust(s, "Other")
        with pytest.raises(ValidationError) as e:
            application_service.save_application(s, other, "PAN Card", 1, "2026-02-10", bill_number=bill.bill_number)
        assert e.value.key == "applications.bill_invalid"
        application_service.set_status(s, unbilled.id, "completed")
        assert [r.type for r in application_service.list_applications(s, status="completed")] == ["Passport"]
        assert [r.type for r in application_service.list_applications(s, text="REF99")] == ["PAN Card"]
        with pytest.raises(ValidationError):
            application_service.set_status(s, unbilled.id, "bogus")


# ---- printer defaults -----------------------------------------------------------------------------

def test_default_printer_is_remembered_per_purpose(db):
    _, f = db
    with session_scope(f) as s:
        printer_service.set_default(s, "receipt_a4", "Office Laser")
        printer_service.set_default(s, "documents", "Colour Inkjet", "A3")
        printer_service.set_default(s, "documents", "Office Laser")
        assert printer_service.get_default(s, "receipt_a4").printer_name == "Office Laser"
        d = printer_service.get_default(s, "documents")
        assert (d.printer_name, d.paper_size) == ("Office Laser", "A4")
        with pytest.raises(ValidationError):
            printer_service.set_default(s, "bogus", "x")
