"""Report -> .xlsx. Money is written as real numbers (rupees) so the owner can sum and chart them in Excel."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from business.report_model import Report, dmy, format_value

Tr = Callable[..., str]
RUPEE = '"₹"#,##0.00'
HEAD = PatternFill("solid", fgColor="E6F2F1")


def _cell_value(value, kind: str, tr: Tr):
    if value is None or value == "":
        return None
    if kind == "money":
        return Decimal(value) / 100  # exact rupees; openpyxl stores it as a number
    if kind in ("qty", "int"):
        return Decimal(value) if kind == "qty" else int(value)
    return format_value(value, kind, tr)


def write_excel(report: Report, tr: Tr, shop_name: str, generated: datetime, path: Path | str) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = tr(report.title)[:31].replace("/", "-")
    bold = Font(bold=True)
    ws.append([shop_name])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([tr(report.title)])
    ws["A2"].font = Font(bold=True, size=12)
    if report.period:
        a, b = report.period
        ws.append([dmy(a) if a == b else f"{dmy(a)} - {dmy(b)}"])
    ws.append([f"{tr('report.generated')}: {generated.strftime('%d-%m-%Y %H:%M')}"])
    ws.append([])
    for line in report.summary:  # (read max_row *after* appending: an empty append() does not move it)
        ws.append([tr(line.label) if line.translate else line.label, _cell_value(line.value, line.kind, tr)])
        r = ws.max_row
        cell = ws.cell(row=r, column=2)
        if line.kind == "money":
            cell.number_format = RUPEE
        if line.emphasis:
            ws.cell(row=r, column=1).font = bold
            cell.font = bold
    ws.append([])
    ws.append([tr(c.label) for c in report.columns])
    header_row = ws.max_row
    for cell in ws[header_row]:
        cell.font, cell.fill = bold, HEAD
        cell.alignment = Alignment(horizontal="center")
    for row in report.rows + ([report.total_row] if report.total_row is not None else []):
        ws.append([_cell_value(v, c.kind, tr) for c, v in zip(report.columns, row)])
        r = ws.max_row
        for col, c in enumerate(report.columns, 1):
            if c.kind == "money":
                ws.cell(row=r, column=col).number_format = RUPEE
    if report.total_row is not None:
        for cell in ws[ws.max_row]:
            cell.font = bold
    ws.append([])
    for note in report.notes:
        ws.append([tr(note)])
        ws.cell(row=ws.max_row, column=1).font = Font(italic=True, color="555555")
    for col in range(1, len(report.columns) + 1):  # readable widths without measuring every cell
        letter = get_column_letter(col)
        width = max((len(str(c.value)) for c in ws[letter][header_row - 1:] if c.value is not None
                     and c.row < ws.max_row - len(report.notes)), default=10)
        ws.column_dimensions[letter].width = min(max(width + 2, 11), 45)
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    wb.save(path)
