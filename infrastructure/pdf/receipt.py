"""A4 receipt rendering with Qt (QTextDocument -> QPdfWriter/QPrinter).

Qt shapes Telugu correctly (ReportLab does not - see ARCHITECTURE.md R1), paginates long bills automatically
and repeats the table header on each page.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from html import escape
from pathlib import Path

from PySide6.QtCore import QMarginsF
from PySide6.QtGui import QFont, QFontDatabase, QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtPrintSupport import QPrinter

import config
from business.money import format_inr

Tr = Callable[..., str]
_fonts_loaded = False


@dataclass(frozen=True)
class ReceiptLine:
    description: str
    quantity: Decimal
    unit: str
    rate: int
    amount: int


@dataclass(frozen=True)
class ReceiptData:
    shop_name: str
    address: str
    phone: str  # empty when the owner hides it
    footer: str
    bill_number: str
    created_at: datetime  # already in IST
    customer_name: str | None
    lines: list[ReceiptLine]
    subtotal: int
    discount: int
    grand_total: int
    total_paid: int
    outstanding: int
    payments: list[tuple[str, int]] = field(default_factory=list)  # (method, amount), net of nothing: collected only
    status: str = "paid"


def ensure_fonts() -> None:
    global _fonts_loaded
    if not _fonts_loaded:
        for font_file in config.resource_path("fonts").glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(font_file))
        _fonts_loaded = True


def _qty(value: Decimal) -> str:
    return f"{value.normalize():f}"


def _unit(unit: str, tr: Tr) -> str:
    text = tr(f"unit.{unit}")
    return unit if text == f"unit.{unit}" else text  # unknown (owner-added) units stay as typed


def build_html(d: ReceiptData, tr: Tr) -> str:
    e = escape
    line_rows = "".join(
        f"<tr><td align='right'>{i}</td><td>{e(l.description)}</td>"
        f"<td align='right'>{e(_qty(l.quantity))} {e(_unit(l.unit, tr))}</td>"
        f"<td align='right'>{format_inr(l.rate)}</td><td align='right'>{format_inr(l.amount)}</td></tr>"
        for i, l in enumerate(d.lines, 1)
    )
    totals = [(tr("receipt.subtotal"), format_inr(d.subtotal))]
    if d.discount:
        totals.append((tr("receipt.discount"), "-" + format_inr(d.discount)))
    totals.append((f"<b>{tr('receipt.grand_total')}</b>", f"<b>{format_inr(d.grand_total)}</b>"))
    totals.append((tr("receipt.paid"), format_inr(d.total_paid)))
    totals.append((f"<b>{tr('receipt.balance')}</b>", f"<b>{format_inr(d.outstanding)}</b>"))
    total_rows = "".join(f"<tr><td align='right'>{a}</td><td align='right' width='28%'>{b}</td></tr>" for a, b in totals)
    paid_by = ", ".join(f"{tr('pay.' + m)} {format_inr(a)}" for m, a in d.payments)
    banner = ""
    if d.status in ("cancelled", "refunded"):
        banner = f"<p align='center' style='color:#B91C1C; font-size:16pt'><b>{e(tr('receipt.' + d.status))}</b></p>"
    contact = " &middot; ".join(x for x in (e(d.address).replace("\n", "<br>"),
                                             f"{tr('receipt.phone')}: {e(d.phone)}" if d.phone else "") if x)
    customer = f"<p>{tr('receipt.customer')}: <b>{e(d.customer_name)}</b></p>" if d.customer_name else ""
    footer = f"<p align='center'>{e(d.footer).replace(chr(10), '<br>')}</p>" if d.footer else ""
    stamp = d.created_at.strftime("%d-%m-%Y %H:%M")
    th = "bgcolor='#E6F2F1'"
    return f"""
<h1 align='center' style='font-size:20pt; color:#0F766E'>{e(d.shop_name)}</h1>
<p align='center'>{contact}</p>
<hr>
<table width='100%'><tr>
  <td><b>{tr('receipt.title')}</b> &nbsp; {tr('receipt.bill_no')}: <b>{e(d.bill_number)}</b></td>
  <td align='right'>{tr('receipt.date')}: {stamp}</td></tr></table>
{customer}{banner}
<table width='100%' border='1' cellspacing='0' cellpadding='5' style='border-collapse:collapse' bordercolor='#9CB8B5'>
<thead><tr>
  <th {th} width='6%'>{tr('receipt.col_no')}</th><th {th} align='left'>{tr('receipt.item')}</th>
  <th {th} align='right' width='20%'>{tr('receipt.qty')}</th><th {th} align='right' width='16%'>{tr('receipt.rate')}</th>
  <th {th} align='right' width='18%'>{tr('receipt.amount')}</th></tr></thead>
<tbody>{line_rows}</tbody></table>
<p></p>
<table width='60%' align='right' cellspacing='0' cellpadding='4'>{total_rows}</table>
<br clear='all'>
<p>{(tr('receipt.paid_by') + ': ' + e(paid_by)) if paid_by else ''}</p>
<hr>{footer}"""


def build_document(d: ReceiptData, tr: Tr) -> QTextDocument:
    ensure_fonts()
    doc = QTextDocument()
    font = QFont()
    font.setFamilies(["Noto Sans", "Noto Sans Telugu"])
    font.setPointSize(10)
    doc.setDefaultFont(font)
    doc.setHtml(build_html(d, tr))
    return doc


def _a4(device) -> None:
    device.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    device.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)


def write_pdf(d: ReceiptData, tr: Tr, path: Path | str) -> None:
    writer = QPdfWriter(str(path))
    _a4(writer)
    writer.setTitle(d.bill_number)
    build_document(d, tr).print_(writer)


def print_to_printer(d: ReceiptData, tr: Tr, printer: QPrinter) -> None:
    """Submits to the OS print queue. This does not prove paper came out (see REQUIREMENTS A8)."""
    _a4(printer)
    build_document(d, tr).print_(printer)
