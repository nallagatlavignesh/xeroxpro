from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QPlainTextEdit, QVBoxLayout

from application.services import customer_service
from business.errors import DomainError
from database.connection import session_scope
from database.models import Customer
from ui.page import show_domain_error


class CustomerDialog(QDialog):
    """Create a customer, or edit one when `customer_id` is given."""

    def __init__(self, parent, session_factory, tr, customer_id: int | None = None) -> None:
        super().__init__(parent)
        self._sf, self._tr, self._edit_id = session_factory, tr, customer_id
        self.customer_id = customer_id
        self.setWindowTitle(tr("customers.edit" if customer_id else "bill.new_customer"))
        self.name, self.phone, self.address = QLineEdit(), QLineEdit(), QLineEdit()
        self.notes = QPlainTextEdit()
        self.notes.setFixedHeight(70)
        if customer_id:
            with session_scope(session_factory) as s:
                c = s.get(Customer, customer_id)
                self.name.setText(c.customer_name)
                self.phone.setText(c.phone)
                self.address.setText(c.address or "")
                self.notes.setPlainText(c.notes)
        form = QFormLayout()
        form.addRow(tr("customer.name"), self.name)
        form.addRow(tr("customer.phone"), self.phone)
        form.addRow(tr("customer.address"), self.address)
        form.addRow(tr("customer.notes"), self.notes)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _save(self) -> None:
        args = (self.name.text(), self.phone.text(), self.address.text(), self.notes.toPlainText())
        try:
            with session_scope(self._sf) as s:
                if self._edit_id:
                    customer_service.update_customer(s, self._edit_id, *args)
                else:
                    self.customer_id = customer_service.create_customer(s, *args).id
        except DomainError as err:
            show_domain_error(self, err, self._tr)
            return
        self.accept()
