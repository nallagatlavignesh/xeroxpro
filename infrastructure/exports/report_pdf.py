"""Report -> PDF / printer, with the same Qt engine as receipts (correct Telugu, repeated table header)."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from html import escape
from pathlib import Path

from PySide6.QtCore import QMarginsF
from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtPrintSupport import QPrinter

from business.report_model import Report, SummaryLine, dmy, format_value
from infrastructure.pdf.receipt import ensure_fonts

Tr = Callable[..., str]
_NUMERIC = ("money", "qty", "int")


def _summary_html(lines: list[SummaryLine], tr: Tr) -> str:
    rows = "".join(
        f"<tr><td>{'<b>' if s.emphasis else ''}{escape(tr(s.label) if s.translate else s.label)}"
        f"{'</b>' if s.emphasis else ''}</td><td align='right'>{'<b>' if s.emphasis else ''}"
        f"{escape(format_value(s.value, s.kind, tr))}{'</b>' if s.emphasis else ''}</td></tr>" for s in lines)
    return f"<table cellspacing='0' cellpadding='3' width='55%'>{rows}</table>" if rows else ""


def build_html(report: Report, tr: Tr, shop_name: str, generated: datetime) -> str:
    cols = report.columns
    head = "".join(f"<th bgcolor='#E6F2F1' align='{'right' if c.kind in _NUMERIC else 'left'}'>{escape(tr(c.label))}</th>"
                   for c in cols)
    body = "".join(
        "<tr>" + "".join(f"<td align='{'right' if c.kind in _NUMERIC else 'left'}'>"
                         f"{escape(format_value(v, c.kind, tr))}</td>" for c, v in zip(cols, row)) + "</tr>"
        for row in report.rows)
    total = ""
    if report.total_row is not None:
        cells = []
        for c, v in zip(cols, report.total_row):
            text = escape(format_value(v, c.kind, tr))
            cells.append(f"<td bgcolor='#F1F6F6' align='{'right' if c.kind in _NUMERIC else 'left'}'>"
                         f"{'<b>' + text + '</b>' if text else ''}</td>")
        total = "<tr>" + "".join(cells) + "</tr>"
    period = ""
    if report.period:
        a, b = report.period
        period = dmy(a) if a == b else f"{dmy(a)} – {dmy(b)}"
    empty = f"<p>{escape(tr('history.none'))}</p>" if not report.rows else ""
    notes = "".join(f"<li>{escape(tr(n))}</li>" for n in report.notes)
    return f"""
<h1 style='font-size:17pt; color:#0F766E'>{escape(shop_name)}</h1>
<h2 style='font-size:14pt'>{escape(tr(report.title))}</h2>
<p>{escape(period)} &nbsp;·&nbsp; {escape(tr('report.generated'))}: {generated.strftime('%d-%m-%Y %H:%M')}</p>
{_summary_html(report.summary, tr)}
<p></p>
<table width='100%' border='1' cellspacing='0' cellpadding='4' style='border-collapse:collapse' bordercolor='#9CB8B5'>
<thead><tr>{head}</tr></thead><tbody>{body}{total}</tbody></table>{empty}
<p></p><ul style='font-size:8pt; color:#4B5563'>{notes}</ul>"""


def build_document(report: Report, tr: Tr, shop_name: str, generated: datetime) -> QTextDocument:
    ensure_fonts()
    doc = QTextDocument()
    font = QFont()
    font.setFamilies(["Noto Sans", "Noto Sans Telugu"])
    font.setPointSize(9)
    doc.setDefaultFont(font)
    doc.setHtml(build_html(report, tr, shop_name, generated))
    return doc


def _page(device, report: Report) -> None:
    wide = len(report.columns) > 6  # wide tables get a landscape page
    device.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    device.setPageOrientation(QPageLayout.Orientation.Landscape if wide else QPageLayout.Orientation.Portrait)
    device.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)


def write_pdf(report: Report, tr: Tr, shop_name: str, generated: datetime, path: Path | str) -> None:
    writer = QPdfWriter(str(path))
    _page(writer, report)
    writer.setTitle(tr(report.title))
    build_document(report, tr, shop_name, generated).print_(writer)


def print_to_printer(report: Report, tr: Tr, shop_name: str, generated: datetime, printer: QPrinter) -> None:
    _page(printer, report)
    build_document(report, tr, shop_name, generated).print_(printer)
