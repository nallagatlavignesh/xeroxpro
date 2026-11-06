from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_col, updated_col


class PrinterSetting(Base):
    __tablename__ = "printer_settings"
    __table_args__ = (UniqueConstraint("printer_name", "printer_type", name="name_type"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    printer_name: Mapped[str]
    printer_type: Mapped[str] = mapped_column(default="documents")  # receipt_a4 | documents | other
    is_default: Mapped[bool] = mapped_column(default=False)
    paper_size: Mapped[str] = mapped_column(default="A4")
    created_at: Mapped[str] = created_col()
    updated_at: Mapped[str] = updated_col()


class AppMetadata(Base):
    """schema_version, app_version, last_backup_at, bill_counter:<year>, job_counter."""

    __tablename__ = "app_metadata"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(unique=True)
    value: Mapped[str]


class AuditLog(Base):
    """Append-only trail for cancellations, refunds, rate overrides, stock adjustments, restores."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_entity", "entity_type", "entity_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[str] = created_col()
    action: Mapped[str]
    entity_type: Mapped[str]
    entity_id: Mapped[int | None]
    reason: Mapped[str] = mapped_column(default="")
    details: Mapped[str | None]  # JSON


class DailyClosing(Base):
    __tablename__ = "daily_closings"
    id: Mapped[int] = mapped_column(primary_key=True)
    closing_date: Mapped[str] = mapped_column(unique=True)
    opening_cash: Mapped[int] = mapped_column(default=0)  # drawer cash carried from the previous closing
    expected_cash: Mapped[int]
    counted_cash: Mapped[int]
    difference: Mapped[int]
    notes: Mapped[str] = mapped_column(default="")
    created_at: Mapped[str] = created_col()


class BackupHistory(Base):
    __tablename__ = "backup_history"
    __table_args__ = (
        CheckConstraint("kind IN ('auto','manual','export','pre_restore','pre_migration')", name="kind"),
        CheckConstraint("status IN ('ok','failed')", name="status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    file_path: Mapped[str]
    created_at: Mapped[str] = created_col()
    size_bytes: Mapped[int] = mapped_column(default=0)
    kind: Mapped[str]
    status: Mapped[str]
    message: Mapped[str] = mapped_column(default="")
