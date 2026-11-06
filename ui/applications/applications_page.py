from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)
from sqlalchemy import select

from application.services import application_service, catalog_service, customer_service
from business.errors import DomainError, ValidationError
from business.money import format_inr
from business.timeutil import ist_today
from database.connection import session_scope
from database.models import ApplicationRecord, Bill, Service
from ui.customers.customer_dialog import CustomerDialog
from ui.page import Page, amp, parse_money, show_domain_error

RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
BILLING_SERVICE = "Online Application Assistance"


def _qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


class ApplicationDialog(QDialog):
    def __init__(self, parent, sf, tr, row: application_service.ApplicationRow | None = None) -> None:
        super().__init__(parent)
        self._sf, self._tr, self._row = sf, tr, row
        self.setWindowTitle(tr("applications.edit" if row else "applications.new"))
        self.customer = QComboBox()
        self.new_customer = QPushButton(amp(tr("bill.new_customer")))
        self.type = QComboBox()
        self.type.setEditable(True)
        self.charge, self.reference, self.notes, self.bill = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.when = QDateEdit(_qdate(ist_today()))
        self.when.setCalendarPopup(True)
        self.when.setDisplayFormat("dd-MM-yyyy")
        self.status = QComboBox()
        for s in application_service.STATUSES:
            self.status.addItem(tr(f"applications.status_{s}"), s)
        with session_scope(sf) as s:
            self._customers = [(c.id, c.customer_name, c.phone) for c in customer_service.search_customers(s, limit=500)]
            self.type.addItems(catalog_service.list_lookup(s, "application_type"))
            if row:
                rec = s.get(ApplicationRecord, row.id)
                self._customer_id = rec.customer_id
        self._fill_customers(self._customer_id if row else None)
        warn = QLabel(tr("applications.warning"))
        warn.setObjectName("statusError")
        warn.setWordWrap(True)
        form = QFormLayout()
        crow = QHBoxLayout()
        crow.addWidget(self.customer, 1)
        crow.addWidget(self.new_customer)
        form.addRow(tr("bill.customer"), crow)
        form.addRow(tr("applications.type"), self.type)
        form.addRow(tr("applications.charge"), self.charge)
        form.addRow(tr("expense.date"), self.when)
        form.addRow(tr("applications.reference"), self.reference)
        form.addRow(tr("history.col_status"), self.status)
        form.addRow(tr("applications.bill_number"), self.bill)
        form.addRow(tr("expense.notes"), self.notes)
        form.addRow(warn)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(box)
        self.new_customer.clicked.connect(self._add_customer)
        if row:
            self.type.setCurrentText(row.type)
            self.charge.setText(format_inr(row.charge, symbol=False))
            self.when.setDate(_qdate(date.fromisoformat(row.date)))
            self.reference.setText(row.reference)
            self.status.setCurrentIndex(application_service.STATUSES.index(row.status))
            self.bill.setText(row.bill_number or "")
            self.notes.setText(row.notes)

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
        try:
            if self.customer.currentData() is None:
                raise ValidationError("bill.unknown_customer")
            with session_scope(self._sf) as s:
                application_service.save_application(
                    s, self.customer.currentData(), self.type.currentText(), parse_money(self.charge.text()),
                    self.when.date().toPython().isoformat(), self.reference.text(), self.notes.text(),
                    self.status.currentData(), self.bill.text(), self._row.id if self._row else None)
        except DomainError as err:
            show_domain_error(self, err, self._tr)
            return
        self.accept()


