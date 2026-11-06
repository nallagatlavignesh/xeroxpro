from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_col, updated_col


class ShopSettings(Base):
    __tablename__ = "shop_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="single_row"),
        CheckConstraint("preferred_language IN ('en','te')", name="language"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_name: Mapped[str]
    address: Mapped[str] = mapped_column(default="")
    phone: Mapped[str] = mapped_column(default="")
    email: Mapped[str | None]
    receipt_footer: Mapped[str] = mapped_column(default="")
    preferred_language: Mapped[str] = mapped_column(default="en")
    currency: Mapped[str] = mapped_column(default="INR")
    default_payment_method: Mapped[str] = mapped_column(default="cash")
    bill_prefix: Mapped[str] = mapped_column(default="")
    receipt_show_phone: Mapped[bool] = mapped_column(default=True)
    backup_dir: Mapped[str | None]
    owner_pin_hash: Mapped[str | None]
    created_at: Mapped[str] = created_col()
    updated_at: Mapped[str] = updated_col()


class Service(Base):
    __tablename__ = "services"
    __table_args__ = (CheckConstraint("kind IN ('service','stationery','custom')", name="kind"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    service_name: Mapped[str] = mapped_column(unique=True)
    category: Mapped[str]
    billing_unit: Mapped[str]
    is_active: Mapped[bool] = mapped_column(default=True)
    description: Mapped[str] = mapped_column(default="")
    kind: Mapped[str] = mapped_column(default="service")
    created_at: Mapped[str] = created_col()
    updated_at: Mapped[str] = updated_col()


class ServiceRate(Base):
    """Append-only rate history. Current rate = latest effective_from <= now."""

    __tablename__ = "service_rates"
    __table_args__ = (
        CheckConstraint("rate >= 0", name="rate_nonneg"),
        UniqueConstraint("service_id", "effective_from", name="service_effective"),
        Index("ix_service_rates_service_effective", "service_id", "effective_from"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="RESTRICT"))
    rate: Mapped[int] = mapped_column(Integer)  # paise
    effective_from: Mapped[str]
    created_at: Mapped[str] = created_col()


class LookupValue(Base):
    """Editable pick-lists: unit, expense_category, application_type, service_category."""

    __tablename__ = "lookup_values"
    __table_args__ = (UniqueConstraint("kind", "value", name="kind_value"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String)
    value: Mapped[str] = mapped_column(String)
    sort_order: Mapped[int] = mapped_column(default=0)
