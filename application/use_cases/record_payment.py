"""Customer pays off udhar. One payment row per bill touched, each with its own ledger credit."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from business.accounting import allocate_payment, check_method
from business.errors import ValidationError
from business.timeutil import to_ist, utc_now_iso
from database.models import Bill, Customer, CustomerLedger, Payment


@dataclass(frozen=True)
class PaymentResult:
    allocations: list[tuple[int, int]]  # (bill_id, paise)
    created: bool  # False if this idempotency key had already been recorded


def outstanding_bills(session: Session, customer_id: int, bill_id: int | None = None) -> list[Bill]:
    """Bills still owing, oldest first (or just `bill_id`)."""
    query = (select(Bill).where(Bill.customer_id == customer_id, Bill.outstanding_amount > 0,
                                Bill.status.in_(("unpaid", "partial"))).order_by(Bill.bill_date, Bill.id))
    if bill_id is not None:
        query = query.where(Bill.id == bill_id)
    return list(session.scalars(query))


def preview_allocation(session: Session, customer_id: int, amount: int,
                       bill_id: int | None = None) -> list[tuple[str, int]]:
    """[(bill_number, paise)] this payment would settle, for showing before the owner confirms."""
    bills = outstanding_bills(session, customer_id, bill_id)
    numbers = {b.id: b.bill_number for b in bills}
    return [(numbers[i], a) for i, a in allocate_payment(amount, [(b.id, b.outstanding_amount) for b in bills])]


def record_customer_payment(session: Session, customer_id: int, amount: int, method: str, idempotency_key: str,
                            reference: str | None = None, bill_id: int | None = None,
                            clock: Callable[[], str] = utc_now_iso) -> PaymentResult:
    check_method(method)
    prefix = f"{idempotency_key}:"
    done = list(session.scalars(select(Payment).where(Payment.idempotency_key.startswith(prefix, autoescape=True))))
    if done:  # a retry / double click: report the original, change nothing
        return PaymentResult([(p.bill_id, p.amount) for p in done], created=False)
    if session.get(Customer, customer_id) is None:
        raise ValidationError("bill.unknown_customer")
    bills = outstanding_bills(session, customer_id, bill_id)
    if bill_id is not None and not bills:
        raise ValidationError("payment.nothing_due")
    allocations = allocate_payment(amount, [(b.id, b.outstanding_amount) for b in bills])

    now = clock()
    today = to_ist(now).date().isoformat()
    by_id = {b.id: b for b in bills}
    for target_id, paid in allocations:
        bill = by_id[target_id]
        payment = Payment(bill_id=bill.id, amount=paid, payment_method=method, kind="payment", payment_date=today,
                          reference_number=(reference or "").strip() or None,
                          idempotency_key=f"{prefix}{bill.id}", created_at=now)
        session.add(payment)
        session.flush()
        bill.total_paid += paid
        bill.outstanding_amount -= paid
        bill.status = "paid" if bill.outstanding_amount == 0 else "partial"
        session.add(CustomerLedger(
            customer_id=customer_id, transaction_type="payment", reference_type="payment", reference_id=payment.id,
            credit=paid, transaction_date=today, description=f"Payment ({method}) for bill {bill.bill_number}"))
    session.flush()
    return PaymentResult(allocations, created=True)
