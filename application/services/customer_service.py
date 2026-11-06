"""Customers and their udhar (credit) position. The ledger is the source of truth for balances."""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from business.errors import ValidationError
from database.models import Bill, Customer, CustomerLedger, Payment


@dataclass(frozen=True)
class CustomerRow:
    id: int
    name: str
    phone: str
    balance: int  # paise owed


@dataclass(frozen=True)
class LedgerRow:
    date: str
    type: str
    detail: str  # bill number, plus the payment method for payments/refunds
    debit: int
    credit: int
    balance: int  # running balance after this row


def _clean(name: str, phone: str) -> tuple[str, str]:
    name, phone = name.strip(), phone.strip()
    if not name:
        raise ValidationError("validation.required", field_key="customer.name")
    if phone and not 7 <= len(re.sub(r"\D", "", phone)) <= 15:
        raise ValidationError("customer.phone_invalid")
    return name, phone


def create_customer(session: Session, name: str, phone: str = "", address: str = "", notes: str = "") -> Customer:
    name, phone = _clean(name, phone)
    customer = Customer(customer_name=name, phone=phone, address=address.strip() or None, notes=notes.strip())
    session.add(customer)
    session.flush()
    return customer


def update_customer(session: Session, customer_id: int, name: str, phone: str = "", address: str = "",
                    notes: str = "") -> Customer:
    name, phone = _clean(name, phone)
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise ValidationError("bill.unknown_customer")
    customer.customer_name, customer.phone = name, phone
    customer.address, customer.notes = address.strip() or None, notes.strip()
    return customer


def search_customers(session: Session, text: str = "", limit: int = 50) -> list[Customer]:
    query = select(Customer).where(Customer.is_active.is_(True)).order_by(Customer.customer_name).limit(limit)
    text = text.strip()
    if text:
        like = f"%{text}%"
        query = query.where(or_(Customer.customer_name.like(like), Customer.phone.like(like)))
    return list(session.scalars(query))


def balance_of(session: Session, customer_id: int) -> int:
    return session.scalar(select(func.coalesce(func.sum(CustomerLedger.debit - CustomerLedger.credit), 0))
                          .where(CustomerLedger.customer_id == customer_id))


def list_with_balances(session: Session, text: str = "", only_owing: bool = False) -> list[CustomerRow]:
    """Customers with what they owe; `only_owing` gives the outstanding credit report (biggest debt first)."""
    owed = (select(CustomerLedger.customer_id, func.sum(CustomerLedger.debit - CustomerLedger.credit).label("bal"))
            .group_by(CustomerLedger.customer_id).subquery())
    query = (select(Customer, func.coalesce(owed.c.bal, 0)).outerjoin(owed, owed.c.customer_id == Customer.id)
             .where(Customer.is_active.is_(True)))
    text = text.strip()
    if text:
        like = f"%{text}%"
        query = query.where(or_(Customer.customer_name.like(like), Customer.phone.like(like)))
    if only_owing:
        query = query.where(func.coalesce(owed.c.bal, 0) > 0).order_by(func.coalesce(owed.c.bal, 0).desc())
    else:
        query = query.order_by(Customer.customer_name)
    return [CustomerRow(c.id, c.customer_name, c.phone, bal) for c, bal in session.execute(query)]


def total_outstanding(session: Session) -> int:
    return session.scalar(select(func.coalesce(func.sum(CustomerLedger.debit - CustomerLedger.credit), 0)))


def ledger(session: Session, customer_id: int) -> list[LedgerRow]:
    """Full transaction history, oldest first, with a running balance.

    `detail` is built from references (bill number, payment method) rather than the stored English description,
    so the screen can show it in the active language.
    """
    rows, balance = [], 0
    for e in session.scalars(select(CustomerLedger).where(CustomerLedger.customer_id == customer_id)
                             .order_by(CustomerLedger.id)):
        balance += e.debit - e.credit
        if e.reference_type == "payment":
            payment = session.get(Payment, e.reference_id)
            bill, method = session.get(Bill, payment.bill_id), payment.payment_method
        else:
            bill, method = session.get(Bill, e.reference_id), None
        rows.append(LedgerRow(e.transaction_date, e.transaction_type, f"{bill.bill_number}|{method or ''}",
                              e.debit, e.credit, balance))
    return rows


def payment_history(session: Session, customer_id: int) -> list[tuple[str, str, str, int, str]]:
    """[(date, bill number, method, amount, kind)] newest first, for this customer's bills."""
    q = (select(Payment.payment_date, Bill.bill_number, Payment.payment_method, Payment.amount, Payment.kind)
         .join(Bill, Payment.bill_id == Bill.id).where(Bill.customer_id == customer_id)
         .order_by(Payment.id.desc()))
    return [tuple(r) for r in session.execute(q)]
