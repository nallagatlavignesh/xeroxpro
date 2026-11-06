from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from application.services import catalog_service, expense_service
from business.billing import PAYMENT_METHODS
from business.errors import DomainError
from business.money import format_inr
from business.timeutil import ist_today
from database.connection import session_scope
from database.models import Expense
from ui.page import Page, amp, parse_money, show_domain_error


def _qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


class ExpenseDialog(QDialog):
    def __init__(self, parent, sf, tr, expense: Expense | None = None) -> None:
        super().__init__(parent)
        self._sf, self._tr, self._id = sf, tr, expense.id if expense else None
        self.setWindowTitle(tr("expense.edit" if expense else "expense.add"))
        with session_scope(sf) as s:
            categories = catalog_service.list_lookup(s, "expense_category")
        self.category = QComboBox()
        self.category.setEditable(True)
        self.category.addItems(categories)
        self.description, self.notes, self.amount = QLineEdit(), QLineEdit(), QLineEdit()
        self.method = QComboBox()
        for m in PAYMENT_METHODS:
            self.method.addItem(tr(f"pay.{m}"), m)
        self.when = QDateEdit(_qdate(ist_today()))
        self.when.setCalendarPopup(True)
        self.when.setDisplayFormat("dd-MM-yyyy")
        self.when.setMaximumDate(_qdate(ist_today()))
        self.hint = QLabel()
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        if expense:
            self.category.setCurrentText(expense.category)
            self.description.setText(expense.description)
            self.amount.setText(format_inr(expense.amount, symbol=False))
            self.method.setCurrentIndex(PAYMENT_METHODS.index(expense.payment_method))
            self.when.setDate(_qdate(date.fromisoformat(expense.expense_date)))
            self.notes.setText(expense.notes)
        form = QFormLayout()
        for key, w in (("expense.category", self.category), ("expense.description", self.description),
                       ("expense.amount", self.amount), ("payment.method", self.method),
                       ("expense.date", self.when), ("expense.notes", self.notes)):
            form.addRow(tr(key), w)
        form.addRow(self.hint)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(box)
        self.category.currentTextChanged.connect(self._hint)
        self._hint()

    def _hint(self, *_a) -> None:
        stock = self.category.currentText().strip() == expense_service.STOCK_CATEGORY
        self.hint.setText(self._tr("expense.stock_hint") if stock else "")

    def _save(self) -> None:
        try:
            args = (self.category.currentText(), self.description.text(), parse_money(self.amount.text()),
                    self.method.currentData(), self.when.date().toPython().isoformat(), self.notes.text())
            with session_scope(self._sf) as s:
                if self._id:
                    expense_service.edit_expense(s, self._id, *args)
                else:
                    expense_service.add_expense(s, *args)
        except DomainError as err:
            show_domain_error(self, err, self._tr)
            return
        self.accept()


