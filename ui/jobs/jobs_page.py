from __future__ import annotations

import uuid
from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from application.services import catalog_service, customer_service, job_service
from business.billing import PAYMENT_METHODS
from business.errors import DomainError
from business.money import format_inr
from business.timeutil import ist_today, to_ist
from database.connection import session_scope
from ui.customers.customer_dialog import CustomerDialog
from ui.page import Page, amp, parse_money, show_domain_error

RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def _qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


class JobDialog(QDialog):
    """New job (customer, work, total, advance, delivery date) or edit of an open one."""

    def __init__(self, parent, sf, tr, job: job_service.JobRow | None = None) -> None:
        super().__init__(parent)
        self._sf, self._tr, self._job = sf, tr, job
        self._key = str(uuid.uuid4())
        self.setWindowTitle(tr("jobs.edit" if job else "jobs.new"))
        self.customer = QComboBox()
        self.new_customer = QPushButton(amp(tr("bill.new_customer")))
        self.description, self.notes = QLineEdit(), QLineEdit()
        self.service = QComboBox()
        self.service.setEditable(True)
        self.total, self.advance = QLineEdit(), QLineEdit()
        self.method = QComboBox()
        for m in PAYMENT_METHODS:
            self.method.addItem(tr(f"pay.{m}"), m)
        self.has_delivery = QCheckBox(tr("jobs.expected_delivery"))
        self.delivery = QDateEdit(_qdate(ist_today()))
        self.delivery.setCalendarPopup(True)
        self.delivery.setDisplayFormat("dd-MM-yyyy")
        with session_scope(sf) as s:
            self._customers = [(c.id, c.customer_name, c.phone) for c in customer_service.search_customers(s, limit=500)]
            self.service.addItems([r.name for r in catalog_service.list_services(s, active_only=True)])
        self._fill_customers(None)
        form = QFormLayout()
        crow = QHBoxLayout()
        crow.addWidget(self.customer, 1)
        crow.addWidget(self.new_customer)
        drow = QHBoxLayout()
        drow.addWidget(self.has_delivery)
        drow.addWidget(self.delivery)
        form.addRow(tr("bill.customer"), crow)
        form.addRow(tr("jobs.service"), self.service)
        form.addRow(tr("jobs.description"), self.description)
        form.addRow(tr("jobs.total"), self.total)
        if not job:
            form.addRow(tr("jobs.advance"), self.advance)
            form.addRow(tr("payment.method"), self.method)
        form.addRow(drow)
        form.addRow(tr("expense.notes"), self.notes)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(box)
        self.new_customer.clicked.connect(self._add_customer)
        if job:
            self.customer.setEnabled(False)
            self.new_customer.setEnabled(False)
            self.service.setCurrentText(job.service_type)
            self.description.setText(job.description)
            self.total.setText(format_inr(job.total, symbol=False))
            if job.expected_delivery:
                self.has_delivery.setChecked(True)
                self.delivery.setDate(_qdate(date.fromisoformat(job.expected_delivery)))

    def _fill_customers(self, select_id: int | None) -> None:
        self.customer.clear()
        for cid, name, phone in self._customers:
            self.customer.addItem(f"{name} ({phone})" if phone else name, cid)
        if select_id is not None:
            self.customer.setCurrentIndex(self.customer.findData(select_id))

    def _add_customer(self) -> None:
        dialog = CustomerDialog(self, self._sf, self._tr)
        if dialog.exec():
            with session_scope(self._sf) as s:
                self._customers = [(c.id, c.customer_name, c.phone) for c in customer_service.search_customers(s, limit=500)]
            self._fill_customers(dialog.customer_id)

    def _save(self) -> None:
        delivery = self.delivery.date().toPython().isoformat() if self.has_delivery.isChecked() else None
        try:
            with session_scope(self._sf) as s:
                if self._job:
                    job_service.update_job(s, self._job.id, self.description.text(), self.service.currentText(),
                                           parse_money(self.total.text()), delivery, self.notes.text())
                else:
                    job_service.create_job(s, self.customer.currentData(), self.description.text(),
                                           self.service.currentText(), parse_money(self.total.text()),
                                           parse_money(self.advance.text()), self.method.currentData(), self._key,
                                           delivery, self.notes.text())
        except DomainError as err:
            show_domain_error(self, err, self._tr)
            return
        self.accept()


class JobPaymentDialog(QDialog):
    def __init__(self, parent, sf, tr, job: job_service.JobRow) -> None:
        super().__init__(parent)
        self._sf, self._tr, self._job, self._key = sf, tr, job, str(uuid.uuid4())
        self.setWindowTitle(tr("jobs.collect"))
        self.amount = QLineEdit(format_inr(job.balance, symbol=False))
        self.method = QComboBox()
        for m in PAYMENT_METHODS:
            self.method.addItem(tr(f"pay.{m}"), m)
        form = QFormLayout()
        form.addRow(tr("payment.due"), QLabel(format_inr(job.balance)))
        form.addRow(tr("payment.amount"), self.amount)
        form.addRow(tr("payment.method"), self.method)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(box)

    def _save(self) -> None:
        try:
            with session_scope(self._sf) as s:
                job_service.collect_payment(s, self._job.id, parse_money(self.amount.text()),
                                            self.method.currentData(), self._key)
        except DomainError as err:
            show_domain_error(self, err, self._tr)
            return
        self.accept()


