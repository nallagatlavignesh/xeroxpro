"""Printers tab: shows what the OS reports and remembers the receipt / document printers."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFormLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from application.services import printer_service
from business.errors import DomainError
from database.connection import session_scope
from ui.page import amp, message_for


class PrintersWidget(QWidget):
    def __init__(self, session_factory, tr, gateway) -> None:
        super().__init__()
        self._sf, self._tr, self._gw = session_factory, tr, gateway
        root = QVBoxLayout(self)
        self.note = QLabel()
        self.note.setObjectName("hint")
        self.note.setWordWrap(True)
        self.table = QTableWidget(0, 5)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.receipt, self.documents = QComboBox(), QComboBox()
        form = QFormLayout()
        self._labels = {"printers.receipt": QLabel(), "printers.documents": QLabel()}
        form.addRow(self._labels["printers.receipt"], self.receipt)
        form.addRow(self._labels["printers.documents"], self.documents)
        self.save_btn, self.refresh_btn = QPushButton(), QPushButton()
        self.status = QLabel()
        for w in (self.note, self.table):
            root.addWidget(w)
        root.addLayout(form)
        for w in (self.save_btn, self.refresh_btn, self.status):
            root.addWidget(w)
        root.addStretch(1)
        self.save_btn.clicked.connect(self._save)
        self.refresh_btn.clicked.connect(self.refresh)
        self.retranslate()

    def _word(self, value) -> str:
        return self._tr("print.cap_unknown") if value is None else self._tr("print.cap_yes" if value else "print.cap_no")

    def refresh(self) -> None:
        rows = self._gw.list_printers()
        self.table.setRowCount(len(rows))
        for r, p in enumerate(rows):
            try:
                caps = self._gw.capabilities(p.name)
                cells = [p.name, self._tr("print.status_" + p.status), self._word(caps.colour), self._word(caps.duplex),
                         ", ".join(caps.paper_sizes) or self._tr("print.cap_unknown")]
            except DomainError:
                cells = [p.name, self._tr("print.status_" + p.status), "?", "?", "?"]
            for c, text in enumerate(cells):
                self.table.setItem(r, c, QTableWidgetItem(text))
        with session_scope(self._sf) as s:
            saved = {t: printer_service.get_default(s, t) for t in printer_service.TYPES}
        for combo, kind in ((self.receipt, "receipt_a4"), (self.documents, "documents")):
            combo.clear()
            combo.addItem(self._tr("printers.ask"), None)
            for p in rows:
                combo.addItem(p.name, p.name)
            if saved[kind]:
                combo.setCurrentIndex(max(combo.findData(saved[kind].printer_name), 0))
        self.status.setText("" if rows else self._tr("print.no_printers"))

    def _save(self) -> None:
        try:
            with session_scope(self._sf) as s:
                for combo, kind in ((self.receipt, "receipt_a4"), (self.documents, "documents")):
                    if combo.currentData():
                        printer_service.set_default(s, kind, combo.currentData())
        except DomainError as err:
            self.status.setText(message_for(err, self._tr))
            return
        self.status.setText(self._tr("common.saved"))

    def retranslate(self) -> None:
        t = self._tr
        self.note.setText(t("printers.note"))
        for key, label in self._labels.items():
            label.setText(t(key))
        self.table.setHorizontalHeaderLabels([t(k) for k in (
            "printers.printer", "history.col_status", "print.colour", "print.double", "print.paper")])
        self.save_btn.setText(amp(t("common.save")))
        self.refresh_btn.setText(amp(t("printers.refresh")))
        self.refresh()
