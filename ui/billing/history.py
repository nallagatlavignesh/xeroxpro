from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from application.services import bill_queries
from business.money import format_inr
from database.connection import session_scope

STATUSES = ("unpaid", "partial", "paid", "cancelled", "refunded")


class HistoryWidget(QWidget):
    def __init__(self, session_factory, tr, open_receipt) -> None:
        super().__init__()
        self._sf, self._tr, self._open = session_factory, tr, open_receipt
        self._ids: list[int] = []
        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.use_dates = QComboBox()  # "All dates" / "Date range" keeps the common case (everything) one click
        self.from_date, self.to_date = QDateEdit(QDate.currentDate()), QDateEdit(QDate.currentDate())
        for d in (self.from_date, self.to_date):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd-MM-yyyy")
        self.status = QComboBox()
        self.from_l, self.to_l, self.status_l = QLabel(), QLabel(), QLabel()
        self.find_btn, self.open_btn = QPushButton(), QPushButton()
        for w in (self.search, self.use_dates, self.from_l, self.from_date, self.to_l, self.to_date,
                  self.status_l, self.status, self.find_btn):
            bar.addWidget(w, 1 if w is self.search else 0)
        root.addLayout(bar)
        self.table = QTableWidget(0, 7)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)
        self.empty = QLabel()
        self.empty.setObjectName("hint")
        root.addWidget(self.empty)
        root.addWidget(self.open_btn, 0, Qt.AlignmentFlag.AlignLeft)

        self.find_btn.clicked.connect(self.refresh)
        self.search.returnPressed.connect(self.refresh)
        self.status.activated.connect(lambda _i: self.refresh())
        self.use_dates.activated.connect(lambda _i: self.refresh())
        self.open_btn.clicked.connect(self._open_selected)
        self.table.doubleClicked.connect(lambda _i: self._open_selected())
        self.retranslate()

    def retranslate(self) -> None:
        t = self._tr
        self.search.setPlaceholderText(t("history.search"))
        self.from_l.setText(t("history.from"))
        self.to_l.setText(t("history.to"))
        self.status_l.setText(t("history.status"))
        self.find_btn.setText(t("common.search"))
        self.open_btn.setText(t("history.open"))
        self.use_dates.clear()
        self.use_dates.addItems([t("history.all"), t("history.from") + "…"])
        self.status.clear()
        self.status.addItem(t("history.all"), None)
        for s in STATUSES:
            self.status.addItem(t(f"status.{s}"), s)
        self.table.setHorizontalHeaderLabels([t(f"history.col_{k}") for k in
                                              ("number", "date", "customer", "total", "paid", "due", "status")])
        self.refresh()

    def refresh(self) -> None:
        ranged = self.use_dates.currentIndex() == 1
        with session_scope(self._sf) as s:
            rows = bill_queries.search_bills(
                s, self.search.text(),
                self.from_date.date().toPython() if ranged else None,
                self.to_date.date().toPython() if ranged else None, self.status.currentData())
        self._ids = [r.id for r in rows]
        self.table.setRowCount(len(rows))
        for r, b in enumerate(rows):
            y, m, d = b.bill_date.split("-")
            cells = [b.bill_number, f"{d}-{m}-{y}", b.customer_name or self._tr("bill.walk_in"),
                     format_inr(b.grand_total), format_inr(b.total_paid), format_inr(b.outstanding),
                     self._tr(f"status.{b.status}")]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c in (3, 4, 5):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, c, item)
        self.empty.setText("" if rows else self._tr("history.none"))

    def _open_selected(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self._ids):
            self._open(self._ids[row])
