from __future__ import annotations

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from application.services import catalog_service, inventory_service
from business.errors import DomainError, ValidationError
from business.money import format_inr
from database.connection import session_scope
from database.models import Product
from ui.page import Page, amp, parse_money, request_pin, show_domain_error

RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def parse_qty(text: str) -> Decimal:
    try:
        return Decimal(text.strip())
    except InvalidOperation:
        raise ValidationError("bill.quantity_positive") from None


def _fmt(q: Decimal) -> str:
    return f"{q.normalize():f}"


class ProductDialog(QDialog):
    def __init__(self, parent, sf, tr, product_id: int | None = None) -> None:
        super().__init__(parent)
        self._sf, self._tr, self._id = sf, tr, product_id
        self.setWindowTitle(tr("inventory.edit" if product_id else "inventory.new"))
        self.name, self.category = QLineEdit(), QLineEdit()
        self.unit = QComboBox()
        self.unit.setEditable(True)
        self.purchase, self.selling, self.minimum = QLineEdit(), QLineEdit(), QLineEdit("0")
        self.active = QCheckBox(tr("catalog.active"))
        self.active.setChecked(True)
        with session_scope(sf) as s:
            self.unit.addItems(catalog_service.list_units(s))
            self.unit.setCurrentText("item")  # stationery is counted in items unless the owner picks otherwise
            if product_id:
                p = s.get(Product, product_id)
                self.name.setText(p.product_name)
                self.category.setText(p.category)
                self.unit.setCurrentText(p.unit)
                self.purchase.setText(format_inr(p.purchase_price, symbol=False))
                self.selling.setText(format_inr(p.selling_price, symbol=False))
                self.minimum.setText(_fmt(p.minimum_stock))
                self.active.setChecked(p.is_active)
        form = QFormLayout()
        for key, w in (("inventory.name", self.name), ("catalog.category", self.category), ("catalog.unit", self.unit),
                       ("inventory.purchase_price", self.purchase), ("inventory.selling_price", self.selling),
                       ("inventory.minimum", self.minimum)):
            form.addRow(tr(key), w)
        if product_id:
            form.addRow(self.active)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(box)

    def _save(self) -> None:
        try:
            args = (self.name.text(), self.category.text(), self.unit.currentText(), parse_money(self.purchase.text()),
                    parse_money(self.selling.text()), parse_qty(self.minimum.text()))
            with session_scope(self._sf) as s:
                if self._id:
                    inventory_service.update_product(s, self._id, *args, self.active.isChecked())
                else:
                    inventory_service.create_product(s, *args)
        except DomainError as err:
            show_domain_error(self, err, self._tr)
            return
        self.accept()


class MovementDialog(QDialog):
    """Stock purchase / customer return / stock adjustment: one small form, three modes."""

    def __init__(self, parent, sf, tr, mode: str, row: inventory_service.StockRow) -> None:
        super().__init__(parent)
        self._sf, self._tr, self._mode, self._row = sf, tr, mode, row
        self.setWindowTitle(f"{tr('inventory.' + mode)} - {row.name}")
        self.qty = QLineEdit()
        self.cost = QLineEdit(format_inr(row.purchase_price, symbol=False))
        self.note = QLineEdit()
        form = QFormLayout()
        form.addRow(tr("inventory.current"), QLabel(f"{_fmt(row.stock)} {row.unit}"))
        form.addRow(tr("inventory.change_by" if mode == "adjust" else "bill.quantity"), self.qty)
        if mode == "purchase":
            form.addRow(tr("inventory.unit_cost"), self.cost)
        form.addRow(tr("bill.cancel_reason" if mode == "adjust" else "expense.notes"), self.note)
        if mode == "adjust":
            form.addRow(QLabel(tr("inventory.adjust_hint")))
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(box)

    def _save(self) -> None:
        try:
            qty = parse_qty(self.qty.text())
            with session_scope(self._sf) as s:
                if self._mode == "purchase":
                    inventory_service.purchase(s, self._row.id, qty, parse_money(self.cost.text()), self.note.text())
                elif self._mode == "return":
                    inventory_service.customer_return(s, self._row.id, qty, self.note.text())
                else:
                    self._adjust(s, qty)
        except DomainError as err:
            show_domain_error(self, err, self._tr)
            return
        self.accept()

    def _adjust(self, session, delta: Decimal) -> None:
        """Counts below zero are only possible after an explicit confirmation and the owner PIN."""
        if self._row.stock + delta < 0:
            ask = self._ask_negative()
            if ask is None:
                raise ValidationError("inventory.negative_blocked", name=self._row.name)
            inventory_service.adjust(session, self._row.id, delta, self.note.text(), True, ask[1])
        else:
            inventory_service.adjust(session, self._row.id, delta, self.note.text())

    def _ask_negative(self):
        from PySide6.QtWidgets import QMessageBox

        sure = QMessageBox.question(self, self._tr("inventory.adjust"),
                                    self._tr("inventory.negative_confirm", name=self._row.name))
        if sure != QMessageBox.StandardButton.Yes:
            return None
        proceed, pin = request_pin(self, self._sf, self._tr)
        return (True, pin) if proceed else None