class JobsPage(Page):
    def __init__(self, session_factory, translator) -> None:
        super().__init__("nav.job_orders", translator.tr)
        self._sf = session_factory
        self._rows: list[job_service.JobRow] = []
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.status = QComboBox()
        self.new_btn, self.edit_btn, self.status_btn, self.pay_btn, self.hist_btn = (QPushButton() for _ in range(5))
        bar.addWidget(self.search, 1)
        bar.addWidget(self.status)
        self.layout_.addLayout(bar)
        self.table = QTableWidget(0, 9)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.layout_.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        for b in (self.new_btn, self.edit_btn, self.status_btn, self.pay_btn, self.hist_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        self.layout_.addLayout(buttons)
        self.search.textChanged.connect(lambda _t: self.reload())
        self.status.activated.connect(lambda _i: self.reload())
        self.new_btn.clicked.connect(self._new)
        self.edit_btn.clicked.connect(self._edit)
        self.status_btn.clicked.connect(self._change_status)
        self.pay_btn.clicked.connect(self._collect)
        self.hist_btn.clicked.connect(self._history)
        self.table.itemSelectionChanged.connect(self._buttons)
        self.retranslate()

    def on_show(self) -> None:
        self.reload()

    def reload(self) -> None:
        with session_scope(self._sf) as s:
            self._rows = job_service.list_jobs(s, self.search.text(), self.status.currentData())
        today = ist_today().isoformat()
        self.table.setRowCount(len(self._rows))
        for r, j in enumerate(self._rows):
            overdue = j.status in job_service.OPEN and j.expected_delivery and j.expected_delivery < today
            delivery = ""
            if j.expected_delivery:
                y, m, d = j.expected_delivery.split("-")
                delivery = f"{d}-{m}-{y}"
            cells = [j.number, j.customer, j.phone, j.description, format_inr(j.total), format_inr(j.advance),
                     format_inr(j.balance), delivery, self._tr(f"jobs.status_{j.status}")]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c in (4, 5, 6):
                    item.setTextAlignment(RIGHT)
                if overdue:
                    item.setForeground(QColor("#B91C1C"))
                self.table.setItem(r, c, item)
        self._buttons()

    def _selected(self) -> job_service.JobRow | None:
        row = self.table.currentRow()
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def _buttons(self) -> None:
        j = self._selected()
        open_ = j is not None and j.status not in job_service.TERMINAL
        self.edit_btn.setEnabled(open_)
        self.status_btn.setEnabled(open_)
        self.pay_btn.setEnabled(open_ and j.balance > 0)
        self.hist_btn.setEnabled(j is not None)

    def _new(self) -> None:
        if JobDialog(self, self._sf, self._tr).exec():
            self.reload()

    def _edit(self) -> None:
        if (j := self._selected()) and JobDialog(self, self._sf, self._tr, j).exec():
            self.reload()

    def _collect(self) -> None:
        if (j := self._selected()) and JobPaymentDialog(self, self._sf, self._tr, j).exec():
            self.reload()

    def _change_status(self) -> None:
        j = self._selected()
        if j is None:
            return
        t = self._tr
        options = [s for s in job_service.STATUSES if s != j.status]
        labels = [t(f"jobs.status_{s}") for s in options]
        label, ok = QInputDialog.getItem(self, t("jobs.change_status"), t("jobs.new_status"), labels, 0, False)
        if not ok:
            return
        status = options[labels.index(label)]
        notes, ok = QInputDialog.getText(self, t("jobs.change_status"),
                                         t("bill.cancel_reason" if status == "cancelled" else "expense.notes"))
        if not ok:
            return
        try:
            with session_scope(self._sf) as s:
                job_service.change_status(s, j.id, status, notes)
        except DomainError as err:
            show_domain_error(self, err, t)
            return
        self.reload()

    def _history(self) -> None:
        j = self._selected()
        if j is None:
            return
        with session_scope(self._sf) as s:
            rows = job_service.status_history(s, j.id)
        t = self._tr
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{t('jobs.history')} - {j.number}")
        table = QTableWidget(len(rows), 3)
        table.setHorizontalHeaderLabels([t("history.col_date"), t("history.col_status"), t("expense.notes")])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for r, h in enumerate(rows):
            move = t(f"jobs.status_{h.new_status}") if not h.previous_status else \
                f"{t('jobs.status_' + h.previous_status)} › {t('jobs.status_' + h.new_status)}"
            for c, text in enumerate((to_ist(h.changed_at).strftime("%d-%m-%Y %H:%M"), move, h.notes)):
                table.setItem(r, c, QTableWidgetItem(text))
        table.horizontalHeader().setStretchLastSection(True)
        layout = QVBoxLayout(dialog)
        layout.addWidget(table)
        dialog.resize(560, 320)
        dialog.exec()

    def retranslate(self) -> None:
        super().retranslate()
        t = self._tr
        self.search.setPlaceholderText(t("jobs.search"))
        self.new_btn.setText(amp(t("jobs.new")))
        self.edit_btn.setText(amp(t("jobs.edit")))
        self.status_btn.setText(amp(t("jobs.change_status")))
        self.pay_btn.setText(amp(t("jobs.collect")))
        self.hist_btn.setText(amp(t("jobs.history")))
        self.status.blockSignals(True)
        self.status.clear()
        self.status.addItem(t("history.all"), None)
        for s in job_service.STATUSES:
            self.status.addItem(t(f"jobs.status_{s}"), s)
        self.status.blockSignals(False)
        self.table.setHorizontalHeaderLabels([t(k) for k in (
            "jobs.number", "bill.customer", "jobs.col_phone", "jobs.description", "history.col_total",
            "jobs.col_advance", "history.col_due", "jobs.col_delivery", "history.col_status")])
        self.reload()
