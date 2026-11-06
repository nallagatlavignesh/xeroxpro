from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem,
)

from application.services import reports, settings_service
from business.errors import DomainError
from business.report_model import Report, format_value, period_range
from business.timeutil import IST, ist_today
from database.connection import session_scope
from infrastructure.exports import excel, report_pdf
from ui.page import Page, amp, show_domain_error

REPORTS = [  # key, title key, needs a date range
    ("sales", "report.sales", True), ("service_sales", "report.service_sales", True),
    ("collections_cash", "report.collections_cash", True), ("collections_upi", "report.collections_upi", True),
    ("collections_other", "report.collections_other", True), ("outstanding", "report.outstanding", False),
    ("expenses", "report.expenses", True), ("inventory", "report.inventory", False),
    ("jobs", "report.jobs", True),
]
PERIODS = ("day", "week", "month", "custom")


def _qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


class ReportsPage(Page):
    def __init__(self, session_factory, translator) -> None:
        super().__init__("nav.reports", translator.tr)
        self._sf = session_factory
        self.report: Report | None = None
        bar = QHBoxLayout()
        self.which, self.period = QComboBox(), QComboBox()
        self.from_d, self.to_d = QDateEdit(_qdate(ist_today())), QDateEdit(_qdate(ist_today()))
        for d in (self.from_d, self.to_d):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd-MM-yyyy")
        self.which_l, self.period_l, self.to_l = QLabel(), QLabel(), QLabel("–")
        for w in (self.which_l, self.which, self.period_l, self.period, self.from_d, self.to_l, self.to_d):
            bar.addWidget(w)
        bar.addStretch(1)
        self.layout_.addLayout(bar)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        self.layout_.addWidget(self.summary)
        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.layout_.addWidget(self.table, 1)
        self.notes = QLabel()
        self.notes.setObjectName("hint")
        self.notes.setWordWrap(True)
        self.layout_.addWidget(self.notes)
        buttons = QHBoxLayout()
        self.pdf_btn, self.xlsx_btn, self.print_btn = QPushButton(), QPushButton(), QPushButton()
        for b in (self.pdf_btn, self.xlsx_btn, self.print_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        self.layout_.addLayout(buttons)

        self.which.activated.connect(lambda _i: self._controls())
        self.period.activated.connect(lambda _i: self._controls())
        self.from_d.dateChanged.connect(lambda _d: self._anchor_changed())
        self.to_d.dateChanged.connect(lambda _d: self.refresh())
        self.pdf_btn.clicked.connect(self._save_pdf)
        self.xlsx_btn.clicked.connect(self._save_excel)
        self.print_btn.clicked.connect(self._print)
        self.retranslate()

    def on_show(self) -> None:
        self.refresh()

    # ---- choosing what to show -------------------------------------------------------------------
    def _needs_range(self) -> bool:
        return next(r for r in REPORTS if r[0] == self.which.currentData())[2]

    def _controls(self) -> None:
        ranged = self._needs_range()
        custom = self.period.currentData() == "custom"
        self.period.setEnabled(ranged)
        self.period_l.setEnabled(ranged)
        self.from_d.setEnabled(ranged)
        self.to_d.setEnabled(ranged and custom)
        self.to_l.setEnabled(ranged and custom)
        if ranged and not custom:
            self._apply_period()
        self.refresh()

    def _apply_period(self) -> None:
        start, end = period_range(self.period.currentData(), self.from_d.date().toPython())
        self.to_d.blockSignals(True)
        self.to_d.setDate(_qdate(end))
        self.to_d.blockSignals(False)
        self._start = start

    def _anchor_changed(self) -> None:
        if self.period.currentData() != "custom":
            self._apply_period()
        self.refresh()

    def _range(self) -> tuple[date, date]:
        if self.period.currentData() == "custom":
            return self.from_d.date().toPython(), self.to_d.date().toPython()
        return period_range(self.period.currentData(), self.from_d.date().toPython())

    def build(self, session) -> Report:
        key = self.which.currentData()
        start, end = self._range()
        if key == "sales":
            return reports.sales_report(session, start, end)
        if key == "service_sales":
            return reports.service_sales_report(session, start, end)
        if key.startswith("collections_"):
            return reports.collections_report(session, start, end, key.split("_", 1)[1])
        if key == "expenses":
            return reports.expense_report(session, start, end)
        if key == "jobs":
            return reports.job_status_report(session, start, end)
        return reports.outstanding_report(session) if key == "outstanding" else reports.inventory_report(session)

    def refresh(self) -> None:
        t = self._tr
        try:
            with session_scope(self._sf) as s:
                self.report = self.build(s)
        except DomainError as err:
            self.report = None
            self.table.setRowCount(0)
            self.summary.setText(f"<span style='color:#B91C1C'>{t(err.key)}</span>")
            self.notes.clear()
            self._buttons()
            return
        r = self.report
        self.table.setColumnCount(len(r.columns))
        self.table.setHorizontalHeaderLabels([t(c.label) for c in r.columns])
        everything = r.rows + ([r.total_row] if r.total_row is not None else [])
        self.table.setRowCount(len(everything))
        for i, row in enumerate(everything):
            is_total = r.total_row is not None and i == len(r.rows)
            for j, (c, v) in enumerate(zip(r.columns, row)):
                item = QTableWidgetItem(format_value(v, c.kind, t))
                if c.kind in ("money", "qty", "int"):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if is_total:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.table.setItem(i, j, item)
        cells = [(f"{'<b>' if s.emphasis else ''}{t(s.label) if s.translate else s.label}{'</b>' if s.emphasis else ''}",
                  f"{'<b>' if s.emphasis else ''}{format_value(s.value, s.kind, t)}{'</b>' if s.emphasis else ''}")
                 for s in r.summary]
        half = (len(cells) + 1) // 2  # two columns of figures keep more room for the table
        left, right = cells[:half], cells[half:] + [("", "")] * (half - len(cells[half:]))
        lines = "".join(f"<tr><td style='padding-right:12px'>{a}</td><td align='right' style='padding-right:40px'>{b}</td>"
                        f"<td style='padding-right:12px'>{c}</td><td align='right'>{d}</td></tr>"
                        for (a, b), (c, d) in zip(left, right))
        self.summary.setText(f"<table>{lines}</table>")
        self.notes.setText("  ·  ".join(t(n) for n in r.notes))
        self._buttons()

    def _buttons(self) -> None:
        for b in (self.pdf_btn, self.xlsx_btn, self.print_btn):
            b.setEnabled(self.report is not None)

    # ---- output ----------------------------------------------------------------------------------
    def _shop(self) -> str:
        with session_scope(self._sf) as s:
            return settings_service.get_shop_settings(s).shop_name

    def _default_name(self, ext: str) -> str:
        r = self.report
        span = f"_{r.period[0]}_{r.period[1]}" if r.period and r.period[0] != r.period[1] else \
            f"_{r.period[0]}" if r.period else ""
        return str(Path.home() / "Documents" / f"{r.key}{span}.{ext}")

    def _save(self, ext: str, label: str, writer) -> None:
        if self.report is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, self._tr(label), self._default_name(ext), f"*.{ext}")
        if not path:
            return
        try:
            writer(path)
        except OSError as exc:
            QMessageBox.warning(self, self._tr("common.error"), self._tr("reports.save_failed", error=str(exc)))
            return
        self.notes.setText(self._tr("reports.saved", path=path))

    def _save_pdf(self) -> None:
        self._save("pdf", "reports.pdf", lambda p: report_pdf.write_pdf(
            self.report, self._tr, self._shop(), datetime.now(IST), p))

    def _save_excel(self) -> None:
        self._save("xlsx", "reports.excel", lambda p: excel.write_excel(
            self.report, self._tr, self._shop(), datetime.now(IST), p))

    def _print(self) -> None:
        if self.report is None:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        if QPrintDialog(printer, self).exec() != QDialog.DialogCode.Accepted:
            return
        try:
            report_pdf.print_to_printer(self.report, self._tr, self._shop(), datetime.now(IST), printer)
        except Exception as exc:  # driver/spooler problems must be shown, not swallowed
            QMessageBox.warning(self, self._tr("common.error"), self._tr("receipt.print_failed", error=str(exc)))
            return
        self.notes.setText(self._tr("reports.print_sent"))

    def retranslate(self) -> None:
        super().retranslate()
        t = self._tr
        current, period = self.which.currentData(), self.period.currentData() or "day"
        self.which.blockSignals(True)
        self.which.clear()
        for key, title, _ in REPORTS:
            self.which.addItem(t(title), key)
        self.which.setCurrentIndex(max(self.which.findData(current), 0))
        self.which.blockSignals(False)
        self.period.blockSignals(True)
        self.period.clear()
        for p in PERIODS:
            self.period.addItem(t(f"reports.{p}"), p)
        self.period.setCurrentIndex(PERIODS.index(period))
        self.period.blockSignals(False)
        self.which_l.setText(t("reports.report"))
        self.period_l.setText(t("reports.period"))
        self.pdf_btn.setText(amp(t("reports.pdf")))
        self.xlsx_btn.setText(amp(t("reports.excel")))
        self.print_btn.setText(amp(t("reports.print")))
        self._controls()