class InventoryPage(Page):
    def __init__(self, session_factory, translator) -> None:
        super().__init__("nav.inventory", translator.tr)
        self._sf = session_factory
        self._rows: list[inventory_service.StockRow] = []
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.low_only = QCheckBox()
        bar.addWidget(self.search, 1)
        bar.addWidget(self.low_only)
        self.layout_.addLayout(bar)
        self.table = QTableWidget(0, 8)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.layout_.addWidget(self.table, 1)
        self.total = QLabel()
        self.total.setStyleSheet("font-weight: 700;")
        self.layout_.addWidget(self.total)
        buttons = QHBoxLayout()
        self.new_btn, self.edit_btn, self.buy_btn, self.ret_btn, self.adj_btn, self.hist_btn = (
            QPushButton() for _ in range(6))
        for b in (self.new_btn, self.edit_btn, self.buy_btn, self.ret_btn, self.adj_btn, self.hist_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        self.layout_.addLayout(buttons)
        self.search.textChanged.connect(lambda _t: self.reload())
        self.low_only.toggled.connect(lambda _c: self.reload())
        self.new_btn.clicked.connect(self._new)
        self.edit_btn.clicked.connect(self._edit)
        self.buy_btn.clicked.connect(lambda: self._move("purchase"))
        self.ret_btn.clicked.connect(lambda: self._move("return"))
        self.adj_btn.clicked.connect(lambda: self._move("adjust"))
        self.hist_btn.clicked.connect(self._history)
        self.table.itemSelectionChanged.connect(self._buttons)
        self.retranslate()

    def on_show(self) -> None:
        self.reload()

    def reload(self) -> None:
        with session_scope(self._sf) as s:
            self._rows = inventory_service.list_stock(s, self.search.text(), self.low_only.isChecked())
            value = inventory_service.stock_value(s)
        self.table.setRowCount(len(self._rows))
        for r, p in enumerate(self._rows):
            cells = [p.name, p.category, f"{_fmt(p.stock)} {p.unit}", _fmt(p.minimum), format_inr(p.purchase_price),
                     format_inr(p.selling_price), format_inr(p.value), self._tr("inventory.low") if p.low else ""]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c in (2, 3, 4, 5, 6):
                    item.setTextAlignment(RIGHT)
                if p.low:
                    item.setForeground(QColor("#B45309"))
                self.table.setItem(r, c, item)
        self.total.setText(f"{self._tr('inventory.total_value')}: {format_inr(value)}")
        self._buttons()

    def _selected(self) -> inventory_service.StockRow | None:
        row = self.table.currentRow()
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def _buttons(self) -> None:
        has = self._selected() is not None
        for b in (self.edit_btn, self.buy_btn, self.ret_btn, self.adj_btn, self.hist_btn):
            b.setEnabled(has)

    def _new(self) -> None:
        if ProductDialog(self, self._sf, self._tr).exec():
            self.reload()

    def _edit(self) -> None:
        if (p := self._selected()) and ProductDialog(self, self._sf, self._tr, p.id).exec():
            self.reload()

    def _move(self, mode: str) -> None:
        if (p := self._selected()) and MovementDialog(self, self._sf, self._tr, mode, p).exec():
            self.reload()

    def _history(self) -> None:
        p = self._selected()
        if p is None:
            return
        with session_scope(self._sf) as s:
            rows = inventory_service.history(s, p.id)
        t = self._tr
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{t('inventory.history')} - {p.name}")
        table = QTableWidget(len(rows), 4)
        table.setHorizontalHeaderLabels([t("history.col_date"), t("history.col_status"), t("bill.quantity"),
                                         t("expense.notes")])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for r, tx in enumerate(rows):
            y, m, d = tx.transaction_date.split("-")
            for c, text in enumerate((f"{d}-{m}-{y}", t(f"inventory.tx_{tx.transaction_type}"),
                                      f"{tx.quantity.normalize():+f}", tx.notes)):
                table.setItem(r, c, QTableWidgetItem(text))
        table.horizontalHeader().setStretchLastSection(True)
        layout = QVBoxLayout(dialog)
        layout.addWidget(table)
        dialog.resize(560, 360)
        dialog.exec()

    def retranslate(self) -> None:
        super().retranslate()
        t = self._tr
        self.search.setPlaceholderText(t("inventory.search"))
        self.low_only.setText(t("inventory.low_only"))
        self.new_btn.setText(amp(t("inventory.new")))
        self.edit_btn.setText(amp(t("inventory.edit")))
        self.buy_btn.setText(amp(t("inventory.purchase")))
        self.ret_btn.setText(amp(t("inventory.return")))
        self.adj_btn.setText(amp(t("inventory.adjust")))
        self.hist_btn.setText(amp(t("inventory.history")))
        self.table.setHorizontalHeaderLabels([t(k) for k in (
            "inventory.name", "catalog.category", "inventory.stock", "inventory.minimum", "inventory.purchase_price",
            "inventory.selling_price", "inventory.value", "history.col_status")])
        self.reload()
