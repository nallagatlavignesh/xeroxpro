"""Inventory, expenses, jobs, online applications."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Quantity, created_col, updated_col


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("purchase_price >= 0 AND selling_price >= 0", name="prices"),
        CheckConstraint("minimum_stock >= 0", name="minimum"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    product_name: Mapped[str] = mapped_column(unique=True)
    category: Mapped[str] = mapped_column(default="")
    purchase_price: Mapped[int] = mapped_column(default=0)
    selling_price: Mapped[int] = mapped_column(default=0)
    # Never negative unless an authorised adjustment is used (enforced by the use case, audited).
    stock_quantity: Mapped[Decimal] = mapped_column(Quantity, default=Decimal(0))
    minimum_stock: Mapped[Decimal] = mapped_column(Quantity, default=Decimal(0))
    unit: Mapped[str] = mapped_column(default="item")
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[str] = created_col()
    updated_at: Mapped[str] = updated_col()


class InventoryTransaction(Base):
    """Append-only. quantity is signed; product.stock_quantity == sum(quantity)."""

    __tablename__ = "inventory_transactions"
    __table_args__ = (
        CheckConstraint(
            "transaction_type IN ('purchase','sale','return','adjustment','sale_reversal')", name="type"
        ),
        CheckConstraint("quantity <> 0 AND unit_cost >= 0", name="valid"),
        Index("ix_inventory_transactions_product", "product_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    transaction_type: Mapped[str]
    quantity: Mapped[Decimal] = mapped_column(Quantity)
    unit_cost: Mapped[int] = mapped_column(default=0)
    reference_id: Mapped[int | None]  # bill id for sales/reversals
    transaction_date: Mapped[str]
    notes: Mapped[str] = mapped_column(default="")


class Expense(Base):
    """Edits are audited; removal is voiding (is_voided), never deletion."""

    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("amount > 0", name="positive"),
        CheckConstraint("payment_method IN ('cash','upi','other')", name="method"),
        Index("ix_expenses_date", "expense_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str]
    description: Mapped[str] = mapped_column(default="")
    amount: Mapped[int]
    payment_method: Mapped[str] = mapped_column(default="cash")
    expense_date: Mapped[str]
    notes: Mapped[str] = mapped_column(default="")
    is_voided: Mapped[bool] = mapped_column(default=False)
    void_reason: Mapped[str | None]
    created_at: Mapped[str] = created_col()
    updated_at: Mapped[str] = updated_col()


class JobOrder(Base):
    __tablename__ = "job_orders"
    __table_args__ = (
        CheckConstraint("total_amount >= 0 AND advance_amount >= 0 AND balance_amount >= 0", name="amounts"),
        CheckConstraint(
            "job_status IN ('received','pending','in_progress','completed','delivered','cancelled')",
            name="status",
        ),
        Index("ix_job_orders_status_delivery", "job_status", "expected_delivery"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    job_number: Mapped[str] = mapped_column(unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"))
    job_description: Mapped[str]
    service_type: Mapped[str] = mapped_column(default="")
    total_amount: Mapped[int] = mapped_column(default=0)
    advance_amount: Mapped[int] = mapped_column(default=0)  # cache of job payments
    balance_amount: Mapped[int] = mapped_column(default=0)
    expected_delivery: Mapped[str | None]
    job_status: Mapped[str] = mapped_column(default="received")
    notes: Mapped[str] = mapped_column(default="")
    created_at: Mapped[str] = created_col()
    updated_at: Mapped[str] = updated_col()


class JobStatusHistory(Base):
    __tablename__ = "job_status_history"
    __table_args__ = (Index("ix_job_status_history_job", "job_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_orders.id", ondelete="RESTRICT"))
    previous_status: Mapped[str | None]
    new_status: Mapped[str]
    changed_at: Mapped[str] = created_col()
    notes: Mapped[str] = mapped_column(default="")


class ApplicationRecord(Base):
    """Never store passwords, OTPs or Aadhaar numbers here (including in notes)."""

    __tablename__ = "application_records"
    __table_args__ = (CheckConstraint("service_charge >= 0", name="charge"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"))
    bill_id: Mapped[int | None] = mapped_column(ForeignKey("bills.id", ondelete="RESTRICT"))
    application_type: Mapped[str]
    service_charge: Mapped[int] = mapped_column(default=0)
    payment_status: Mapped[str] = mapped_column(default="unpaid")  # display value derived from the bill
    reference_number: Mapped[str | None]
    application_status: Mapped[str] = mapped_column(default="received")
    application_date: Mapped[str]
    notes: Mapped[str] = mapped_column(default="")
