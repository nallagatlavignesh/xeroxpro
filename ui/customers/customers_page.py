from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from application.services import bill_queries, customer_service
from business.money import format_inr
from database.connection import session_scope
from ui.customers.customer_dialog import CustomerDialog
from ui.customers.payment_dialog import PaymentDialog
from ui.page import Page, amp

RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def _table(columns: int, stretch: int = 0) -> QTableWidget:
    t = QTableWidget(0, columns)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
    return t


def _fill(table: QTableWidget, rows: list[list[str]], right_cols: tuple[int, ...] = ()) -> None:
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            item = QTableWidgetItem(text)
            if c in right_cols:
                item.setTextAlignment(RIGHT)
            table.setItem(r, c, item)


def _dmy(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}-{m}-{y}"


class CustomersPage(Page):
    def __init__(self, session_factory, translator) -> None:
        super().__init__("nav.customers", translator.tr)
        self._sf = session_factory
        self._rows: list = []
        self._bill_ids: list[int] = []

        split = QSplitter()
        self.layout_.addWidget(split, 1)
        # --- left: customer list / outstanding report
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 8, 0)
        self.search = QLineEdit()
        self.only_owing = QCheckBox()
        self.table = _table(3, 0)
        self.total = QLabel()
        self.total.setStyleSheet("font-weight: 700;")
        bar = QHBoxLayout()
        self.new_btn, self.edit_btn = QPushButton(), QPushButton()
        bar.addWidget(self.new_btn)
        bar.addWidget(self.edit_btn)
        bar.addStretch(1)
        for w in (self.search, self.only_owing, self.table, self.total):
            lv.addWidget(w)
        lv.addLayout(bar)
        split.addWidget(left)
        # --- right: selected customer
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 0, 0, 0)
        self.header = QLabel()
        self.header.setStyleSheet("font-size: 18px; font-weight: 700;")
        self.balance = QLabel()
        self.balance.setStyleSheet("font-size: 20px; font-weight: 700; color: #B45309;")
        self.pay_btn = QPushButton()
        self.pay_bill_btn = QPushButton()
        head = QHBoxLayout()
        head.addWidget(self.header, 1)
        head.addWidget(self.pay_btn)
        head.addWidget(self.pay_bill_btn)
        self.tabs = QTabWidget()
        self.ledger_t, self.bills_t, self.pay_t = _table(6, 2), _table(5, 0), _table(5, 1)
        for t in (self.ledger_t, self.bills_t, self.pay_t):
            self.tabs.addTab(t, "")
        rv.addLayout(head)
        rv.addWidget(self.balance)
        rv.addWidget(self.tabs, 1)
        split.addWidget(right)
        split.setSizes([420, 700])

        self.search.textChanged.connect(lambda _t: self.reload())
        self.only_owing.toggled.connect(lambda _c: self.reload())
        self.table.itemSelectionChanged.connect(self._show_detail)
        self.new_btn.clicked.connect(self._new)
        self.edit_btn.clicked.connect(self._edit)
        self.pay_btn.clicked.connect(lambda: self._receive(None))
        self.pay_bill_btn.clicked.connect(self._receive_for_bill)
        self.retranslate()

    # ---- data ------------------------------------------------------------------------------
    def on_show(self) -> None:
        self.reload()

    def reload(self, select_id: int | None = None) -> None:
        keep = select_id or self._selected_id()
        with session_scope(self._sf) as s:
            self._rows = customer_service.list_with_balances(s, self.search.text(), self.only_owing.isChecked())
            total = customer_service.total_outstanding(s)
        _fill(self.table, [[c.name, c.phone, format_inr(c.balance)] for c in self._rows], (2,))
        self.total.setText(f"{self._tr('customers.total_due')}: {format_inr(total)}")
        for r, c in enumerate(self._rows):
            if c.id == keep:
                self.table.selectRow(r)
        self._show_detail()

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        return self._rows[row].id if 0 <= row < len(self._rows) else None

    def _show_detail(self) -> None:
        cid = self._selected_id()
        has = cid is not None
        for b in (self.edit_btn, self.pay_btn, self.pay_bill_btn):
            b.setEnabled(has)
        if not has:
            self.header.clear()
            self.balance.clear()
            for t in (self.ledger_t, self.bills_t, self.pay_t):
                t.setRowCount(0)
            return
        t = self._tr
        with session_scope(self._sf) as s:
            row = next(c for c in self._rows if c.id == cid)
            ledger = customer_service.ledger(s, cid)
            pays = customer_service.payment_history(s, cid)
            bills = bill_queries.customer_bills(s, cid)
        self.header.setText(f"{row.name}  {row.phone}")
        self.balance.setText(f"{t('customers.balance')}: {format_inr(row.balance)}")
        _fill(self.ledger_t, [[_dmy(e.date), t(f"ledger.{e.type}"), self._detail(e.detail),
                               format_inr(e.debit) if e.debit else "", format_inr(e.credit) if e.credit else "",
                               format_inr(e.balance)] for e in reversed(ledger)], (3, 4, 5))  # newest first
        self._bill_ids = [b.id for b in bills]
        _fill(self.bills_t, [[b.bill_number, _dmy(b.bill_date), format_inr(b.grand_total), format_inr(b.outstanding),
                              t(f"status.{b.status}")] for b in bills], (2, 3))
        _fill(self.pay_t, [[_dmy(d), n, t(f"pay.{m}"), format_inr(a), t("payment.refund" if k == "refund" else "payment.received")]
                           for d, n, m, a, k in pays], (3,))

    def _detail(self, raw: str) -> str:
        number, method = raw.split("|")
        return f"{number} · {self._tr('pay.' + method)}" if method else number

    # ---- actions ---------------------------------------------------------------------------
    def _new(self) -> None:
        dialog = CustomerDialog(self, self._sf, self._tr)
        if dialog.exec():
            self.reload(dialog.customer_id)

    def _edit(self) -> None:
        if (cid := self._selected_id()) is not None and CustomerDialog(self, self._sf, self._tr, cid).exec():
            self.reload(cid)

    def _receive(self, bill_id: int | None) -> None:
        if (cid := self._selected_id()) is not None and PaymentDialog(self, self._sf, self._tr, cid, bill_id).exec():
            self.reload(cid)

    def _receive_for_bill(self) -> None:
        row = self.bills_t.currentRow()
        if 0 <= row < len(self._bill_ids):
            self._receive(self._bill_ids[row])

    def retranslate(self) -> None:
        super().retranslate()
        t = self._tr
        self.search.setPlaceholderText(t("customers.search"))
        self.only_owing.setText(t("customers.only_owing"))
        self.table.setHorizontalHeaderLabels([t("customer.name"), t("customer.phone"), t("customers.col_due")])
        self.new_btn.setText(amp(t("bill.new_customer")))
        self.edit_btn.setText(amp(t("customers.edit")))
        self.pay_btn.setText(amp(t("customers.receive")))
        self.pay_bill_btn.setText(amp(t("customers.receive_bill")))
        for i, k in enumerate(("customers.tab_ledger", "customers.tab_bills", "customers.tab_payments")):
            self.tabs.setTabText(i, amp(t(k)))
        self.bills_t.setHorizontalHeaderLabels([t(k) for k in (
            "history.col_number", "history.col_date", "history.col_total", "history.col_due", "history.col_status")])
        self.ledger_t.setHorizontalHeaderLabels([t(k) for k in (
            "ledger.col_date", "ledger.col_type", "ledger.col_desc", "ledger.col_debit", "ledger.col_credit",
            "ledger.col_balance")])
        self.pay_t.setHorizontalHeaderLabels([t(k) for k in (
            "history.col_date", "history.col_number", "expense.method", "payment.amount", "history.col_status")])
        self.reload()
