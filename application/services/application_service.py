"""Online application / government form assistance records.

Never store passwords, OTPs or Aadhaar numbers: free text is screened for the obvious cases.
Payment status is read from the linked bill, not stored twice (REQUIREMENTS A4).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from business.errors import ValidationError
from database.models import ApplicationRecord, Bill, Customer

STATUSES = ("received", "submitted", "in_progress", "completed", "rejected")
_AADHAAR = re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)")
_SECRET = re.compile(r"\b(password|passwd|pwd|otp|pin)\b\s*[:=\-]\s*\S+", re.IGNORECASE)


@dataclass(frozen=True)
class ApplicationRow:
    id: int
    date: str
    customer: str
    type: str
    charge: int
    reference: str
    status: str
    payment_status: str  # unpaid | partial | paid | cancelled | refunded | not_billed
    bill_number: str | None
    notes: str


def check_no_secrets(*texts: str) -> None:
    for text in texts:
        if _AADHAAR.search(text or "") or _SECRET.search(text or ""):
            raise ValidationError("applications.sensitive")


def _clean(customer_id: int, application_type: str, charge: int, app_date: str, notes: str, status: str,
           session: Session) -> date:
    if not application_type.strip():
        raise ValidationError("validation.required", field_key="applications.type")
    if charge < 0:
        raise ValidationError("bill.rate_invalid")
    if status not in STATUSES:
        raise ValidationError("jobs.status_invalid")
    if session.get(Customer, customer_id) is None:
        raise ValidationError("bill.unknown_customer")
    check_no_secrets(notes)
    try:
        return date.fromisoformat(app_date)
    except ValueError:
        raise ValidationError("expense.date_invalid") from None


def _link(session: Session, bill_number: str, customer_id: int) -> int | None:
    bill_number = bill_number.strip()
    if not bill_number:
        return None
    bill = session.scalar(select(Bill).where(Bill.bill_number == bill_number))
    if bill is None or bill.customer_id not in (None, customer_id):
        raise ValidationError("applications.bill_invalid")
    return bill.id


def save_application(session: Session, customer_id: int, application_type: str, charge: int, app_date: str,
                     reference_number: str = "", notes: str = "", status: str = "received", bill_number: str = "",
                     application_id: int | None = None) -> ApplicationRecord:
    when = _clean(customer_id, application_type, charge, app_date, notes, status, session)
    bill_id = _link(session, bill_number, customer_id)
    if application_id is None:
        record = ApplicationRecord(customer_id=customer_id, application_date=when.isoformat())
        session.add(record)
    else:
        record = session.get(ApplicationRecord, application_id)
    record.customer_id, record.application_type, record.service_charge = customer_id, application_type.strip(), charge
    record.application_date, record.reference_number = when.isoformat(), reference_number.strip() or None
    record.notes, record.application_status, record.bill_id = notes.strip(), status, bill_id
    session.flush()
    return record


def set_status(session: Session, application_id: int, status: str) -> None:
    if status not in STATUSES:
        raise ValidationError("jobs.status_invalid")
    session.get(ApplicationRecord, application_id).application_status = status


def list_applications(session: Session, text: str = "", status: str | None = None) -> list[ApplicationRow]:
    query = (select(ApplicationRecord, Customer, Bill)
             .join(Customer, ApplicationRecord.customer_id == Customer.id)
             .outerjoin(Bill, ApplicationRecord.bill_id == Bill.id).order_by(ApplicationRecord.id.desc()))
    text = text.strip()
    if text:
        like = f"%{text}%"
        query = query.where(or_(Customer.customer_name.like(like), Customer.phone.like(like),
                                ApplicationRecord.application_type.like(like),
                                ApplicationRecord.reference_number.like(like)))
    if status:
        query = query.where(ApplicationRecord.application_status == status)
    return [ApplicationRow(a.id, a.application_date, c.customer_name, a.application_type, a.service_charge,
                           a.reference_number or "", a.application_status, b.status if b else "not_billed",
                           b.bill_number if b else None, a.notes)
            for a, c, b in session.execute(query)]
