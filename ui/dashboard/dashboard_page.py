"""Dashboard. Sales, money received, credit outstanding, expenses and cash movement are separate cards on purpose."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QPushButton, QScrollArea,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from application.services import accounting_queries as aq
from application.services import backup_service
from business.money import format_inr
from business.timeutil import ist_today, to_ist
from database.connection import session_scope
from ui.dashboard.closing_dialog import ClosingDialog
from ui.page import Page, amp
from ui.widgets.bar_chart import BarChart

CARDS = [  # key, title key
    ("sales", "dash.sales"), ("bills", "dash.bills"), ("collected", "dash.collected"), ("credit", "dash.credit"),
    ("cash", "pay.cash"), ("upi", "pay.upi"), ("other", "pay.other"), ("expenses", "dash.expenses"),
    ("movement", "dash.cash_movement"), ("jobs", "dash.jobs"), ("low", "dash.low_stock"),
]


class Card(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("card")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 10)
        self.title, self.value = QLabel(), QLabel()
        self.title.setObjectName("hint")
        self.value.setStyleSheet("font-size: 22px; font-weight: 700;")  # colour comes from the 'tone' property
        v.addWidget(self.title)
        v.addWidget(self.value)
        self.set_value("", "")

    def set_value(self, text: str, tone: str) -> None:
        """tone: '' (teal), 'warn' (amber: money owed to us) or 'bad' (red: negative)."""
        self.value.setText(text)
        self.value.setProperty("tone", tone)
        self.value.setStyleSheet(f"font-size: 22px; font-weight: 700; color: "
                                 f"{ {'warn': '#B45309', 'bad': '#B91C1C'}.get(tone, '#0F766E') };")


class DashboardPage(Page):
    navigate = Signal(str)  # sidebar key
    quick_action = Signal(str)  # "add_expense"

    def __init__(self, session_factory, translator) -> None:
        super().__init__("nav.dashboard", translator.tr)
        self._sf = session_factory
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 12, 0)
        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.layout_.addWidget(scroll, 1)

        self.actions = QHBoxLayout()
        self.btn_bill, self.btn_pay, self.btn_expense, self.btn_close = (QPushButton() for _ in range(4))
        for b in (self.btn_bill, self.btn_pay, self.btn_expense, self.btn_close):
            self.actions.addWidget(b)
        self.actions.addStretch(1)
        v.addLayout(self.actions)
        self.today_l = QLabel()
        self.today_l.setStyleSheet("font-weight: 700; padding-top: 6px;")
        v.addWidget(self.today_l)
        grid = QGridLayout()
        self.cards: dict[str, Card] = {}
        for i, (key, _) in enumerate(CARDS):
            self.cards[key] = Card()
            grid.addWidget(self.cards[key], i // 4, i % 4)
        v.addLayout(grid)
        self.note = QLabel()
        self.note.setObjectName("hint")
        self.note.setWordWrap(True)
        v.addWidget(self.note)
        self.backup_banner = QLabel()
        self.backup_banner.setObjectName("statusError")
        self.backup_banner.setWordWrap(True)
        v.insertWidget(0, self.backup_banner)

        charts = QHBoxLayout()
        self.week_l, self.month_l = QLabel(), QLabel()
        self.week, self.month = BarChart(), BarChart()
        for label, chart in ((self.week_l, self.week), (self.month_l, self.month)):
            col = QVBoxLayout()
            label.setStyleSheet("font-weight: 700;")
            col.addWidget(label)
            col.addWidget(chart)
            charts.addLayout(col)
        v.addLayout(charts)
        self.recent_l = QLabel()
        self.recent_l.setStyleSheet("font-weight: 700;")
        self.recent = QTableWidget(0, 4)
        self.recent.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.recent.verticalHeader().setVisible(False)
        self.recent.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.recent.setMinimumHeight(260)
        v.addWidget(self.recent_l)
        v.addWidget(self.recent)

        self.btn_bill.clicked.connect(lambda: self.navigate.emit("new_bill"))
        self.btn_pay.clicked.connect(lambda: self.navigate.emit("customers"))
        self.btn_expense.clicked.connect(lambda: self.quick_action.emit("add_expense"))
        self.btn_close.clicked.connect(self._close_day)
        self.retranslate()

    def on_show(self) -> None:
        self.refresh()

    def _close_day(self) -> None:
        ClosingDialog(self, self._sf, self._tr).exec()
        self.refresh()

    def refresh(self) -> None:
        today = ist_today()
        week_from = today.fromordinal(today.toordinal() - 6)
        month_from = today.replace(day=1)
        with session_scope(self._sf) as s:
            d = aq.day_summary(s, today.isoformat())
            week = aq.sales_by_day(s, week_from, today)
            month = aq.sales_by_day(s, month_from, today)
            recent = aq.recent_transactions(s)
            stale = backup_service.is_stale(s)
        c, t = d.collections, self._tr
        values = {"sales": format_inr(d.sales), "bills": str(d.bill_count), "collected": format_inr(c.net_total),
                  "credit": format_inr(d.outstanding_credit), "cash": format_inr(c.net("cash")),
                  "upi": format_inr(c.net("upi")), "other": format_inr(c.net("other")),
                  "expenses": format_inr(d.expenses), "movement": format_inr(d.cash_movement),
                  "jobs": str(d.pending_jobs), "low": str(d.low_stock)}
        tones = {"credit": "warn" if d.outstanding_credit else "", "movement": "bad" if d.cash_movement < 0 else ""}
        for key, text in values.items():
            self.cards[key].set_value(text, tones.get(key, ""))
        self.backup_banner.setText(self._tr("backup.stale", days=backup_service.STALE_AFTER_DAYS) if stale else "")
        self.today_l.setText(f"{t('dash.today')}: {today.strftime('%d-%m-%Y')}")
        self.week.set_data([x.strftime("%d/%m") for x, _ in week], [v for _, v in week])
        self.month.set_data([str(x.day) for x, _ in month], [v for _, v in month])
        self.recent.setRowCount(len(recent))
        for r, item in enumerate(recent):
            cells = [to_ist(item.at).strftime("%d-%m %H:%M"), t(f"dash.kind_{item.kind}"), item.text,
                     ("-" if item.kind in ("refund", "expense") else "") + format_inr(item.amount)]
            for col, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if col == 3:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.recent.setItem(r, col, cell)

    def retranslate(self) -> None:
        super().retranslate()
        t = self._tr
        for key, tkey in CARDS:
            self.cards[key].title.setText(t(tkey))
        self.btn_bill.setText(amp(t("nav.new_bill")))
        self.btn_pay.setText(amp(t("customers.receive")))
        self.btn_expense.setText(amp(t("expense.add")))
        self.btn_close.setText(amp(t("closing.title")))
        self.week_l.setText(t("dash.week"))
        self.month_l.setText(t("dash.month"))
        self.recent_l.setText(t("dash.recent"))
        self.note.setText(t("dash.note"))
        self.recent.setHorizontalHeaderLabels([t(k) for k in (
            "history.col_date", "history.col_status", "receipt.item", "history.col_total")])
        self.refresh()
