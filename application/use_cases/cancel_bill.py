"""CancelBill: nothing is deleted. Reversing rows, refund payments, stock returns and an audit row are added."""
from __future__ import annotations

import json
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from application.services import auth_service
from business.errors import ValidationError
from business.timeutil import to_ist, utc_now_iso
from database.models import AuditLog, Bill, BillItem, CustomerLedger, InventoryTransaction, Payment, Product


def cancel_bill(session: Session, bill_id: int, reason: str, pin: str | None = None,
                clock: Callable[[], str] = utc_now_iso) -> str:
    """Cancel a bill and refund everything collected on it (each refund uses the original payment's method).

    Returns the new status: 'cancelled' (nothing had been paid) or 'refunded'.
    shortcut: always a full refund, no keeping the money as customer advance; add a mode if the shop needs it.
    """
    reason = reason.strip()
    if not reason:
        raise ValidationError("validation.required", field_key="bill.cancel_reason")
    auth_service.require_authorized(session, pin)
    bill = session.get(Bill, bill_id)
    if bill is None:
        raise ValidationError("bill.not_found")
    if bill.status in ("cancelled", "refunded"):
        raise ValidationError("bill.already_cancelled")

    now = clock()
    today = to_ist(now).date().isoformat()
    paid = list(session.scalars(select(Payment).where(Payment.bill_id == bill.id, Payment.kind == "payment")))
    refunded = 0
    for p in paid:
        refund = Payment(
            bill_id=bill.id, amount=p.amount, payment_method=p.payment_method, kind="refund", payment_date=today,
            notes=reason, idempotency_key=f"refund:{p.id}", created_at=now)
        session.add(refund)
        session.flush()
        refunded += p.amount
        if bill.customer_id is not None:
            session.add(CustomerLedger(
                customer_id=bill.customer_id, transaction_type="refund", reference_type="payment",
                reference_id=refund.id, debit=p.amount, transaction_date=today,
                description=f"Refund for cancelled bill {bill.bill_number}"))
    if bill.customer_id is not None and bill.grand_total > 0:
        session.add(CustomerLedger(
            customer_id=bill.customer_id, transaction_type="bill_reversal", reference_type="bill",
            reference_id=bill.id, credit=bill.grand_total, transaction_date=today,
            description=f"Cancelled bill {bill.bill_number}"))

    for item in session.scalars(select(BillItem).where(BillItem.bill_id == bill.id, BillItem.product_id.isnot(None))):
        product = session.get(Product, item.product_id)
        product.stock_quantity = product.stock_quantity + item.quantity
        session.add(InventoryTransaction(
            product_id=product.id, transaction_type="sale_reversal", quantity=item.quantity,
            unit_cost=item.unit_cost or 0, reference_id=bill.id, transaction_date=today,
            notes=f"Cancelled bill {bill.bill_number}"))

    bill.status = "refunded" if paid else "cancelled"
    bill.total_paid = 0
    bill.outstanding_amount = 0
    bill.cancelled_at = now
    bill.cancel_reason = reason
    session.add(AuditLog(
        action="bill_cancelled", entity_type="bill", entity_id=bill.id, reason=reason, at=now,
        details=json.dumps({"bill_number": bill.bill_number, "refunded": refunded, "status": bill.status})))
    session.flush()
    return bill.status
