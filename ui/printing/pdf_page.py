"""PDF Printing Assistant: open a PDF, choose pages/copies/colour/sides/printer, see the cost, print or add to a bill."""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QMessageBox,
    QProgressDialog, QPushButton, QRadioButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget, QLineEdit,
)

from application.services import catalog_service, printer_service
from business.errors import DomainError
from business.money import format_inr
from business.pricing import estimate_print, parse_page_ranges
from database.connection import session_scope
from infrastructure.pdf.pdf_info import PdfInfo, read_pdf, render_page
from infrastructure.printers.gateway import PrinterCaps, PrintRequest
from ui.page import Page, amp, message_for, show_domain_error

STANDARD_PAPERS = ("A4", "A3", "A5", "Letter", "Legal")


class PdfPrintPage(Page):
    add_to_bill = Signal(int, object, int, object)  # service id, quantity per copy, copies, details

    def __init__(self, session_factory, translator, gateway) -> None:
        super().__init__("nav.pdf_printing", translator.tr)
        self._sf, self._gw = session_factory, gateway
        self._info: PdfInfo | None = None
        self._pages: list[int] = []
        self._current = 1
        self._manual = False
        self._busy_setting = False
        self._caps: PrinterCaps | None = None
        self._estimate = None
        self._services: list = []

        body = QHBoxLayout()
        self.layout_.addLayout(body, 1)
        # --- preview column
        left = QVBoxLayout()
        self.open_btn = QPushButton()
        self.file_label = QLabel()
        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        self.preview = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidget(self.preview)
        scroll.setWidgetResizable(True)
        nav = QHBoxLayout()
        self.prev_btn, self.next_btn, self.page_label = QPushButton("◀"), QPushButton("▶"), QLabel()
        nav.addStretch(1)
        for w in (self.prev_btn, self.page_label, self.next_btn):
            nav.addWidget(w)
        nav.addStretch(1)
        for w in (self.open_btn, self.file_label, self.info_label):
            left.addWidget(w)
        left.addWidget(scroll, 1)
        left.addLayout(nav)
        body.addLayout(left, 3)
        # --- options column
        side = QWidget()
        form = QFormLayout(side)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)  # long Telugu labels move above their field
        self.range = QLineEdit()
        self.selected_label = QLabel()
        self.override = QSpinBox()
        self.override.setRange(1, 100000)
        self.copies = QSpinBox()
        self.copies.setRange(1, 9999)
        self.bw, self.colour = QRadioButton(), QRadioButton()
        self.single, self.double = QRadioButton(), QRadioButton()
        self.bw.setChecked(True)
        self.single.setChecked(True)
        for a, b in ((self.bw, self.colour), (self.single, self.double)):
            group = QButtonGroup(self)
            group.addButton(a)
            group.addButton(b)
        colour_row, sides_row = QHBoxLayout(), QHBoxLayout()
        for w in (self.bw, self.colour):
            colour_row.addWidget(w)
        for w in (self.single, self.double):
            sides_row.addWidget(w)
        self.printer, self.refresh_btn = QComboBox(), QPushButton("⟳")
        prow = QHBoxLayout()
        prow.addWidget(self.printer, 1)
        prow.addWidget(self.refresh_btn)
        self.paper = QComboBox()
        self.caps_label = QLabel()
        self.caps_label.setObjectName("hint")
        self.caps_label.setWordWrap(True)
        self.service = QComboBox()
        self.estimate_label = QLabel()
        self.estimate_label.setWordWrap(True)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.print_btn, self.bill_btn = QPushButton(), QPushButton()
        self._labels: dict[str, QLabel] = {}
        for key, field in (("print.range", self.range), ("print.selected", self.selected_label),
                           ("print.pages_to_bill", self.override), ("print.copies", self.copies),
                           ("print.colour_mode", colour_row), ("print.sides", sides_row),
                           ("print.printer", prow), ("print.paper", self.paper), ("print.capabilities", self.caps_label),
                           ("print.service", self.service)):
            self._labels[key] = QLabel()
            form.addRow(self._labels[key], field)
        form.addRow(self.estimate_label)
        form.addRow(self.status)
        form.addRow(self.print_btn)
        form.addRow(self.bill_btn)
        scroll2 = QScrollArea()
        scroll2.setWidget(side)
        scroll2.setWidgetResizable(True)
        scroll2.setFixedWidth(480)
        scroll2.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll2.setFrameShape(scroll2.Shape.NoFrame)
        body.addWidget(scroll2, 0)

        self.open_btn.clicked.connect(self._choose_file)
        self.prev_btn.clicked.connect(lambda: self._goto(self._current - 1))
        self.next_btn.clicked.connect(lambda: self._goto(self._current + 1))
        self.range.textChanged.connect(self._on_range)
        self.override.valueChanged.connect(self._on_override)
        for w in (self.copies,):
            w.valueChanged.connect(lambda _v: self._recalc())
        for r in (self.bw, self.colour, self.single, self.double):
            r.toggled.connect(lambda _c: self._on_options())
        self.printer.activated.connect(lambda _i: self._on_printer())
        self.refresh_btn.clicked.connect(self.load_printers)
        self.service.activated.connect(lambda _i: self._recalc())
        self.print_btn.clicked.connect(self._print)
        self.bill_btn.clicked.connect(self._add_to_bill)
        self.retranslate()

    # ---- file & preview ------------------------------------------------------------------------
    def on_show(self) -> None:
        self.load_printers()

    def open_pdf(self, path: str) -> bool:
        try:
            info = read_pdf(path)
        except DomainError as err:
            self._report(message_for(err, self._tr), True)
            return False
        self._info, self._current = info, 1
        self.range.clear()
        self.file_label.setText(path)
        self._update_doc_info()
        paper = info.paper_names[0]
        index = self.paper.findData(paper)
        if index >= 0:
            self.paper.setCurrentIndex(index)
        self._show_page()
        self._on_range()
        return True

    def _update_doc_info(self) -> None:
        info = self._info
        if info is None:
            self.info_label.clear()
            return
        text = self._tr("print.doc_info", pages=info.page_count, sizes=", ".join(sorted(set(info.paper_names))))
        if info.mixed_sizes:
            text += "\n" + self._tr("print.mixed_sizes")
        self.info_label.setText(text)

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self._tr("print.open"), "", "PDF (*.pdf)")
        if path:
            self.open_pdf(path)

    def _goto(self, number: int) -> None:
        if self._info and 1 <= number <= self._info.page_count:
            self._current = number
            self._show_page()

    def _show_page(self) -> None:
        if not self._info:
            return
        self.preview.setPixmap(QPixmap.fromImage(render_page(self._info.path, self._current, 70)))
        self.page_label.setText(f"{self._current} / {self._info.page_count}")
        self.prev_btn.setEnabled(self._current > 1)
        self.next_btn.setEnabled(self._current < self._info.page_count)

    # ---- options -------------------------------------------------------------------------------
    def load_printers(self) -> None:
        saved = None
        with session_scope(self._sf) as s:
            default = printer_service.get_default(s, "documents")
            saved = default.printer_name if default else None
            self._services = [r for r in catalog_service.list_services(s, active_only=True) if r.kind == "service"]
        rows = self._gw.list_printers()
        keep = self.printer.currentData() or saved
        self.printer.clear()
        for r in rows:
            label = r.name + ("" if r.status == "ready" else f"  ({self._tr('print.status_' + r.status)})")
            self.printer.addItem(label, r.name)
        if not rows:
            self.printer.addItem(self._tr("print.no_printers"), None)
        for target in (keep, next((r.name for r in rows if r.is_default), None)):
            index = self.printer.findData(target) if target else -1
            if index >= 0:
                self.printer.setCurrentIndex(index)
                break
        self.service.clear()
        for r in self._services:
            self.service.addItem(r.name, r.id)
        self._pick_service()
        self._on_printer()

    def _pick_service(self) -> None:
        wanted = "Colour Printing" if self.colour.isChecked() else "B&W Printing"
        index = self.service.findText(wanted)
        if index >= 0:
            self.service.setCurrentIndex(index)

    def _on_printer(self) -> None:
        name = self.printer.currentData()
        self._caps = None
        if name:
            try:
                self._caps = self._gw.capabilities(name)
            except DomainError:
                self._caps = None
        t = self._tr

        def word(value):
            return t("print.cap_unknown") if value is None else t("print.cap_yes" if value else "print.cap_no")

        caps = self._caps
        if caps is None:
            self.caps_label.setText(t("print.cap_unavailable") if name else "")
        else:
            papers = ", ".join(caps.paper_sizes) if caps.paper_sizes else t("print.cap_unknown")
            self.caps_label.setText(f"{t('print.colour')}: {word(caps.colour)} · {t('print.double')}: {word(caps.duplex)}"
                                    f" · {t('print.paper')}: {papers}")
        current = self.paper.currentData()
        self.paper.clear()
        sizes = caps.paper_sizes if caps and caps.paper_sizes else STANDARD_PAPERS
        for p in sizes:
            self.paper.addItem(p, p)
        if self._info and self._info.paper_names[0] in sizes:
            self.paper.setCurrentIndex(self.paper.findData(self._info.paper_names[0]))
        elif current in sizes:
            self.paper.setCurrentIndex(self.paper.findData(current))
        self._recalc()

    def _on_options(self) -> None:
        self._pick_service()
        self._recalc()

    def _on_range(self) -> None:
        self._manual = False
        self._recalc()

    def _on_override(self, _v: int) -> None:
        if not self._busy_setting:
            self._manual = True
            self._recalc()

    def _report(self, text: str, error: bool) -> None:
        self.status.setObjectName("statusError" if error else "status")
        self.status.setText(text)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _recalc(self) -> None:
        """Refresh page count, sheets and cost. All maths lives in business.pricing."""
        self._estimate, self._pages = None, []
        self.print_btn.setEnabled(False)
        self.bill_btn.setEnabled(False)
        if not self._info:
            self.selected_label.setText("")
            self.estimate_label.setText("")
            return
        t = self._tr
        try:
            self._pages = parse_page_ranges(self.range.text(), self._info.page_count)
            if not self._manual:
                self._busy_setting = True
                self.override.setValue(len(self._pages))
                self._busy_setting = False
            self.selected_label.setText(t("print.selected_count", n=len(self._pages)))
            rate_row = next((r for r in self._services if r.id == self.service.currentData()), None)
            if rate_row is None:
                self.estimate_label.setText("")
                return
            if rate_row.rate is None:
                self.estimate_label.setText(t("bill.no_rate_hint"))
                self._report("", False)
                return
            e = estimate_print(self.override.value(), self.copies.value(), self.double.isChecked(), rate_row.rate,
                               rate_row.unit)
        except DomainError as err:
            self.selected_label.setText("")
            self.estimate_label.setText("")
            self._report(message_for(err, t), True)
            return
        self._estimate = e
        self.estimate_label.setText(
            f"{t('print.est_pages', pages=e.pages_per_copy, copies=e.copies, total=e.total_pages)}\n"
            f"{t('print.est_sheets', per_copy=e.sheets_per_copy, total=e.total_sheets)}\n"
            f"{t('print.est_cost', rate=format_inr(e.rate), unit=self._unit(e.billing_unit), cost=format_inr(e.cost))}")
        warning = self._capability_problem()
        self._report(warning or "", bool(warning))
        self.bill_btn.setEnabled(True)
        self.print_btn.setEnabled(not warning and bool(self.printer.currentData()))

    def _unit(self, unit: str) -> str:
        text = self._tr(f"unit.{unit}")
        return unit if text == f"unit.{unit}" else text

    def _capability_problem(self) -> str:
        caps = self._caps
        if caps and self.colour.isChecked() and caps.colour is False:
            return self._tr("print.no_colour")
        if caps and self.double.isChecked() and caps.duplex is False:
            return self._tr("print.no_duplex")
        return ""  # capabilities the driver did not report are allowed; the label says "not detected"

    # ---- actions -------------------------------------------------------------------------------
    def _request(self) -> PrintRequest:
        return PrintRequest(self._info.path, self._pages, self.copies.value(), self.colour.isChecked(),
                            self.double.isChecked(), self.paper.currentData())

    def _print(self) -> None:
        if not (self._info and self._pages and self.printer.currentData()):
            return
        t = self._tr
        name = self.printer.currentData()
        ask = QMessageBox.question(self, t("print.confirm_title"),
                                   t("print.confirm", pages=len(self._pages), copies=self.copies.value(), printer=name))
        if ask != QMessageBox.StandardButton.Yes:
            return
        total = len(self._pages) * self.copies.value()
        progress = QProgressDialog(t("print.sending"), None, 0, total, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(400)

        def step(done: int, _total: int) -> None:
            progress.setValue(done)
            QApplication.processEvents()

        try:
            result = self._gw.print_pdf(name, self._request(), step)
        except DomainError as err:
            progress.close()
            self._report(message_for(err, t), True)
            show_domain_error(self, err, t)
            return
        progress.close()
        self._report(t("print.sent", pages=result.pages_sent), False)  # submitted to the queue, NOT "printed"

    def _add_to_bill(self) -> None:
        e = self._estimate
        if e is None:
            return
        details = {"pages": self.range.text().strip() or "all", "sides": "double" if e.duplex else "single",
                   "colour": self.colour.isChecked(), "sheets": e.total_sheets}
        self.add_to_bill.emit(self.service.currentData(), Decimal(e.quantity_per_copy), e.copies, details)

    def retranslate(self) -> None:
        super().retranslate()
        t = self._tr
        self.open_btn.setText(amp(t("print.open")))
        for key, label in self._labels.items():
            label.setText(t(key))
        self.bw.setText(amp(t("print.bw")))
        self.colour.setText(t("print.colour"))
        self.single.setText(t("print.single"))
        self.double.setText(t("print.double"))
        self.print_btn.setText(amp(t("print.print")))
        self.bill_btn.setText(amp(t("print.add_to_bill")))
        self.page_label.setText(self.page_label.text())
        if self._info is None:
            self.file_label.setText(t("print.no_file"))
        self._update_doc_info()
        self.load_printers()