class ExpensesPage(Page):
    def __init__(self, session_factory, translator) -> None:
        super().__init__("nav.expenses", translator.tr)
        self._sf = session_factory
        self._rows: list[Expense] = []
        today = ist_today()
        bar = QHBoxLayout()
        self.from_l, self.to_l, self.cat_l = QLabel(), QLabel(), QLabel()
        self.from_d, self.to_d = QDateEdit(_qdate(today.replace(day=1))), QDateEdit(_qdate(today))
        for d in (self.from_d, self.to_d):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd-MM-yyyy")
        self.category = QComboBox()
        for w in (self.from_l, self.from_d, self.to_l, self.to_d, self.cat_l, self.category):
            bar.addWidget(w)
        bar.addStretch(1)
        self.add_btn, self.edit_btn, self.void_btn = QPushButton(), QPushButton(), QPushButton()
        for b in (self.add_btn, self.edit_btn, self.void_btn):
            bar.addWidget(b)
        self.layout_.addLayout(bar)
        self.table = QTableWidget(0, 6)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.layout_.addWidget(self.table, 1)
        self.total = QLabel()
        self.total.setStyleSheet("font-weight: 700; font-size: 16px;")
        self.by_category = QLabel()
        self.by_category.setObjectName("hint")
        self.by_category.setWordWrap(True)
        self.layout_.addWidget(self.total)
        self.layout_.addWidget(self.by_category)

        for w in (self.from_d, self.to_d):
            w.dateChanged.connect(lambda _d: self.reload())
        self.category.activated.connect(lambda _i: self.reload())
        self.add_btn.clicked.connect(self.add)
        self.edit_btn.clicked.connect(self._edit)
        self.void_btn.clicked.connect(self._void)
        self.table.itemSelectionChanged.connect(self._buttons)
        self.retranslate()

    def on_show(self) -> None:
        self.reload()

    def _range(self) -> tuple[date, date]:
        return self.from_d.date().toPython(), self.to_d.date().toPython()

    def reload(self) -> None:
        start, end = self._range()
        with session_scope(self._sf) as s:
            self._rows = expense_service.list_expenses(s, start, end, self.category.currentData())
            by_cat = expense_service.totals_by_category(s, start, end)
            if self.category.currentData():
                by_cat = {k: v for k, v in by_cat.items() if k == self.category.currentData()}
        self.table.setRowCount(len(self._rows))
        t = self._tr
        for r, e in enumerate(self._rows):
            y, m, d = e.expense_date.split("-")
            cells = [f"{d}-{m}-{y}", e.category, e.description, t(f"pay.{e.payment_method}"),
                     format_inr(e.amount), t("expense.voided") if e.is_voided else ""]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 4:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if e.is_voided:
                    item.setForeground(QColor("#9CA3AF"))
                    font = item.font()
                    font.setStrikeOut(True)
                    item.setFont(font)
                self.table.setItem(r, c, item)
        self.total.setText(f"{t('expense.total')}: {format_inr(sum(by_cat.values()))}")
        self.by_category.setText("  ·  ".join(f"{c}: {format_inr(v)}" for c, v in sorted(by_cat.items())))
        self._buttons()

    def _selected(self) -> Expense | None:
        row = self.table.currentRow()
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def _buttons(self) -> None:
        e = self._selected()
        usable = e is not None and not e.is_voided
        self.edit_btn.setEnabled(usable)
        self.void_btn.setEnabled(usable)

    def add(self) -> None:
        if ExpenseDialog(self, self._sf, self._tr).exec():
            self.reload()

    def _edit(self) -> None:
        if (e := self._selected()) and ExpenseDialog(self, self._sf, self._tr, e).exec():
            self.reload()

    def _void(self) -> None:
        e = self._selected()
        if e is None:
            return
        reason, ok = QInputDialog.getText(self, self._tr("expense.void"), self._tr("bill.cancel_reason"))
        if not ok:
            return
        try:
            with session_scope(self._sf) as s:
                expense_service.void_expense(s, e.id, reason)
        except DomainError as err:
            show_domain_error(self, err, self._tr)
            return
        self.reload()

    def retranslate(self) -> None:
        super().retranslate()
        t = self._tr
        self.from_l.setText(t("history.from"))
        self.to_l.setText(t("history.to"))
        self.cat_l.setText(t("expense.category"))
        self.add_btn.setText(amp(t("expense.add")))
        self.edit_btn.setText(amp(t("expense.edit")))
        self.void_btn.setText(amp(t("expense.void")))
        self.table.setHorizontalHeaderLabels([t(k) for k in (
            "expense.date", "expense.category", "expense.description", "expense.method", "expense.amount",
            "history.col_status")])
        with session_scope(self._sf) as s:
            cats = catalog_service.list_lookup(s, "expense_category")
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem(t("history.all"), None)
        for c in cats:
            self.category.addItem(c, c)
        self.category.blockSignals(False)
        self.reload()
