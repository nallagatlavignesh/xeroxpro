"""Declarative base, shared column types and helpers.

Money columns are plain Integer (paise). Quantity columns hold thousandths and surface as Decimal.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Integer, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from business.timeutil import utc_now_iso

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class Quantity(TypeDecorator):
    """Decimal in Python, integer thousandths in SQLite (exact and SUM-able)."""

    impl = Integer
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        scaled = Decimal(value) * 1000
        if scaled != scaled.to_integral_value():
            raise ValueError("quantity allows at most 3 decimal places")
        return int(scaled)

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value).scaleb(-3)


def created_col() -> Mapped[str]:
    return mapped_column(String, nullable=False, default=utc_now_iso)


def updated_col() -> Mapped[str]:
    return mapped_column(String, nullable=False, default=utc_now_iso, onupdate=utc_now_iso)
