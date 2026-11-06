from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_col, updated_col


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        Index("ix_customers_phone", "phone"),
        Index("ix_customers_name", "customer_name"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_name: Mapped[str]
    phone: Mapped[str] = mapped_column(default="")
    address: Mapped[str | None]
    notes: Mapped[str] = mapped_column(default="")
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[str] = created_col()
    updated_at: Mapped[str] = updated_col()


class CustomerLedger(Base):
    """Balance = sum(debit) - sum(credit). Never stored. Unique key blocks duplicate retries."""

    __tablename__ = "customer_ledger"
    __table_args__ = (
        CheckConstraint("transaction_type IN ('bill','payment','bill_reversal','refund','adjustment')", name="type"),
        CheckConstraint("debit >= 0 AND credit >= 0 AND (debit = 0 OR credit = 0)", name="one_side"),
        UniqueConstraint("reference_type", "reference_id", "transaction_type", name="reference"),
        Index("ix_customer_ledger_customer_date", "customer_id", "transaction_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"))
    transaction_type: Mapped[str]
    reference_type: Mapped[str]
    reference_id: Mapped[int]
    debit: Mapped[int] = mapped_column(default=0)
    credit: Mapped[int] = mapped_column(default=0)
    transaction_date: Mapped[str]
    description: Mapped[str] = mapped_column(default="")
