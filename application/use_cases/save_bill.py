"""SaveBill: one transaction creates the bill, items, payments, ledger rows, stock movements and audit rows.

Call it inside `session_scope(...)`: any exception rolls everything back, including the bill-number counter.
"""
from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from application.services import auth_service, catalog_service
from business.billing import LineInput, PaymentInput, compute_totals
from business.errors import StockError, ValidationError
from business.timeutil import to_ist, utc_now_iso
from database.models import (
    AppMetadata, AuditLog, Bill, BillItem, Customer, CustomerLedger, InventoryTransaction, Payment, Product,
    Service, ShopSettings,
)


@dataclass(frozen=True)
class LineRequest:
    quantity: Decimal
    unit: str
    unit_rate: int  # paise, as shown to the cashier
    copies: int = 1
    service_id: int | None = None
    product_id: int | None = None
    rate_override: bool = False  # cashier deliberately changed the rate (needs owner PIN if one is set)
    details: dict = field(default_factory=dict)  # e.g. {"colour": false, "pages": "1-5"}


@dataclass(frozen=True)
class BillRequest:
    idempotency_key: str  # created when the bill screen opens; a repeated submit returns the same bill
    lines: list[LineRequest]
    payments: list[PaymentInput] = field(default_factory=list)
    customer_id: int | None = None
    discount: int = 0
    notes: str = ""
    pin: str | None = None


@dataclass(frozen=True)
class SavedBill:
    bill_id: int
    bill_number: str
    created: bool  # False when the idempotency key had already been saved


def save_bill(session: Session, req: BillRequest, clock: Callable[[], str] = utc_now_iso) -> SavedBill:
    existing = session.scalar(select(Bill).where(Bill.idempotency_key == req.idempotency_key))
    if existing:
        return SavedBill(existing.id, existing.bill_number, created=False)

    totals = compute_totals(
        [LineInput(l.quantity, l.unit_rate, l.copies) for l in req.lines], req.discount, req.payments
    )
    now = clock()
    local = to_ist(now)
    if req.customer_id is not None and session.get(Customer, req.customer_id) is None:
        raise ValidationError("bill.unknown_customer")

    overridden: list[tuple[LineRequest, int | None]] = []
    sources: list[Service | Product] = []
    for line in req.lines:
        if (line.service_id is None) == (line.product_id is None):
            raise ValidationError("bill.line_subject")
        if not line.unit.strip():
            raise ValidationError("bill.unit_required")
        if line.service_id is not None:
            source = session.get(Service, line.service_id)
            expected = catalog_service.current_rate(session, line.service_id, now) if source else None
        else:
            source = session.get(Product, line.product_id)
            expected = source.selling_price if source else None
        if source is None or not source.is_active:
            raise ValidationError("bill.item_unavailable")
        sources.append(source)
        if line.unit_rate != expected:
            if not line.rate_override:  # also catches a rate edited in Settings while the bill was open
                raise ValidationError("bill.no_rate" if expected is None else "bill.rate_mismatch",
                                      name=_name(source))
            overridden.append((line, expected))
    if overridden:
        auth_service.require_authorized(session, req.pin)

    wanted: dict[int, Decimal] = defaultdict(Decimal)
    for line, source in zip(req.lines, sources):
        if line.product_id is not None:
            wanted[source.id] += Decimal(line.quantity) * line.copies
    for product_id, qty in wanted.items():
        product = session.get(Product, product_id)
        if product.stock_quantity < qty:
            raise StockError("stock.insufficient", name=product.product_name, available=str(product.stock_quantity))

    if totals.outstanding > 0 and req.customer_id is None:
        raise ValidationError("bill.credit_needs_customer")

    bill = Bill(
        bill_number=_next_bill_number(session, local.year), customer_id=req.customer_id,
        bill_date=local.date().isoformat(), subtotal=totals.subtotal, discount=totals.discount,
        grand_total=totals.grand_total, total_paid=totals.total_paid, outstanding_amount=totals.outstanding,
        status=totals.status, notes=req.notes.strip(), idempotency_key=req.idempotency_key, created_at=now,
    )
    session.add(bill)
    session.flush()

    for line, source in zip(req.lines, sources):
        li = LineInput(line.quantity, line.unit_rate, line.copies)
        details = {"quantity": str(line.quantity), "copies": line.copies, **line.details}
        session.add(BillItem(
            bill_id=bill.id, service_id=line.service_id, product_id=line.product_id, description=_name(source),
            quantity=li.effective_quantity, unit=line.unit.strip(), unit_rate=line.unit_rate, amount=li.amount,
            unit_cost=source.purchase_price if line.product_id is not None else None,
            service_details=json.dumps(details, ensure_ascii=False),
        ))
        if line.product_id is not None:
            product = source
            product.stock_quantity = product.stock_quantity - li.effective_quantity
            session.add(InventoryTransaction(
                product_id=product.id, transaction_type="sale", quantity=-li.effective_quantity,
                unit_cost=product.purchase_price, reference_id=bill.id, transaction_date=local.date().isoformat(),
                notes=bill.bill_number))

    if req.customer_id is not None and totals.grand_total > 0:
        session.add(CustomerLedger(
            customer_id=req.customer_id, transaction_type="bill", reference_type="bill", reference_id=bill.id,
            debit=totals.grand_total, transaction_date=bill.bill_date, description=f"Bill {bill.bill_number}"))
    for i, p in enumerate(req.payments):
        payment = Payment(
            bill_id=bill.id, amount=p.amount, payment_method=p.method, kind="payment",
            payment_date=bill.bill_date, reference_number=(p.reference or "").strip() or None,
            idempotency_key=f"{req.idempotency_key}:p{i}", created_at=now)
        session.add(payment)
        session.flush()
        if req.customer_id is not None:
            session.add(CustomerLedger(
                customer_id=req.customer_id, transaction_type="payment", reference_type="payment",
                reference_id=payment.id, credit=p.amount, transaction_date=bill.bill_date,
                description=f"Payment ({p.method}) for bill {bill.bill_number}"))

    for line, expected in overridden:
        session.add(AuditLog(
            action="rate_override", entity_type="bill", entity_id=bill.id, at=now,
            reason="rate changed on bill", details=json.dumps(
                {"service_id": line.service_id, "product_id": line.product_id, "list_rate": expected,
                 "charged_rate": line.unit_rate})))
    session.flush()
    return SavedBill(bill.id, bill.bill_number, created=True)


def _name(source: Service | Product) -> str:
    return source.service_name if isinstance(source, Service) else source.product_name


def _next_bill_number(session: Session, year: int) -> str:
    """Counter row + bill row are written in the same transaction, so numbers are gap-free and never reused."""
    key = f"bill_counter:{year}"
    row = session.scalar(select(AppMetadata).where(AppMetadata.key == key))
    if row is None:
        row = AppMetadata(key=key, value="0")
        session.add(row)
    row.value = str(int(row.value) + 1)
    prefix = session.get(ShopSettings, 1).bill_prefix
    return f"{prefix}{year}-{int(row.value):06d}"
