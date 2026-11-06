from __future__ import annotations

import uuid

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout,
)

from application.services import settings_service
from application.use_cases.record_payment import outstanding_bills, preview_allocation, record_customer_payment
from business.billing import PAYMENT_METHODS
from business.errors import DomainError
from business.money import format_inr
from database.connection import session_scope
from ui.page import message_for, parse_money, show_domain_error


class PaymentDialog(QDialog):
    """Receive a payment against a customer's udhar. Oldest bills are settled first unless one bill is chosen."""

    def __init__(self, parent, session_factory, tr, customer_id: int, bill_id: int | None = None) -> None:
        super().__init__(parent)
        self._sf, self._tr, self._cid, self._bill_id = session_factory, tr, customer_id, bill_id
        self._key = str(uuid.uuid4())  # one key per dialog: a double click can't record the payment twice
        self._saving = False
        self.setWindowTitle(tr("payment.title"))
        with session_scope(session_factory) as s:
            due = sum(b.outstanding_amount for b in outstanding_bills(s, customer_id, bill_id))
            default_method = settings_service.get_shop_settings(s).default_payment_method
        self.amount = QLineEdit(format_inr(due, symbol=False) if due else "")
        self.method = QComboBox()
        for m in PAYMENT_METHODS:
            self.method.addItem(tr(f"pay.{m}"), m)
        self.method.setCurrentIndex(PAYMENT_METHODS.index(default_method))
        self.reference = QLineEdit()
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        form = QFormLayout()
        form.addRow(tr("payment.due"), QLabel(format_inr(due)))
        form.addRow(tr("payment.amount"), self.amount)
        form.addRow(tr("payment.method"), self.method)
        form.addRow(tr("payment.reference"), self.reference)
        form.addRow(self.preview)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.buttons)
        self.amount.textChanged.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        try:
            with session_scope(self._sf) as s:
                lines = preview_allocation(s, self._cid, parse_money(self.amount.text()), self._bill_id)
        except DomainError as err:
            self.preview.setObjectName("statusError")
            self.preview.setText(message_for(err, self._tr))
            ok.setEnabled(False)
        else:
            self.preview.setObjectName("hint")
            self.preview.setText("\n".join(f"{n}: {format_inr(a)}" for n, a in lines))
            ok.setEnabled(True)
        self.preview.style().unpolish(self.preview)
        self.preview.style().polish(self.preview)

    def _save(self) -> None:
        if self._saving:
            return
        self._saving = True
        try:
            with session_scope(self._sf) as s:
                record_customer_payment(s, self._cid, parse_money(self.amount.text()), self.method.currentData(),
                                        self._key, self.reference.text(), self._bill_id)
        except DomainError as err:
            show_domain_error(self, err, self._tr)
            return
        finally:
            self._saving = False
        self.accept()
