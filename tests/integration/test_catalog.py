from decimal import Decimal

import pytest
from sqlalchemy import func, select

from application.services import catalog_service, customer_service, settings_service
from application.use_cases.cancel_bill import cancel_bill
from application.use_cases.save_bill import BillRequest, LineRequest, save_bill
from business.billing import PaymentInput
from business.errors import ValidationError
from database.connection import session_scope
from database.models import Bill, CustomerLedger, LookupValue


def test_set_rate_validation_and_same_second_overwrite(db):
    _, factory = db
    with session_scope(factory) as s:
        sid = catalog_service.list_services(s)[0].id
        for bad in (-1, 2.5, True):
            with pytest.raises(ValidationError):
                catalog_service.set_rate(s, sid, bad)
        with pytest.raises(ValidationError):
            catalog_service.set_rate(s, 9999, 100)
        catalog_service.set_rate(s, sid, 100, lambda: "2026-01-01T00:00:00")
        catalog_service.set_rate(s, sid, 150, lambda: "2026-01-01T00:00:00")
        assert catalog_service.rate_history(s, sid) == [("2026-01-01T00:00:00", 150)]
        assert catalog_service.current_rate(s, sid, "2025-12-31T00:00:00") is None  # not yet effective


def test_save_service_rules_and_new_unit_is_remembered(db):
    _, factory = db
    with session_scope(factory) as s:
        with pytest.raises(ValidationError):
            catalog_service.save_service(s, "  ", "page")
        with pytest.raises(ValidationError):
            catalog_service.save_service(s, "Scanning", "page")  # duplicate of seeded service
        svc = catalog_service.save_service(s, "Passport Photo", "set", "Photos")
        catalog_service.save_service(s, "Passport Photo", "strip", is_active=False, service_id=svc.id)
        assert "strip" in catalog_service.list_units(s)
        assert [r for r in catalog_service.list_services(s, active_only=True) if r.name == "Passport Photo"] == []


def test_customer_validation(db):
    _, factory = db
    with session_scope(factory) as s:
        with pytest.raises(ValidationError):
            customer_service.create_customer(s, "")
        with pytest.raises(ValidationError):
            customer_service.create_customer(s, "A", "12")
        assert customer_service.create_customer(s, "A", "98480 12345").id


def test_bad_bill_prefix_rejected(db):
    _, factory = db
    with session_scope(factory) as s:
        with pytest.raises(ValidationError):
            settings_service.update_shop_settings(s, bill_prefix="bad prefix!")
        with pytest.raises(ValidationError):
            settings_service.update_shop_settings(s, default_payment_method="cheque")


def test_ledger_always_matches_outstanding_of_live_bills(shop):
    """Ledger balance == sum of outstanding on non-cancelled bills, after a mix of saves and cancellations."""
    factory, ids = shop
    svc = ids["Xerox / Photocopy"]
    with session_scope(factory) as s:
        cid = customer_service.create_customer(s, "Ramu").id
        bills = []
        for i, paid in enumerate([0, 3000, 10000, 500]):
            payments = [PaymentInput(paid, "cash")] if paid else []
            bills.append(save_bill(s, BillRequest(f"k{i}", [LineRequest(Decimal(50), "page", 200, service_id=svc)],
                                                  payments=payments, customer_id=cid), lambda: "2026-02-10T08:00:00"))
        cancel_bill(s, bills[1].bill_id, "x")
        cancel_bill(s, bills[0].bill_id, "y")
    with session_scope(factory) as s:
        balance = s.scalar(select(func.sum(CustomerLedger.debit - CustomerLedger.credit)))
        live = s.scalar(select(func.sum(Bill.outstanding_amount)).where(Bill.status.notin_(["cancelled", "refunded"])))
        assert balance == live == 9500
