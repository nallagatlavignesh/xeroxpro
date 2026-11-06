"""Services & Rates tab: add/edit services, set a new rate, view rate history."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from application.services import catalog_service
from business.errors import DomainError, ValidationError
from business.money import format_inr, to_paise
from business.timeutil import to_ist
from database.connection import session_scope
from ui.page import amp, show_domain_error


class ServiceDialog(QDialog):
    def __init__(self, parent, sf, tr, units: list[str], row=None) -> None:
        super().__init__(parent)
        self._sf, self._tr, self._row = sf, tr, row
        self.setWindowTitle(tr("rates.edit_service" if row else "rates.add_service"))
        self.name = QLineEdit(row.name if row else "")
        self.unit = QComboBox()
        self.unit.setEditable(True)  # typing a new unit adds it to the list
        self.unit.addItems(units)
        self.unit.setCurrentText(row.unit if row else (units[0] if units else ""))
        self.category = QLineEdit(row.category if row else "")
        self.active = QCheckBox(tr("catalog.active"))
        self.active.setChecked(row.is_active if row else True)
        form = QFormLayout()
        form.addRow(tr("catalog.name"), self.name)
        form.addRow(tr("catalog.unit"), self.unit)
        form.addRow(tr("catalog.category"), self.category)
        form.addRow(self.active)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(box)

    def _save(self) -> None:
        try:
            with session_scope(self._sf) as s:
                catalog_service.save_service(s, self.name.text(), self.unit.currentText(), self.category.text(),
                                             self.active.isChecked(), self._row.id if self._row else None)
        except DomainError as err:
            show_domain_error(self, err, self._tr)
            return
        self.accept()


class RatesWidget(QWidget):
    def __init__(self, session_factory, tr) -> None:
        super().__init__()
        self._sf, self._tr = session_factory, tr
        self._rows: list = []
        root = QVBoxLayout(self)
        self.note = QLabel()
        self.note.setObjectName("hint")
        self.note.setWordWrap(True)
        root.addWidget(self.note)
        self.table = QTableWidget(0, 4)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)
        bar = QHBoxLayout()
        self.set_btn, self.edit_btn, self.add_btn, self.hist_btn = (QPushButton() for _ in range(4))
        for b in (self.set_btn, self.hist_btn, self.edit_btn, self.add_btn):
            bar.addWidget(b)
        bar.addStretch(1)
        root.addLayout(bar)
        self.set_btn.clicked.connect(self._set_rate)
        self.hist_btn.clicked.connect(self._history)
        self.edit_btn.clicked.connect(self._edit)
        self.add_btn.clicked.connect(self._add)
        self.retranslate()

    def retranslate(self) -> None:
        t = self._tr
        self.note.setText(t("rates.note"))
        self.set_btn.setText(amp(t("rates.set_rate")))
        self.hist_btn.setText(amp(t("rates.history")))
        self.edit_btn.setText(amp(t("rates.edit_service")))
        self.add_btn.setText(amp(t("rates.add_service")))
        self.table.setHorizontalHeaderLabels([t(k) for k in (
            "rates.col_service", "rates.col_unit", "rates.col_rate", "rates.col_active")])
        self.refresh()

    def refresh(self) -> None:
        with session_scope(self._sf) as s:
            self._rows = catalog_service.list_services(s)
        self.table.setRowCount(len(self._rows))
        for r, row in enumerate(self._rows):
            unit = self._tr(f"unit.{row.unit}")
            cells = [row.name, row.unit if unit == f"unit.{row.unit}" else unit,
                     self._tr("rates.not_set") if row.rate is None else format_inr(row.rate),
                     self._tr("common.yes" if row.is_active else "common.no")]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, c, item)

    def _selected(self):
        row = self.table.currentRow()
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def _set_rate(self) -> None:
        row = self._selected()
        if row is None:
            return
        text, ok = QInputDialog.getText(self, self._tr("rates.set_rate"), f"{row.name} - {self._tr('rates.new_rate')}")
        if not ok:
            return
        try:
            try:
                paise = to_paise(text.strip().replace(",", ""))
            except (ValueError, TypeError):
                raise ValidationError("rates.invalid") from None
            with session_scope(self._sf) as s:
                catalog_service.set_rate(s, row.id, paise)
        except DomainError as err:
            show_domain_error(self, err, self._tr)
            return
        self.refresh()

    def _history(self) -> None:
        row = self._selected()
        if row is None:
            return
        with session_scope(self._sf) as s:
            history = catalog_service.rate_history(s, row.id)
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{self._tr('rates.history')} - {row.name}")
        table = QTableWidget(len(history), 2)
        table.setHorizontalHeaderLabels([self._tr("rates.effective"), self._tr("rates.col_rate")])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for r, (effective, rate) in enumerate(history):
            table.setItem(r, 0, QTableWidgetItem(to_ist(effective).strftime("%d-%m-%Y %H:%M")))
            table.setItem(r, 1, QTableWidgetItem(format_inr(rate)))
        table.horizontalHeader().setStretchLastSection(True)
        layout = QVBoxLayout(dialog)
        layout.addWidget(table)
        dialog.resize(420, 320)
        dialog.exec()

    def _open_dialog(self, row=None) -> None:
        with session_scope(self._sf) as s:
            units = catalog_service.list_units(s)
        if ServiceDialog(self, self._sf, self._tr, units, row).exec():
            self.refresh()

    def _edit(self) -> None:
        if (row := self._selected()) is not None:
            self._open_dialog(row)

    def _add(self) -> None:
        self._open_dialog()
