import json
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from application.services import auth_service, bill_queries, catalog_service, customer_service
from application.use_cases.cancel_bill import cancel_bill
from application.use_cases.save_bill import BillRequest, LineRequest, save_bill
from business.billing import PaymentInput
from business.errors import AuthorizationError, StockError, ValidationError
from database.connection import session_scope
from database.models import (
    AppMetadata, AuditLog, Bill, BillItem, CustomerLedger, InventoryTransaction, Payment, Product,
)

D = Decimal
NOW = "2026-02-10T08:00:00"  # 13:30 IST


def at(iso):
    return lambda: iso


def xerox(ids, qty="25", copies=2, rate=200, **kw):
    return LineRequest(D(qty), "page", rate, copies, service_id=ids["Xerox / Photocopy"], **kw)


def req(key, lines, **kw):
    return BillRequest(idempotency_key=key, lines=lines, **kw)


def ledger_balance(s, customer_id):
    return s.scalar(select(func.coalesce(func.sum(CustomerLedger.debit - CustomerLedger.credit), 0))
                    .where(CustomerLedger.customer_id == customer_id))


def test_walk_in_cash_bill_end_to_end(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        saved = save_bill(s, req("k1", [xerox(ids)], payments=[PaymentInput(10000, "cash")]), at(NOW))
    assert saved.created and saved.bill_number == "2026-000001"
    with session_scope(factory) as s:
        b = s.get(Bill, saved.bill_id)
        assert (b.subtotal, b.grand_total, b.total_paid, b.outstanding_amount, b.status) == (10000,) * 2 + (10000, 0, "paid")
        assert b.bill_date == "2026-02-10"
        item = s.query(BillItem).one()
        assert (item.quantity, item.unit_rate, item.amount) == (D(50), 200, 10000)
        assert json.loads(item.service_details) == {"quantity": "25", "copies": 2}
        assert s.query(CustomerLedger).count() == 0  # walk-ins have no ledger


def test_lamination_10_copies(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        line = LineRequest(D(10), "item", 2000, service_id=ids["Lamination"])
        saved = save_bill(s, req("k", [line], payments=[PaymentInput(20000, "upi")]), at(NOW))
        assert s.get(Bill, saved.bill_id).grand_total == 20000


def test_multi_item_discount_and_split_payment(shop):
    factory, ids = shop
    lines = [xerox(ids), LineRequest(D(10), "item", 2000, service_id=ids["Lamination"])]
    with session_scope(factory) as s:
        cid = customer_service.create_customer(s, "Ramu").id
        saved = save_bill(s, req("k", lines, discount=1000, customer_id=cid,
                                 payments=[PaymentInput(14000, "cash"), PaymentInput(5000, "upi", "UTR123")]), at(NOW))
        b = s.get(Bill, saved.bill_id)
        assert (b.subtotal, b.discount, b.grand_total) == (30000, 1000, 29000)
        assert (b.total_paid, b.outstanding_amount, b.status) == (19000, 10000, "partial")
        assert s.query(Payment).filter_by(payment_method="upi").one().reference_number == "UTR123"
        assert ledger_balance(s, cid) == 10000


def test_credit_bill_needs_a_customer_and_writes_ledger(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        with pytest.raises(ValidationError) as e:
            save_bill(s, req("k0", [xerox(ids)], payments=[PaymentInput(6000, "cash")]), at(NOW))
        assert e.value.key == "bill.credit_needs_customer"
    with session_scope(factory) as s:
        cid = customer_service.create_customer(s, "Ramu", "9848012345").id
        saved = save_bill(s, req("k1", [xerox(ids)], customer_id=cid, payments=[PaymentInput(6000, "cash")]), at(NOW))
        b = s.get(Bill, saved.bill_id)
        assert (b.total_paid, b.outstanding_amount, b.status) == (6000, 4000, "partial")
        assert ledger_balance(s, cid) == 4000  # 100 billed - 60 paid


def test_failed_save_leaves_nothing_behind_including_bill_number(shop):
    factory, ids = shop
    with pytest.raises(ValidationError):
        with session_scope(factory) as s:
            save_bill(s, req("bad", [xerox(ids), xerox(ids, qty="0")]), at(NOW))
    with session_scope(factory) as s:
        assert s.query(Bill).count() == 0 and s.query(Payment).count() == 0
        assert s.query(AppMetadata).filter(AppMetadata.key.like("bill_counter%")).count() == 0


def test_rollback_when_a_late_step_fails(shop):
    """Insufficient stock is detected after other checks; no half-saved bill may remain."""
    factory, ids = shop
    with session_scope(factory) as s:
        s.add(Product(product_name="Pen", selling_price=1000, purchase_price=600, stock_quantity=D(1)))
    with session_scope(factory) as s:
        pid = s.query(Product).one().id
    with pytest.raises(StockError):
        with session_scope(factory) as s:
            save_bill(s, req("k", [xerox(ids), LineRequest(D(5), "item", 1000, product_id=pid)],
                             payments=[PaymentInput(10000 + 5000, "cash")]), at(NOW))
    with session_scope(factory) as s:
        assert s.query(Bill).count() == 0
        assert s.query(Product).one().stock_quantity == D(1)


def test_duplicate_submit_returns_same_bill(shop):
    factory, ids = shop
    for _ in range(2):
        with session_scope(factory) as s:
            saved = save_bill(s, req("same-key", [xerox(ids)], payments=[PaymentInput(10000, "cash")]), at(NOW))
    assert saved.created is False
    with session_scope(factory) as s:
        assert s.query(Bill).count() == 1 and s.query(Payment).count() == 1


def test_bill_numbers_sequential_per_year_and_prefixed(shop):
    factory, ids = shop
    from application.services import settings_service
    with session_scope(factory) as s:
        settings_service.update_shop_settings(s, bill_prefix="SX-")
    nums = []
    for i, when in enumerate(["2026-12-31T10:00:00", "2026-12-31T11:00:00", "2026-12-31T19:00:00"]):
        with session_scope(factory) as s:  # last one is 00:30 IST on 1 Jan 2027
            nums.append(save_bill(s, req(f"k{i}", [xerox(ids)], payments=[PaymentInput(10000, "cash")]),
                                  at(when)).bill_number)
    assert nums == ["SX-2026-000001", "SX-2026-000002", "SX-2027-000001"]


def test_historical_rate_is_kept_after_price_change(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        old = save_bill(s, req("old", [xerox(ids)], payments=[PaymentInput(10000, "cash")]), at("2026-02-01T10:00:00"))
        catalog_service.set_rate(s, ids["Xerox / Photocopy"], 300, at("2026-03-01T00:00:00"))
    with session_scope(factory) as s:
        # a bill made at the old rate after the change is refused as stale...
        with pytest.raises(ValidationError) as e:
            save_bill(s, req("stale", [xerox(ids, rate=200)]), at("2026-03-02T10:00:00"))
        assert e.value.key == "bill.rate_mismatch"
        new = save_bill(s, req("new", [xerox(ids, rate=300)], payments=[PaymentInput(15000, "cash")]),
                        at("2026-03-02T10:00:00"))
    with session_scope(factory) as s:
        assert bill_queries.get_bill_detail(s, old.bill_id).items[0].unit_rate == 200
        assert bill_queries.get_bill_detail(s, old.bill_id).summary.grand_total == 10000
        assert bill_queries.get_bill_detail(s, new.bill_id).items[0].unit_rate == 300
        assert catalog_service.current_rate(s, ids["Xerox / Photocopy"], "2026-02-15T00:00:00") == 200
        assert [r for _, r in catalog_service.rate_history(s, ids["Xerox / Photocopy"])] == [300, 200]


def test_rate_override_needs_flag_pin_and_is_audited(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        with pytest.raises(ValidationError):  # different rate without the override flag
            save_bill(s, req("a", [xerox(ids, rate=150)]), at(NOW))
        auth_service.set_pin(s, "1234")
    with session_scope(factory) as s:
        with pytest.raises(AuthorizationError) as e:
            save_bill(s, req("b", [xerox(ids, rate=150, rate_override=True)]), at(NOW))
        assert e.value.key == "auth.pin_required"
    with session_scope(factory) as s:
        with pytest.raises(AuthorizationError) as e:
            save_bill(s, req("c", [xerox(ids, rate=150, rate_override=True)], pin="0000"), at(NOW))
        assert e.value.key == "auth.pin_wrong"
    with session_scope(factory) as s:
        saved = save_bill(s, req("d", [xerox(ids, rate=150, rate_override=True)], pin="1234",
                                 payments=[PaymentInput(7500, "cash")]), at(NOW))
        audit = s.query(AuditLog).filter_by(action="rate_override").one()
        assert audit.entity_id == saved.bill_id
        assert json.loads(audit.details)["list_rate"] == 200 and json.loads(audit.details)["charged_rate"] == 150
        assert s.query(BillItem).one().unit_rate == 150  # historical rate = what was charged


def test_override_without_pin_set_still_audited(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        save_bill(s, req("a", [xerox(ids, rate=150, rate_override=True)], payments=[PaymentInput(7500, "cash")]), at(NOW))
        assert s.query(AuditLog).filter_by(action="rate_override").count() == 1


def test_service_without_rate_cannot_be_billed(db):
    _, factory = db
    with session_scope(factory) as s:
        from database.models import Service
        sid = s.query(Service).filter_by(service_name="Scanning").one().id
        with pytest.raises(ValidationError) as e:
            save_bill(s, req("k", [LineRequest(D(1), "page", 0, service_id=sid)]), at(NOW))
        assert e.value.key == "bill.no_rate"


def test_overpayment_and_invalid_inputs_rejected(shop):
    factory, ids = shop
    for kw, key in [(dict(payments=[PaymentInput(10001, "cash")]), "bill.overpayment"),
                    (dict(discount=10001), "bill.discount_invalid")]:
        with session_scope(factory) as s:
            with pytest.raises(ValidationError) as e:
                save_bill(s, req("k" + key, [xerox(ids)], **kw), at(NOW))
            assert e.value.key == key
    with session_scope(factory) as s:
        with pytest.raises(ValidationError) as e:  # both service and product
            save_bill(s, req("x", [LineRequest(D(1), "page", 200, service_id=ids["Xerox / Photocopy"], product_id=1)]), at(NOW))
        assert e.value.key == "bill.line_subject"


# --- stationery stock ------------------------------------------------------------------------

def _product(factory, stock="10"):
    with session_scope(factory) as s:
        p = Product(product_name="Notebook", selling_price=2500, purchase_price=1800, stock_quantity=D(stock))
        s.add(p)
        s.flush()
        return p.id


def test_selling_two_from_ten_leaves_eight_and_records_cost(shop):
    factory, _ = shop
    pid = _product(factory)
    with session_scope(factory) as s:
        save_bill(s, req("k", [LineRequest(D(2), "item", 2500, product_id=pid)], payments=[PaymentInput(5000, "cash")]), at(NOW))
    with session_scope(factory) as s:
        assert s.get(Product, pid).stock_quantity == D(8)
        tx = s.query(InventoryTransaction).one()
        assert (tx.transaction_type, tx.quantity, tx.unit_cost) == ("sale", D(-2), 1800)
        assert s.query(BillItem).one().unit_cost == 1800


def test_cannot_oversell_stock(shop):
    factory, _ = shop
    pid = _product(factory, "3")
    with session_scope(factory) as s:
        with pytest.raises(StockError) as e:
            save_bill(s, req("k", [LineRequest(D(2), "item", 2500, product_id=pid),
                                   LineRequest(D(2), "item", 2500, product_id=pid)]), at(NOW))
        assert e.value.key == "stock.insufficient"  # two lines of the same product are summed


# --- cancellation ----------------------------------------------------------------------------

def _credit_bill_with_stock(factory, ids):
    pid = _product(factory)
    with session_scope(factory) as s:
        cid = customer_service.create_customer(s, "Ramu").id
        saved = save_bill(s, req("k", [xerox(ids), LineRequest(D(2), "item", 2500, product_id=pid)], customer_id=cid,
                                 payments=[PaymentInput(4000, "cash"), PaymentInput(2000, "upi")]), at(NOW))
    return saved.bill_id, cid, pid


def test_cancel_refunds_reverses_ledger_and_stock_and_audits(shop):
    factory, ids = shop
    bill_id, cid, pid = _credit_bill_with_stock(factory, ids)
    with session_scope(factory) as s:
        assert ledger_balance(s, cid) == 15000 - 6000
        assert s.get(Product, pid).stock_quantity == D(8)
        assert cancel_bill(s, bill_id, "customer left", clock=at("2026-02-11T05:00:00")) == "refunded"
    with session_scope(factory) as s:
        b = s.get(Bill, bill_id)
        assert (b.status, b.total_paid, b.outstanding_amount, b.cancel_reason) == ("refunded", 0, 0, "customer left")
        assert ledger_balance(s, cid) == 0
        assert s.get(Product, pid).stock_quantity == D(10)
        refunds = s.query(Payment).filter_by(kind="refund").order_by(Payment.id).all()
        assert [(r.amount, r.payment_method) for r in refunds] == [(4000, "cash"), (2000, "upi")]
        assert s.query(Payment).filter_by(kind="payment").count() == 2  # nothing deleted
        assert s.query(BillItem).count() == 2
        a = s.query(AuditLog).filter_by(action="bill_cancelled").one()
        assert a.reason == "customer left" and json.loads(a.details)["refunded"] == 6000
        assert s.query(InventoryTransaction).filter_by(transaction_type="sale_reversal").one().quantity == D(2)


def test_cancel_unpaid_bill_is_cancelled_not_refunded(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        cid = customer_service.create_customer(s, "Ramu").id
        saved = save_bill(s, req("k", [xerox(ids)], customer_id=cid), at(NOW))
        assert cancel_bill(s, saved.bill_id, "mistake") == "cancelled"
        assert ledger_balance(s, cid) == 0


def test_cancel_requires_reason_pin_and_is_not_repeatable(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        saved = save_bill(s, req("k", [xerox(ids)], payments=[PaymentInput(10000, "cash")]), at(NOW))
        auth_service.set_pin(s, "4321")
    for reason, pin, key in [("  ", "4321", "validation.required"), ("x", None, "auth.pin_required"),
                             ("x", "1111", "auth.pin_wrong")]:
        with session_scope(factory) as s:
            with pytest.raises((ValidationError, AuthorizationError)) as e:
                cancel_bill(s, saved.bill_id, reason, pin)
            assert e.value.key == key
    with session_scope(factory) as s:
        cancel_bill(s, saved.bill_id, "ok", "4321")
    with session_scope(factory) as s:
        with pytest.raises(ValidationError) as e:
            cancel_bill(s, saved.bill_id, "again", "4321")
        assert e.value.key == "bill.already_cancelled"
        assert s.query(Payment).filter_by(kind="refund").count() == 1  # no double refund


# --- queries / PIN service ---------------------------------------------------------------------

def test_search_bills_by_number_customer_status_and_date(shop):
    factory, ids = shop
    with session_scope(factory) as s:
        cid = customer_service.create_customer(s, "Lakshmi", "9000011111").id
        save_bill(s, req("a", [xerox(ids)], payments=[PaymentInput(10000, "cash")]), at("2026-02-01T10:00:00"))
        save_bill(s, req("b", [xerox(ids)], customer_id=cid), at("2026-02-05T10:00:00"))
        from datetime import date
        assert len(bill_queries.search_bills(s)) == 2
        assert [r.customer_name for r in bill_queries.search_bills(s, "Laksh")] == ["Lakshmi"]
        assert [r.customer_name for r in bill_queries.search_bills(s, "9000011111")] == ["Lakshmi"]
        assert len(bill_queries.search_bills(s, "2026-000001")) == 1
        assert len(bill_queries.search_bills(s, status="unpaid")) == 1
        assert len(bill_queries.search_bills(s, date_from=date(2026, 2, 3))) == 1
        assert len(bill_queries.search_bills(s, date_to=date(2026, 2, 3))) == 1


def test_pin_set_change_remove(db):
    _, factory = db
    with session_scope(factory) as s:
        assert not auth_service.has_pin(s) and auth_service.verify_pin(s, None)
        with pytest.raises(ValidationError):
            auth_service.set_pin(s, "12")
        auth_service.set_pin(s, "1234")
        assert not auth_service.verify_pin(s, "9999") and auth_service.verify_pin(s, "1234")
    with session_scope(factory) as s:
        with pytest.raises(AuthorizationError):
            auth_service.set_pin(s, "5678", "0000")
        auth_service.set_pin(s, "5678", "1234")
        auth_service.clear_pin(s, "5678")
        assert not auth_service.has_pin(s)
