from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout,
    QWidget,
)

from application.services import auth_service, settings_service
from application.services.i18n import LANGUAGES
from business.billing import PAYMENT_METHODS
from business.errors import DomainError
from database.connection import session_scope
from ui.page import Page, amp, message_for
from ui.settings.printers_widget import PrintersWidget
from ui.settings.rates_widget import RatesWidget


class SettingsPage(Page):
    saved = Signal()
    language_chosen = Signal(str)

    def __init__(self, session_factory, tr, current_language, gateway) -> None:
        super().__init__("settings.title", tr)
        self._sf = session_factory
        self._current_language = current_language
        self.tabs = QTabWidget()
        self.layout_.addWidget(self.tabs, 1)

        shop = QWidget()
        outer = QVBoxLayout(shop)
        self.form = QFormLayout()
        self.shop_name, self.phone, self.email = QLineEdit(), QLineEdit(), QLineEdit()
        self.address, self.footer = QPlainTextEdit(), QPlainTextEdit()
        for box in (self.address, self.footer):
            box.setFixedHeight(70)
        self.language, self.default_method = QComboBox(), QComboBox()
        self.prefix = QLineEdit()
        self.show_phone = QCheckBox()
        self._labels: dict[str, QLabel] = {}
        for key, widget in (
            ("settings.shop_name", self.shop_name), ("settings.address", self.address),
            ("settings.phone", self.phone), ("settings.email", self.email),
            ("settings.receipt_footer", self.footer), ("settings.bill_prefix", self.prefix),
            ("settings.default_payment", self.default_method), ("settings.language", self.language),
        ):
            self._labels[key] = QLabel()
            self.form.addRow(self._labels[key], widget)
        self.form.addRow(self.show_phone)
        outer.addLayout(self.form)
        self.save_button = QPushButton()
        self.save_button.clicked.connect(self._save)
        outer.addWidget(self.save_button)

        # owner PIN
        self.pin_title = QLabel()
        self.pin_title.setStyleSheet("font-weight: 700; padding-top: 12px;")
        self.pin_hint = QLabel()
        self.pin_hint.setObjectName("hint")
        self.pin_hint.setWordWrap(True)
        self.pin_current, self.pin_new = QLineEdit(), QLineEdit()
        for edit in (self.pin_current, self.pin_new):
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            edit.setMaxLength(6)
        self.pin_form = QFormLayout()
        self._labels["settings.pin_current"], self._labels["settings.pin_new"] = QLabel(), QLabel()
        self.pin_form.addRow(self._labels["settings.pin_current"], self.pin_current)
        self.pin_form.addRow(self._labels["settings.pin_new"], self.pin_new)
        self.pin_set_btn, self.pin_remove_btn = QPushButton(), QPushButton()
        self.pin_set_btn.clicked.connect(self._set_pin)
        self.pin_remove_btn.clicked.connect(self._remove_pin)
        for w in (self.pin_title, self.pin_hint):
            outer.addWidget(w)
        outer.addLayout(self.pin_form)
        outer.addWidget(self.pin_set_btn)
        outer.addWidget(self.pin_remove_btn)
        self.status = QLabel()
        outer.addWidget(self.status)
        outer.addStretch(1)

        self.rates = RatesWidget(session_factory, tr)
        self.tabs.addTab(shop, "")
        self.printers = PrintersWidget(session_factory, tr, gateway)
        self.tabs.addTab(self.rates, "")
        self.tabs.addTab(self.printers, "")
        self.language.activated.connect(lambda _i: self.language_chosen.emit(self.language.currentData()))
        self._load()
        self.retranslate()

    def _load(self) -> None:
        with session_scope(self._sf) as s:
            row = settings_service.get_shop_settings(s)
            self.shop_name.setText(row.shop_name)
            self.address.setPlainText(row.address)
            self.phone.setText(row.phone)
            self.email.setText(row.email or "")
            self.footer.setPlainText(row.receipt_footer)
            self.prefix.setText(row.bill_prefix)
            self.show_phone.setChecked(row.receipt_show_phone)
            self._default_method = row.default_payment_method

    def _report(self, text: str, error: bool) -> None:
        self.status.setObjectName("statusError" if error else "status")
        self.status.setText(text)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _save(self) -> None:
        try:
            with session_scope(self._sf) as s:
                settings_service.update_shop_settings(
                    s, shop_name=self.shop_name.text(), address=self.address.toPlainText(),
                    phone=self.phone.text(), email=self.email.text(), receipt_footer=self.footer.toPlainText(),
                    bill_prefix=self.prefix.text(), default_payment_method=self.default_method.currentData(),
                    receipt_show_phone=self.show_phone.isChecked())
        except DomainError as err:
            self._report(message_for(err, self._tr), True)
            return
        self._report(self._tr("common.saved"), False)
        self.saved.emit()

    def _pin_action(self, action, ok_key: str) -> None:
        try:
            with session_scope(self._sf) as s:
                action(s)
        except DomainError as err:
            self._report(message_for(err, self._tr), True)
            return
        self.pin_current.clear()
        self.pin_new.clear()
        self._report(self._tr(ok_key), False)

    def _set_pin(self) -> None:
        self._pin_action(lambda s: auth_service.set_pin(s, self.pin_new.text(), self.pin_current.text() or None),
                         "settings.pin_saved")

    def _remove_pin(self) -> None:
        self._pin_action(lambda s: auth_service.clear_pin(s, self.pin_current.text() or None),
                         "settings.pin_removed")

    def retranslate(self) -> None:
        super().retranslate()
        t = self._tr
        for key, label in self._labels.items():
            label.setText(t(key))
        self.show_phone.setText(t("settings.show_phone"))
        self.save_button.setText(amp(t("common.save")))
        self.pin_title.setText(t("settings.pin_section"))
        self.pin_hint.setText(t("settings.pin_hint"))
        self.pin_set_btn.setText(amp(t("settings.pin_set")))
        self.pin_remove_btn.setText(amp(t("settings.pin_remove")))
        self.tabs.setTabText(0, amp(t("settings.tab_shop")))
        self.tabs.setTabText(1, amp(t("settings.tab_services")))
        self.tabs.setTabText(2, amp(t("settings.tab_printers")))
        self.language.clear()
        for code in LANGUAGES:
            self.language.addItem(t(f"lang.{code}"), code)
        self.language.setCurrentIndex(LANGUAGES.index(self._current_language()))
        self.default_method.clear()
        for m in PAYMENT_METHODS:
            self.default_method.addItem(t(f"pay.{m}"), m)
        self.default_method.setCurrentIndex(PAYMENT_METHODS.index(self._default_method))
        self.status.clear()
        self.rates.retranslate()
        self.printers.retranslate()
