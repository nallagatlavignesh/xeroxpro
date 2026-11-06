"""Job orders: work taken in advance, with an advance payment and a delivery date.

Job money is recorded as payments linked to the job, so it appears in cash/UPI collections. A job is not a bill
(REQUIREMENTS A3), so job totals do not count as dashboard "sales".
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from business.accounting import check_method
from business.errors import ValidationError
from business.timeutil import to_ist, utc_now_iso
from database.models import AppMetadata, AuditLog, Customer, JobOrder, JobStatusHistory, Payment

STATUSES = ("received", "pending", "in_progress", "completed", "delivered", "cancelled")
OPEN = ("received", "pending", "in_progress")
TERMINAL = ("delivered", "cancelled")


@dataclass(frozen=True)
class JobRow:
    id: int
    number: str
    customer: str
    phone: str
    service_type: str
    description: str
    total: int
    advance: int
    balance: int
    expected_delivery: str | None
    status: str


def _next_number(session: Session, year: int) -> str:
    key = "job_counter"
    row = session.scalar(select(AppMetadata).where(AppMetadata.key == key))
    if row is None:
        row = AppMetadata(key=key, value="0")
        session.add(row)
    row.value = str(int(row.value) + 1)
    return f"J{year}-{int(row.value):05d}"


def _check_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValidationError("expense.date_invalid") from None


def _add_payment(session: Session, job: JobOrder, amount: int, method: str, key: str, now: str) -> None:
    session.add(Payment(job_id=job.id, amount=amount, payment_method=method, kind="payment",
                        payment_date=to_ist(now).date().isoformat(), idempotency_key=key, created_at=now))
    job.advance_amount += amount
    job.balance_amount = job.total_amount - job.advance_amount


def create_job(session: Session, customer_id: int, description: str, service_type: str, total: int, advance: int,
               advance_method: str, idempotency_key: str, expected_delivery: str | None = None, notes: str = "",
               clock: Callable[[], str] = utc_now_iso) -> JobOrder:
    description = description.strip()
    if not description:
        raise ValidationError("validation.required", field_key="jobs.description")
    if session.get(Customer, customer_id) is None:
        raise ValidationError("bill.unknown_customer")
    if total < 0:
        raise ValidationError("bill.rate_invalid")
    if advance < 0 or advance > total:
        raise ValidationError("jobs.advance_invalid")
    existing = session.scalar(select(JobOrder).join(Payment, Payment.job_id == JobOrder.id)
                              .where(Payment.idempotency_key == f"{idempotency_key}:advance"))
    if existing:  # repeated submit
        return existing
    now = clock()
    job = JobOrder(job_number=_next_number(session, to_ist(now).year), customer_id=customer_id,
                   job_description=description, service_type=service_type.strip(), total_amount=total,
                   advance_amount=0, balance_amount=total, expected_delivery=_check_date(expected_delivery),
                   job_status="received", notes=notes.strip(), created_at=now, updated_at=now)
    session.add(job)
    session.flush()
    session.add(JobStatusHistory(job_id=job.id, previous_status=None, new_status="received", changed_at=now))
    if advance:
        check_method(advance_method)
        _add_payment(session, job, advance, advance_method, f"{idempotency_key}:advance", now)
    session.flush()
    return job


def update_job(session: Session, job_id: int, description: str, service_type: str, total: int,
               expected_delivery: str | None, notes: str, clock: Callable[[], str] = utc_now_iso) -> JobOrder:
    job = session.get(JobOrder, job_id)
    if job is None or job.job_status in TERMINAL:
        raise ValidationError("jobs.not_editable")
    if not description.strip():
        raise ValidationError("validation.required", field_key="jobs.description")
    if total < job.advance_amount:
        raise ValidationError("jobs.total_below_advance")
    job.job_description, job.service_type = description.strip(), service_type.strip()
    job.total_amount, job.balance_amount = total, total - job.advance_amount
    job.expected_delivery, job.notes, job.updated_at = _check_date(expected_delivery), notes.strip(), clock()
    return job


def collect_payment(session: Session, job_id: int, amount: int, method: str, idempotency_key: str,
                    clock: Callable[[], str] = utc_now_iso) -> None:
    check_method(method)
    if session.scalar(select(Payment.id).where(Payment.idempotency_key == idempotency_key)):
        return  # repeat of a payment already recorded
    job = session.get(JobOrder, job_id)
    if job is None or job.job_status in TERMINAL:
        raise ValidationError("jobs.not_editable")
    if amount <= 0:
        raise ValidationError("bill.payment_positive")
    if amount > job.balance_amount:
        raise ValidationError("payment.exceeds_outstanding")
    now = clock()
    _add_payment(session, job, amount, method, idempotency_key, now)
    job.updated_at = now


def change_status(session: Session, job_id: int, new_status: str, notes: str = "",
                  clock: Callable[[], str] = utc_now_iso) -> JobOrder:
    """Move a job along. Delivered needs the balance cleared; cancelling refunds money taken (needs a reason)."""
    if new_status not in STATUSES:
        raise ValidationError("jobs.status_invalid")
    job = session.get(JobOrder, job_id)
    if job is None:
        raise ValidationError("jobs.not_editable")
    if job.job_status in TERMINAL:
        raise ValidationError("jobs.already_closed")
    if new_status == job.job_status:
        raise ValidationError("jobs.status_invalid")
    now = clock()
    if new_status == "delivered" and job.balance_amount > 0:
        raise ValidationError("jobs.balance_due")
    if new_status == "cancelled":
        if not notes.strip():
            raise ValidationError("validation.required", field_key="bill.cancel_reason")
        refunded = 0
        for p in list(session.scalars(select(Payment).where(Payment.job_id == job.id, Payment.kind == "payment"))):
            session.add(Payment(job_id=job.id, amount=p.amount, payment_method=p.payment_method, kind="refund",
                                payment_date=to_ist(now).date().isoformat(), notes=notes.strip(),
                                idempotency_key=f"refund:{p.id}", created_at=now))
            refunded += p.amount
        job.advance_amount, job.balance_amount = 0, 0
        session.add(AuditLog(action="job_cancelled", entity_type="job", entity_id=job.id, at=now, reason=notes.strip(),
                             details=json.dumps({"job_number": job.job_number, "refunded": refunded})))
    session.add(JobStatusHistory(job_id=job.id, previous_status=job.job_status, new_status=new_status,
                                 changed_at=now, notes=notes.strip()))
    job.job_status, job.updated_at = new_status, now
    session.flush()
    return job


def status_history(session: Session, job_id: int) -> list[JobStatusHistory]:
    return list(session.scalars(select(JobStatusHistory).where(JobStatusHistory.job_id == job_id)
                                .order_by(JobStatusHistory.id)))


def list_jobs(session: Session, text: str = "", status: str | None = None, only_open: bool = False) -> list[JobRow]:
    query = select(JobOrder, Customer).join(Customer, JobOrder.customer_id == Customer.id).order_by(JobOrder.id.desc())
    text = text.strip()
    if text:
        like = f"%{text}%"
        query = query.where(or_(JobOrder.job_number.like(like), Customer.customer_name.like(like),
                                Customer.phone.like(like), JobOrder.job_description.like(like)))
    if status:
        query = query.where(JobOrder.job_status == status)
    if only_open:
        query = query.where(JobOrder.job_status.in_(OPEN))
    return [JobRow(j.id, j.job_number, c.customer_name, c.phone, j.service_type, j.job_description, j.total_amount,
                   j.advance_amount, j.balance_amount, j.expected_delivery, j.job_status)
            for j, c in session.execute(query)]
