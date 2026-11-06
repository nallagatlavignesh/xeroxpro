"""New Bill screen. It only collects input and shows results: every number comes from business.billing."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from application.services import auth_service, catalog_service, customer_service, settings_service
from application.use_cases.save_bill import BillRequest, LineRequest, save_bill
from business.billing import LineInput, PaymentInput, compute_totals, discount_from_percent
from business.errors import DomainError, ValidationError
from business.money import format_inr, to_paise
from database.connection import session_scope
from ui.customers.customer_dialog import CustomerDialog
from ui.page import amp, message_for, parse_money, request_pin, show_domain_error

METHODS = ("cash", "upi", "other")


@dataclass
class Draft:
    name: str
    unit: str
    quantity: Decimal
    copies: int
    rate: int
    service_id: int | None = None
    product_id: int | None = None
    override: bool = False
    details: dict | None = None

    def line_input(self) -> LineInput:
        return LineInput(self.quantity, self.rate, self.copies)


_money = parse_money


class NewBillWidget(QWidget):
    bill_saved = Signal(int, bool)  # bill id, open receipt?

    def __init__(self, session_factory, tr) -> None:
        super().__init__()
        self._sf, self._tr = session_factory, tr
        self._drafts: list[Draft] = []
        self._key = str(uuid.uuid4())
        self._pin: str | None = None
        self._saving = False
        self._labels: dict[str, QLabel] = {}
        root = QVBoxLayout(self)

        # --- add-a-line row
        grid = QGridLayout()
        self.item = QComboBox()
        self.qty = QLineEdit("1")
        self.copies = QSpinBox()
        self.copies.setRange(1, 99999)
        self.unit = QComboBox()
        self.rate = QLineEdit()
        self.rate.setReadOnly(True)
        self.change_rate = QCheckBox()
        self.add_btn = QPushButton()
        self._labels["bill.service"] = QLabel()
        grid.addWidget(self._labels["bill.service"], 0, 0, 1, 6)
        grid.addWidget(self.item, 1, 0, 1, 6)  # full width: service names can be long
        for col, (key, widget) in enumerate((("bill.quantity", self.qty), ("bill.copies", self.copies),
                                             ("bill.unit", self.unit), ("bill.rate", self.rate))):
            self._labels[key] = QLabel()
            grid.addWidget(self._labels[key], 2, col)
            grid.addWidget(widget, 3, col)
        grid.addWidget(self.change_rate, 2, 4)
        grid.addWidget(self.add_btn, 3, 4, 1, 2)
        grid.setColumnStretch(3, 1)
        self.hint = QLabel()
        self.hint.setObjectName("statusError")

        body = QHBoxLayout()
        root.addLayout(body, 1)

        # --- lines table
        left = QVBoxLayout()
        left.addLayout(grid)
        left.addWidget(self.hint)
        self.table = QTableWidget(0, 5)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, width in zip(range(1, 5), (60, 70, 90, 100)):
            self.table.setColumnWidth(col, width)
        self.table.verticalHeader().setVisible(False)
        self.remove_btn = QPushButton()
        left.addWidget(self.table, 1)
        left.addWidget(self.remove_btn, 0, Qt.AlignmentFlag.AlignLeft)
        body.addLayout(left, 3)

        # --- totals + payment
        side = QFrame()
        form = QFormLayout(side)
        self.customer = QComboBox()
        self.new_customer_btn = QPushButton()
        crow = QHBoxLayout()
        crow.addWidget(self.customer, 1)
        crow.addWidget(self.new_customer_btn)
        self.discount = QLineEdit()
        self.discount_kind = QComboBox()
        self.discount_kind.addItems(["₹", "%"])
        drow = QHBoxLayout()
        drow.addWidget(self.discount, 1)
        drow.addWidget(self.discount_kind)
        self.subtotal_l, self.total_l, self.paid_l, self.due_l = QLabel(), QLabel(), QLabel(), QLabel()
        self.total_l.setStyleSheet("font-size: 22px; font-weight: 700; color: #0F766E;")
        self.pay: dict[str, QLineEdit] = {m: QLineEdit() for m in METHODS}
        self.upi_ref = QLineEdit()
        self.pay_full_btn = QPushButton()
        self.notes = QLineEdit()
        for key, field in (("bill.customer", crow), ("bill.discount", drow), ("bill.subtotal", self.subtotal_l),
                           ("bill.grand_total", self.total_l)):
            self._labels[key] = QLabel()
            form.addRow(self._labels[key], field)
        pay_grid = QGridLayout()  # cash | UPI | other side by side to save height
        for col, m in enumerate(METHODS):
            self._labels[f"pay.{m}"] = QLabel()
            pay_grid.addWidget(self._labels[f"pay.{m}"], 0, col)
            pay_grid.addWidget(self.pay[m], 1, col)
        form.addRow(pay_grid)
        self._labels["bill.upi_ref"] = QLabel()
        form.addRow(self._labels["bill.upi_ref"], self.upi_ref)
        form.addRow(self.pay_full_btn)
        for key, field in (("bill.paid_total", self.paid_l), ("bill.outstanding", self.due_l),
                           ("bill.notes", self.notes)):
            self._labels[key] = QLabel()
            form.addRow(self._labels[key], field)
        self.status = QLabel()
        self.status.setWordWrap(True)
        form.addRow(self.status)
        self.save_btn, self.save_view_btn, self.clear_btn = QPushButton(), QPushButton(), QPushButton()
        form.addRow(self.save_view_btn)
        small = QHBoxLayout()
        small.addWidget(self.save_btn, 1)
        small.addWidget(self.clear_btn)
        form.addRow(small)
        scroll = QScrollArea()  # never squash the form on a 768px-high screen: scroll instead
        scroll.setWidget(side)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedWidth(530)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.addWidget(scroll, 0)

        self.item.currentIndexChanged.connect(self._on_item_changed)
        self.change_rate.toggled.connect(self._on_change_rate)
        self.add_btn.clicked.connect(self._add_line)
        self.remove_btn.clicked.connect(self._remove_line)
        self.new_customer_btn.clicked.connect(self._new_customer)
        self.pay_full_btn.clicked.connect(self._pay_full)
        self.save_btn.clicked.connect(lambda: self._save(False))
        self.save_view_btn.clicked.connect(lambda: self._save(True))
        self.clear_btn.clicked.connect(self.reset)
        for w in (self.discount, *self.pay.values(), self.upi_ref, self.customer):
            (w.textChanged if isinstance(w, QLineEdit) else w.currentIndexChanged).connect(lambda *_: self._refresh())
        self.discount_kind.currentIndexChanged.connect(lambda *_: self._refresh())
        self.retranslate()
        self.reload_catalog()

    # ---- catalogue / customers -------------------------------------------------------------
    def reload_catalog(self) -> None:
        with session_scope(self._sf) as s:
            services = catalog_service.list_services(s, active_only=True)
            products = catalog_service.list_sellable_products(s)
            self._units = catalog_service.list_units(s)
            customers = customer_service.search_customers(s, limit=500)
        self.item.blockSignals(True)
        self.item.clear()
        for r in services:
            if r.kind != "stationery":  # stationery is sold as products
                self.item.addItem(r.name, ("service", r.id, r.unit, r.rate))
        for pid, name, price, unit in products:
            self.item.addItem(f"{self._tr('nav.inventory')}: {name}", ("product", pid, unit, price, name))
        self.item.blockSignals(False)
        self._load_customers([(c.id, c.customer_name, c.phone) for c in customers])
        self._on_item_changed()

    def _load_customers(self, rows, select_id: int | None = None) -> None:
        current = select_id if select_id is not None else self.customer.currentData()
        self.customer.blockSignals(True)
        self.customer.clear()
        self.customer.addItem(self._tr("bill.walk_in"), None)
        for cid, name, phone in rows:
            self.customer.addItem(f"{name} ({phone})" if phone else name, cid)
        index = self.customer.findData(current)
        self.customer.setCurrentIndex(max(index, 0))
        self.customer.blockSignals(False)
        self._refresh()

    def _new_customer(self) -> None:
        dialog = CustomerDialog(self, self._sf, self._tr)
        if dialog.exec():
            with session_scope(self._sf) as s:
                rows = [(c.id, c.customer_name, c.phone) for c in customer_service.search_customers(s, limit=500)]
            self._load_customers(rows, dialog.customer_id)

    # ---- add-line row ----------------------------------------------------------------------
    def _on_item_changed(self, *_args) -> None:
        data = self.item.currentData()
        self.change_rate.setChecked(False)
        self._pin = None
        self.unit.clear()
        self.unit.addItems(self._units)
        if data is None:
            self.rate.clear()
            self.hint.clear()
            return
        index = self.unit.findText(data[2])
        if index < 0:
            self.unit.addItem(data[2])
            index = self.unit.count() - 1
        self.unit.setCurrentIndex(index)
        rate = data[3]
        self.rate.setText("" if rate is None else format_inr(rate, symbol=False))
        self.hint.setText(self._tr("bill.no_rate_hint") if rate is None else "")

    def _on_change_rate(self, checked: bool) -> None:
        if not checked:
            self.rate.setReadOnly(True)
            self._on_item_changed_rate_only()
            return
        proceed, pin = request_pin(self, self._sf, self._tr)
        if proceed:
            with session_scope(self._sf) as s:
                proceed = auth_service.verify_pin(s, pin)
            if not proceed:
                self.status.setObjectName("statusError")
                self.status.setText(self._tr("auth.pin_wrong"))
        if not proceed:
            self.change_rate.blockSignals(True)
            self.change_rate.setChecked(False)
            self.change_rate.blockSignals(False)
            return
        self._pin = pin
        self.rate.setReadOnly(False)

    def _on_item_changed_rate_only(self) -> None:
        data = self.item.currentData()
        if data and data[3] is not None:
            self.rate.setText(format_inr(data[3], symbol=False))

    def _add_line(self) -> None:
        data = self.item.currentData()
        try:
            if data is None:
                raise ValidationError("bill.line_subject")
            try:
                quantity = Decimal(self.qty.text().strip())
            except InvalidOperation:
                raise ValidationError("bill.quantity_positive") from None
            rate = _money(self.rate.text())
            if not self.rate.text().strip():
                raise ValidationError("bill.no_rate", name=self.item.currentText())
            name = data[4] if data[0] == "product" else self.item.currentText()
            draft = Draft(name, self.unit.currentText(), quantity, self.copies.value(), rate,
                          service_id=data[1] if data[0] == "service" else None,
                          product_id=data[1] if data[0] == "product" else None,
                          override=rate != data[3])
            from business.billing import validate_line
            validate_line(draft.line_input())
        except DomainError as err:
            show_domain_error(self, err, self._tr)
            return
        self._drafts.append(draft)
        self.qty.setText("1")
        self.copies.setValue(1)
        self._redraw_table()
        self._refresh()

    def add_service_line(self, service_id: int, quantity: Decimal, copies: int = 1, details: dict | None = None,
                         rate: int | None = None) -> bool:
        """Add a line from another screen (PDF assistant, applications). A rate different from the list rate is an
        override, so the owner PIN is asked when the bill is saved. Returns False if the service is not billable."""
        for i in range(self.item.count()):
            data = self.item.itemData(i)
            if data and data[0] == "service" and data[1] == service_id:
                break
        else:
            return False
        list_rate = data[3]
        charged = list_rate if rate is None else rate
        if charged is None:
            show_domain_error(self, ValidationError("bill.no_rate", name=self.item.itemText(i)), self._tr)
            return False
        self._drafts.append(Draft(self.item.itemText(i), data[2], quantity, copies, charged, service_id=service_id,
                                  override=charged != list_rate, details=details))
        self._redraw_table()
        self._refresh()
        return True

    def _remove_line(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            del self._drafts[r]
        self._redraw_table()
        self._refresh()

    def _redraw_table(self) -> None:
        self.table.setRowCount(len(self._drafts))
        for r, d in enumerate(self._drafts):
            li = d.line_input()
            cells = [d.name, f"{li.effective_quantity.normalize():f}", self._unit_text(d.unit),
                     format_inr(d.rate), format_inr(li.amount)]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c >= 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, c, item)

    def _unit_text(self, unit: str) -> str:
        text = self._tr(f"unit.{unit}")
        return unit if text == f"unit.{unit}" else text

    # ---- totals ----------------------------------------------------------------------------
    def _discount_paise(self, subtotal: int) -> int:
        text = self.discount.text().strip()
        if not text:
            return 0
        if self.discount_kind.currentText() == "%":
            try:
                return discount_from_percent(subtotal, Decimal(text))
            except InvalidOperation:
                raise ValidationError("bill.discount_invalid") from None
        return _money(text)

    def _payments(self) -> list[PaymentInput]:
        out = []
        for m in METHODS:
            amount = _money(self.pay[m].text())
            if amount:
                out.append(PaymentInput(amount, m, self.upi_ref.text() if m == "upi" else None))
        return out

    def _refresh(self) -> None:
        """Recompute everything through business.billing; show the first problem instead of crashing."""
        lines = [d.line_input() for d in self._drafts]
        subtotal = sum(l.amount for l in lines)
        self.subtotal_l.setText(format_inr(subtotal))
        self.status.setObjectName("status")
        self.status.setText("")
        try:
            totals = compute_totals(lines, self._discount_paise(subtotal), self._payments()) if lines else None
        except DomainError as err:
            self.total_l.setText(format_inr(subtotal))
            self.paid_l.setText("")
            self.due_l.setText("")
            self.status.setObjectName("statusError")
            self.status.setText(message_for(err, self._tr))
            self._totals = None
        else:
            self._totals = totals
            self.total_l.setText(format_inr(totals.grand_total) if totals else format_inr(0))
            self.paid_l.setText(format_inr(totals.total_paid) if totals else "")
            self.due_l.setText(format_inr(totals.outstanding) if totals else "")
            if totals and totals.outstanding > 0 and self.customer.currentData() is None:
                self.status.setObjectName("statusError")
                self.status.setText(self._tr("bill.credit_needs_customer"))
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.save_btn.setEnabled(bool(self._totals) and not self._saving)
        self.save_view_btn.setEnabled(bool(self._totals) and not self._saving)

    def _pay_full(self) -> None:
        if not self._totals:
            return
        with session_scope(self._sf) as s:
            method = settings_service.get_shop_settings(s).default_payment_method
        for m in METHODS:
            self.pay[m].setText("")
        self.pay[method].setText(format_inr(self._totals.grand_total, symbol=False))

    # ---- save ------------------------------------------------------------------------------
    def _request(self) -> BillRequest:
        return BillRequest(
            idempotency_key=self._key,
            lines=[LineRequest(d.quantity, d.unit, d.rate, d.copies, d.service_id, d.product_id, d.override, d.details or {})
                   for d in self._drafts],
            payments=self._payments(), customer_id=self.customer.currentData(),
            discount=self._discount_paise(sum(d.line_input().amount for d in self._drafts)),
            notes=self.notes.text(), pin=self._pin)

    def _save(self, view_receipt: bool) -> None:
        if self._saving:  # a second click while saving must not create a second bill
            return
        self._saving = True
        self.save_btn.setEnabled(False)
        self.save_view_btn.setEnabled(False)
        try:
            request = self._request()
            if any(d.override for d in self._drafts) and self._pin is None:
                proceed, pin = request_pin(self, self._sf, self._tr)
                if not proceed:
                    return
                request = BillRequest(**{**request.__dict__, "pin": pin})
            with session_scope(self._sf) as s:
                saved = save_bill(s, request)
        except DomainError as err:
            show_domain_error(self, err, self._tr)
            return
        finally:
            self._saving = False
            self._refresh()
        self.reset()
        self.status.setObjectName("status")
        self.status.setText(self._tr("bill.saved", number=saved.bill_number))
        self.bill_saved.emit(saved.bill_id, view_receipt)

    def reset(self) -> None:
        """Start a fresh bill (new idempotency key)."""
        self._key = str(uuid.uuid4())
        self._drafts.clear()
        self._pin = None
        self.change_rate.setChecked(False)
        for w in (self.discount, self.upi_ref, self.notes, *self.pay.values()):
            w.clear()
        self.customer.setCurrentIndex(0)
        self._redraw_table()
        self._refresh()

    def retranslate(self) -> None:
        t = self._tr
        for key, label in self._labels.items():
            label.setText(t(key))
        self.change_rate.setText(t("bill.change_rate"))
        self.add_btn.setText(amp(t("bill.add_line")))
        self.remove_btn.setText(amp(t("bill.remove_line")))
        self.new_customer_btn.setText(amp(t("bill.new_customer")))
        self.pay_full_btn.setText(amp(t("bill.pay_full")))
        self.save_btn.setText(amp(t("bill.save")))
        self.save_view_btn.setText(amp(t("bill.save_print")))
        self.clear_btn.setText(amp(t("bill.clear")))
        self.table.setHorizontalHeaderLabels([t(k) for k in (
            "bill.col_item", "bill.col_qty", "bill.col_unit", "bill.col_rate", "bill.col_amount")])
        if hasattr(self, "_units"):
            self.reload_catalog()
            self._redraw_table()
