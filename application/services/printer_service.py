"""Remembers which printer to use for what (receipts vs documents)."""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from business.errors import ValidationError
from database.models import PrinterSetting

TYPES = ("receipt_a4", "documents")


def set_default(session: Session, printer_type: str, printer_name: str, paper_size: str = "A4") -> None:
    if printer_type not in TYPES or not printer_name.strip():
        raise ValidationError("validation.required", field_key="printers.printer")
    session.execute(update(PrinterSetting).where(PrinterSetting.printer_type == printer_type).values(is_default=False))
    row = session.scalar(select(PrinterSetting).where(PrinterSetting.printer_type == printer_type,
                                                      PrinterSetting.printer_name == printer_name))
    if row is None:
        row = PrinterSetting(printer_name=printer_name, printer_type=printer_type)
        session.add(row)
    row.is_default, row.paper_size = True, paper_size
    session.flush()


def get_default(session: Session, printer_type: str) -> PrinterSetting | None:
    return session.scalar(select(PrinterSetting).where(PrinterSetting.printer_type == printer_type,
                                                       PrinterSetting.is_default.is_(True)))