class ApplicationsPage(Page):
    bill_requested = Signal(int, int)  # service id, charge in paise

    def __init__(self, session_factory, translator) -> None:
        super().__init__("nav.applications", translator.tr)
        self._sf = session_factory
        self._rows: list[application_service.ApplicationRow] = []
        warn = QLabel()
        warn.setObjectName("statusError")
        warn.setWordWrap(True)
        self.warning = warn
        self.layout_.addWidget(warn)
        bar = QHBoxLayout()
        self.search, self.status = QLineEdit(), QComboBox()
        bar.addWidget(self.search, 1)
        bar.addWidget(self.status)
        self.layout_.addLayout(bar)
        self.table = QTableWidget(0, 7)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.layout_.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        self.new_btn, self.edit_btn, self.status_btn, self.bill_btn = (QPushButton() for _ in range(4))
        for b in (self.new_btn, self.edit_btn, self.status_btn, self.bill_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        self.layout_.addLayout(buttons)
        self.search.textChanged.connect(lambda _t: self.reload())
        self.status.activated.connect(lambda _i: self.reload())
        self.new_btn.clicked.connect(self._new)
        self.edit_btn.clicked.connect(self._edit)
        self.status_btn.clicked.connect(self._change_status)
        self.bill_btn.clicked.connect(self._bill)
        self.table.itemSelectionChanged.connect(self._buttons)
        self.retranslate()

    def on_show(self) -> None:
        self.reload()

    def reload(self) -> None:
        with session_scope(self._sf) as s:
            self._rows = application_service.list_applications(s, self.search.text(), self.status.currentData())
        t = self._tr
        self.table.setRowCount(len(self._rows))
        for r, a in enumerate(self._rows):
            y, m, d = a.date.split("-")
            pay = t("applications.not_billed") if a.payment_status == "not_billed" else t(f"status.{a.payment_status}")
            cells = [f"{d}-{m}-{y}", a.customer, a.type, format_inr(a.charge), a.reference,
                     t(f"applications.status_{a.status}"), pay]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 3:
                    item.setTextAlignment(RIGHT)
                self.table.setItem(r, c, item)
        self._buttons()

    def _selected(self):
        row = self.table.currentRow()
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def _buttons(self) -> None:
        has = self._selected() is not None
        for b in (self.edit_btn, self.status_btn, self.bill_btn):
            b.setEnabled(has)

    def _new(self) -> None:
        if ApplicationDialog(self, self._sf, self._tr).exec():
            self.reload()

    def _edit(self) -> None:
        if (a := self._selected()) and ApplicationDialog(self, self._sf, self._tr, a).exec():
            self.reload()

    def _change_status(self) -> None:
        a = self._selected()
        if a is None:
            return
        labels = [self._tr(f"applications.status_{s}") for s in application_service.STATUSES]
        label, ok = QInputDialog.getItem(self, self._tr("jobs.change_status"), self._tr("jobs.new_status"),
                                         labels, application_service.STATUSES.index(a.status), False)
        if ok:
            with session_scope(self._sf) as s:
                application_service.set_status(s, a.id, application_service.STATUSES[labels.index(label)])
            self.reload()

    def _bill(self) -> None:
        """Send the service charge to the New Bill screen; link the resulting bill number afterwards via Edit."""
        a = self._selected()
        if a is None:
            return
        with session_scope(self._sf) as s:
            service_id = s.scalar(select(Service.id).where(Service.service_name == BILLING_SERVICE))
        self.bill_requested.emit(service_id, a.charge)

    def retranslate(self) -> None:
        super().retranslate()
        t = self._tr
        self.warning.setText(t("applications.warning"))
        self.search.setPlaceholderText(t("applications.search"))
        self.new_btn.setText(amp(t("applications.new")))
        self.edit_btn.setText(amp(t("applications.edit")))
        self.status_btn.setText(amp(t("jobs.change_status")))
        self.bill_btn.setText(amp(t("applications.bill")))
        self.status.blockSignals(True)
        self.status.clear()
        self.status.addItem(t("history.all"), None)
        for s in application_service.STATUSES:
            self.status.addItem(t(f"applications.status_{s}"), s)
        self.status.blockSignals(False)
        self.table.setHorizontalHeaderLabels([t(k) for k in (
            "history.col_date", "bill.customer", "applications.type", "applications.charge", "applications.reference",
            "history.col_status", "applications.payment")])
        self.reload()
