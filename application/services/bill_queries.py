"""Read-only bill lookups for history and receipts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from database.models import Bill, BillItem, Customer, Payment


@dataclass(frozen=True)
class BillSummary:
    id: int
    bill_number: str
    bill_date: str
    customer_name: str | None
    grand_total: int
    total_paid: int
    outstanding: int
    status: str


@dataclass(frozen=True)
class ItemRow:
    description: str
    quantity: Decimal
    unit: str
    unit_rate: int
    amount: int


@dataclass(frozen=True)
class PaymentRow:
    method: str
    amount: int
    kind: str
    payment_date: str
    reference: str | None


@dataclass(frozen=True)
class BillDetail:
    summary: BillSummary
    customer_phone: str | None
    subtotal: int
    discount: int
    notes: str
    created_at: str  # UTC iso
    cancel_reason: str | None
    items: list[ItemRow]
    payments: list[PaymentRow]


def _summary(bill: Bill, customer: Customer | None) -> BillSummary:
    return BillSummary(bill.id, bill.bill_number, bill.bill_date, customer.customer_name if customer else None,
                       bill.grand_total, bill.total_paid, bill.outstanding_amount, bill.status)


def search_bills(session: Session, text: str = "", date_from: date | None = None, date_to: date | None = None,
                 status: str | None = None, limit: int = 300) -> list[BillSummary]:
    query = (select(Bill, Customer).outerjoin(Customer, Bill.customer_id == Customer.id)
             .order_by(Bill.id.desc()).limit(limit))
    text = text.strip()
    if text:
        like = f"%{text}%"
        query = query.where(or_(Bill.bill_number.like(like), Customer.customer_name.like(like),
                                Customer.phone.like(like)))
    if date_from:
        query = query.where(Bill.bill_date >= date_from.isoformat())
    if date_to:
        query = query.where(Bill.bill_date <= date_to.isoformat())
    if status:
        query = query.where(Bill.status == status)
    return [_summary(b, c) for b, c in session.execute(query)]


def customer_bills(session: Session, customer_id: int) -> list[BillSummary]:
    query = (select(Bill, Customer).join(Customer, Bill.customer_id == Customer.id)
             .where(Bill.customer_id == customer_id).order_by(Bill.id.desc()))
    return [_summary(b, c) for b, c in session.execute(query)]


def get_bill_detail(session: Session, bill_id: int) -> BillDetail:
    bill = session.get(Bill, bill_id)
    customer = session.get(Customer, bill.customer_id) if bill.customer_id else None
    items = [ItemRow(i.description, i.quantity, i.unit, i.unit_rate, i.amount)
             for i in session.scalars(select(BillItem).where(BillItem.bill_id == bill_id).order_by(BillItem.id))]
    payments = [PaymentRow(p.payment_method, p.amount, p.kind, p.payment_date, p.reference_number)
                for p in session.scalars(select(Payment).where(Payment.bill_id == bill_id).order_by(Payment.id))]
    return BillDetail(_summary(bill, customer), customer.phone if customer else None, bill.subtotal, bill.discount,
                      bill.notes, bill.created_at, bill.cancel_reason, items, payments)
