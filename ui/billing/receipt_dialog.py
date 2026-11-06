from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton, QTextBrowser,
    QVBoxLayout,
)

from application.services import printer_service, receipt_service
from application.services.i18n import LANGUAGES, Translator
from application.use_cases.cancel_bill import cancel_bill
from business.errors import DomainError
from database.connection import session_scope
from infrastructure.pdf import receipt as receipt_pdf
from ui.page import amp, request_pin, show_domain_error

log = logging.getLogger(__name__)


class ReceiptDialog(QDialog):
    """Preview a stored bill's receipt; print, save as PDF, or cancel the bill."""

    changed = Signal()  # the bill was cancelled

    def __init__(self, parent, session_factory, translator: Translator, bill_id: int) -> None:
        super().__init__(parent)
        self._sf, self._ui_tr, self._bill_id = session_factory, translator.tr, bill_id
        self._receipt_tr = Translator(translator.language)
        self.resize(760, 760)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.lang_label = QLabel()
        self.lang = QComboBox()
        for code in LANGUAGES:
            self.lang.addItem(self._ui_tr(f"lang.{code}"), code)
        self.lang.setCurrentIndex(LANGUAGES.index(translator.language))
        self.lang.activated.connect(lambda _i: self._render())
        top.addWidget(self.lang_label)
        top.addWidget(self.lang)
        top.addStretch(1)
        layout.addLayout(top)
        self.view = QTextBrowser()
        layout.addWidget(self.view, 1)
        self.status = QLabel()
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.print_btn, self.pdf_btn = QPushButton(), QPushButton()
        self.cancel_btn, self.close_btn = QPushButton(), QPushButton()
        for b in (self.print_btn, self.pdf_btn, self.cancel_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)
        self.print_btn.clicked.connect(self._print)
        self.pdf_btn.clicked.connect(self._save_pdf)
        self.cancel_btn.clicked.connect(self._cancel_bill)
        self.close_btn.clicked.connect(self.accept)
        self._retranslate()
        self._render()

    def _retranslate(self) -> None:
        t = self._ui_tr
        self.setWindowTitle(t("receipt.dialog_title"))
        self.lang_label.setText(t("receipt.language"))
        self.print_btn.setText(amp(t("receipt.print")))
        self.pdf_btn.setText(amp(t("receipt.save_pdf")))
        self.cancel_btn.setText(amp(t("receipt.cancel_bill")))
        self.close_btn.setText(amp(t("common.close")))

    def _data(self):
        with session_scope(self._sf) as s:
            return receipt_service.build_receipt_data(s, self._bill_id)

    def _render(self) -> None:
        self._receipt_tr.set_language(self.lang.currentData())
        self._data_cache = self._data()
        self._doc = receipt_pdf.build_document(self._data_cache, self._receipt_tr.tr)
        self.view.setDocument(self._doc)
        self.cancel_btn.setEnabled(self._data_cache.status not in ("cancelled", "refunded"))

    def _print(self) -> None:
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        with session_scope(self._sf) as s:
            saved = printer_service.get_default(s, "receipt_a4")
        if saved:  # the owner's chosen receipt printer is pre-selected in the dialog
            printer.setPrinterName(saved.printer_name)
        if QPrintDialog(printer, self).exec() != QDialog.DialogCode.Accepted:
            return
        try:
            receipt_pdf.print_to_printer(self._data_cache, self._receipt_tr.tr, printer)
        except Exception as exc:  # driver/spooler failures surface here; never claim success on failure
            log.exception("receipt print failed")
            QMessageBox.warning(self, self._ui_tr("common.error"), self._ui_tr("receipt.print_failed", error=str(exc)))
            return
        self.status.setText(self._ui_tr("receipt.sent"))

    def _save_pdf(self) -> None:
        default = str(Path.home() / "Documents" / f"{self._data_cache.bill_number}.pdf")
        path, _ = QFileDialog.getSaveFileName(self, self._ui_tr("receipt.save_pdf"), default, "PDF (*.pdf)")
        if not path:
            return
        try:
            receipt_pdf.write_pdf(self._data_cache, self._receipt_tr.tr, path)
        except OSError as exc:
            QMessageBox.warning(self, self._ui_tr("common.error"), str(exc))
            return
        self.status.setText(self._ui_tr("receipt.saved_to", path=path))

    def _cancel_bill(self) -> None:
        t = self._ui_tr
        reason, ok = QInputDialog.getText(self, t("receipt.cancel_bill"), t("bill.cancel_reason"))
        if not ok:
            return
        sure = QMessageBox.question(self, t("receipt.cancel_bill"),
                                    t("receipt.cancel_confirm", number=self._data_cache.bill_number))
        if sure != QMessageBox.StandardButton.Yes:
            return
        proceed, pin = request_pin(self, self._sf, t)
        if not proceed:
            return
        try:
            with session_scope(self._sf) as s:
                cancel_bill(s, self._bill_id, reason, pin)
        except DomainError as err:
            show_domain_error(self, err, t)
            return
        self.status.setText(t("receipt.cancelled_ok"))
        self._render()
        self.changed.emit()
