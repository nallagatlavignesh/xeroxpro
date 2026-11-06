from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout,
)

from application.use_cases import close_day
from business.accounting import closing_difference, expected_drawer
from business.errors import DomainError
from business.money import format_inr
from business.timeutil import ist_today
from database.connection import session_scope
from ui.page import message_for, parse_money, show_domain_error


class ClosingDialog(QDialog):
    """Count the drawer and compare with what the books expect: opening cash + cash in - cash refunds - cash expenses."""

    def __init__(self, parent, session_factory, tr) -> None:
        super().__init__(parent)
        self._sf, self._tr = session_factory, tr
        self._movement = 0
        self.setWindowTitle(tr("closing.title"))
        today = ist_today()
        self.day = QDateEdit(QDate(today.year, today.month, today.day))
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("dd-MM-yyyy")
        self.day.setMaximumDate(self.day.date())
        self.opening, self.counted, self.notes = QLineEdit(), QLineEdit(), QLineEdit()
        self.movement_l, self.expected_l, self.diff_l = QLabel(), QLabel(), QLabel()
        self.diff_l.setStyleSheet("font-weight: 700; font-size: 16px;")
        self.note_l = QLabel(tr("closing.hint"))
        self.note_l.setObjectName("hint")
        self.note_l.setWordWrap(True)
        form = QFormLayout()
        for key, w in (("closing.date", self.day), ("closing.opening", self.opening),
                       ("closing.movement", self.movement_l), ("closing.expected", self.expected_l),
                       ("closing.counted", self.counted), ("closing.difference", self.diff_l),
                       ("expense.notes", self.notes)):
            form.addRow(tr(key), w)
        form.addRow(self.note_l)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.buttons)
        self.day.dateChanged.connect(lambda _d: self._load_day())
        self.opening.textChanged.connect(lambda _t: self._recalc())
        self.counted.textChanged.connect(lambda _t: self._recalc())
        self._load_day()

    def _iso(self) -> str:
        return self.day.date().toPython().isoformat()

    def _load_day(self) -> None:
        with session_scope(self._sf) as s:
            p = close_day.preview(s, self._iso())
        self._movement = p.cash_movement
        self.opening.blockSignals(True)
        self.opening.setText(format_inr(p.opening_cash, symbol=False))
        self.opening.blockSignals(False)
        self.counted.setText(format_inr(p.existing.counted_cash, symbol=False) if p.existing else "")
        self.notes.setText(p.existing.notes if p.existing else "")
        self._recalc()

    def _recalc(self) -> None:
        try:
            expected = expected_drawer(parse_money(self.opening.text()), self._movement)
            self.movement_l.setText(format_inr(self._movement))
            self.expected_l.setText(format_inr(expected))
            if self.counted.text().strip():
                diff = closing_difference(parse_money(self.counted.text()), expected)
                self.diff_l.setText(format_inr(diff))
                self.diff_l.setStyleSheet(
                    f"font-weight: 700; font-size: 16px; color: {'#0F766E' if diff == 0 else '#B91C1C'};")
            else:
                self.diff_l.setText("")
            ok = self.counted.text().strip() != ""
        except DomainError as err:
            self.diff_l.setText(message_for(err, self._tr))
            ok = False
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(ok)

    def _save(self) -> None:
        try:
            with session_scope(self._sf) as s:
                close_day.close_day(s, self._iso(), parse_money(self.counted.text()),
                                    parse_money(self.opening.text()), self.notes.text())
        except DomainError as err:
            show_domain_error(self, err, self._tr)
            return
        self.accept()
