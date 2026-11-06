from __future__ import annotations

from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Quantity, created_col


class Bill(Base):
    """Cached totals (total_paid/outstanding) are maintained only by use cases and reconciled by tests."""

    __tablename__ = "bills"
    __table_args__ = (
        CheckConstraint("status IN ('unpaid','partial','paid','cancelled','refunded')", name="status"),
        CheckConstraint("subtotal >= 0 AND discount >= 0 AND discount <= subtotal", name="amounts"),
        CheckConstraint("grand_total = subtotal - discount", name="grand_total"),
        CheckConstraint("total_paid >= 0 AND outstanding_amount >= 0", name="paid_nonneg"),
        CheckConstraint(
            "status IN ('cancelled','refunded') OR outstanding_amount = grand_total - total_paid",
            name="outstanding",
        ),
        CheckConstraint("outstanding_amount = 0 OR customer_id IS NOT NULL", name="credit_needs_customer"),
        Index("ix_bills_bill_date", "bill_date"),
        Index("ix_bills_customer", "customer_id"),
        Index("ix_bills_status", "status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    bill_number: Mapped[str] = mapped_column(unique=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"))
    bill_date: Mapped[str]
    subtotal: Mapped[int]
    discount: Mapped[int] = mapped_column(default=0)
    grand_total: Mapped[int]
    total_paid: Mapped[int] = mapped_column(default=0)
    outstanding_amount: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(default="unpaid")
    notes: Mapped[str] = mapped_column(default="")
    idempotency_key: Mapped[str] = mapped_column(unique=True)
    cancelled_at: Mapped[str | None]
    cancel_reason: Mapped[str | None]
    created_at: Mapped[str] = created_col()


class BillItem(Base):
    __tablename__ = "bill_items"
    __table_args__ = (
        CheckConstraint("quantity > 0 AND unit_rate >= 0", name="positive"),
        # same rule as business.money.line_amount: round-half-up of quantity(thousandths) x rate
        CheckConstraint("amount = (quantity * unit_rate + 500) / 1000", name="amount"),
        CheckConstraint("service_id IS NOT NULL OR product_id IS NOT NULL OR description <> ''", name="has_subject"),
        Index("ix_bill_items_bill", "bill_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    bill_id: Mapped[int] = mapped_column(ForeignKey("bills.id", ondelete="RESTRICT"))
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id", ondelete="RESTRICT"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    description: Mapped[str] = mapped_column(default="")
    quantity: Mapped[Decimal] = mapped_column(Quantity)
    unit: Mapped[str]
    unit_rate: Mapped[int]  # historical rate, paise
    amount: Mapped[int]
    unit_cost: Mapped[int | None]  # stationery purchase price at time of sale (profit estimate)
    service_details: Mapped[str | None]  # JSON: pages, copies, colour, duplex, range...


class Payment(Base):
    """Collected money. Refunds are kind='refund' with a positive amount. Never deleted."""

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="positive"),
        CheckConstraint("(bill_id IS NULL) <> (job_id IS NULL)", name="one_target"),
        CheckConstraint("payment_method IN ('cash','upi','other')", name="method"),
        CheckConstraint("kind IN ('payment','refund')", name="kind"),
        Index("ix_payments_date_method", "payment_date", "payment_method"),
        Index("ix_payments_bill", "bill_id"),
        Index("ix_payments_job", "job_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    bill_id: Mapped[int | None] = mapped_column(ForeignKey("bills.id", ondelete="RESTRICT"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("job_orders.id", ondelete="RESTRICT"))
    amount: Mapped[int]
    payment_method: Mapped[str]
    kind: Mapped[str] = mapped_column(default="payment")
    payment_date: Mapped[str]
    reference_number: Mapped[str | None]
    notes: Mapped[str] = mapped_column(default="")
    idempotency_key: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[str] = created_col()
