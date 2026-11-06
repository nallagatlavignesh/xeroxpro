from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from application.services import settings_service
from application.services.i18n import LANGUAGES, Translator
from business.timeutil import ist_today
from database.connection import session_scope
from ui.billing.billing_page import BillingPage
from ui.customers.customers_page import CustomersPage
from ui.dashboard.dashboard_page import DashboardPage
from ui.expenses.expenses_page import ExpensesPage
from infrastructure.printers.gateway import QtPrinterGateway
from ui.applications.applications_page import ApplicationsPage
from ui.backup.backup_page import BackupPage
from ui.reports.reports_page import ReportsPage
from ui.inventory.inventory_page import InventoryPage
from ui.jobs.jobs_page import JobsPage
from ui.page import PlaceholderPage, amp
from ui.printing.pdf_page import PdfPrintPage
from ui.settings.settings_page import SettingsPage

# (key, translation key) in sidebar order. Pages other than Settings are placeholders until their phase.
NAV = [
    ("dashboard", "nav.dashboard"), ("new_bill", "nav.new_bill"), ("pdf_printing", "nav.pdf_printing"),
    ("job_orders", "nav.job_orders"), ("customers", "nav.customers"), ("inventory", "nav.inventory"),
    ("expenses", "nav.expenses"), ("applications", "nav.applications"), ("reports", "nav.reports"),
    ("settings", "nav.settings"), ("backup", "nav.backup"),
]


class MainWindow(QMainWindow):
    def __init__(self, session_factory, translator: Translator, gateway=None) -> None:
        super().__init__()
        self._sf = session_factory
        self._gateway = gateway or QtPrinterGateway()
        self._t = translator
        self.resize(1366, 740)
        self.setMinimumSize(1000, 600)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sidebar = QFrame(objectName="sidebar")
        sidebar.setFixedWidth(250)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(0)
        self.sidebar_title = QLabel("XeroxPro", objectName="sidebarTitle")
        side.addWidget(self.sidebar_title)
        self.stack = QStackedWidget()
        self.nav_group = QButtonGroup(self)
        self.nav_buttons: dict[str, QPushButton] = {}
        self.pages: dict[str, QWidget] = {}
        for index, (key, tkey) in enumerate(NAV):
            button = QPushButton(objectName="navButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.nav_group.addButton(button, index)
            side.addWidget(button)
            self.nav_buttons[key] = button
            page = self._make_page(key, tkey)
            self.pages[key] = page
            self.stack.addWidget(page)
        side.addStretch(1)
        self.nav_group.idClicked.connect(self.stack.setCurrentIndex)
        self.stack.currentChanged.connect(lambda i: self.pages[NAV[i][0]].on_show())

        right = QVBoxLayout()
        right.setSpacing(0)
        topbar = QFrame(objectName="topbar")
        topbar.setFixedHeight(56)
        top = QHBoxLayout(topbar)
        top.setContentsMargins(24, 0, 24, 0)
        self.shop_label = QLabel(objectName="shopName")
        self.date_label = QLabel(objectName="dateLabel")
        self.lang_label = QLabel()
        self.lang_combo = QComboBox()
        self.lang_combo.activated.connect(lambda _i: self.set_language(self.lang_combo.currentData()))
        top.addWidget(self.shop_label)
        top.addStretch(1)
        top.addWidget(self.date_label)
        top.addSpacing(24)
        top.addWidget(self.lang_label)
        top.addWidget(self.lang_combo)
        right.addWidget(topbar)
        right.addWidget(self.stack, 1)
        outer.addWidget(sidebar)
        outer.addLayout(right, 1)

        self.nav_buttons["dashboard"].setChecked(True)
        self.retranslate()

    def _make_page(self, key: str, tkey: str) -> QWidget:
        if key == "new_bill":
            return BillingPage(self._sf, self._t)
        if key == "pdf_printing":
            page = PdfPrintPage(self._sf, self._t, self._gateway)
            page.add_to_bill.connect(self._add_to_bill)
            return page
        if key == "reports":
            return ReportsPage(self._sf, self._t)
        if key == "backup":
            page = BackupPage(self._sf, self._t)
            page.restored.connect(self.refresh_after_restore)
            return page
        if key == "job_orders":
            return JobsPage(self._sf, self._t)
        if key == "inventory":
            return InventoryPage(self._sf, self._t)
        if key == "applications":
            page = ApplicationsPage(self._sf, self._t)
            page.bill_requested.connect(lambda sid, charge: self._add_to_bill(sid, Decimal(1), 1, {}, charge))
            return page
        if key == "customers":
            return CustomersPage(self._sf, self._t)
        if key == "expenses":
            return ExpensesPage(self._sf, self._t)
        if key == "dashboard":
            page = DashboardPage(self._sf, self._t)
            page.navigate.connect(self.go)
            page.quick_action.connect(self._quick_action)
            return page
        if key != "settings":
            return PlaceholderPage(tkey, self._t.tr)
        page = SettingsPage(self._sf, self._t.tr, lambda: self._t.language, self._gateway)
        page.saved.connect(self.refresh_header)
        page.language_chosen.connect(self.set_language)
        return page

    def refresh_after_restore(self) -> None:
        """The database file was replaced by a backup: reload language, drop the half-made bill, redraw everything."""
        with session_scope(self._sf) as s:
            self._t.set_language(settings_service.get_shop_settings(s).preferred_language)
        self.pages["new_bill"].new_bill.reset()
        self.retranslate()

    def go(self, key: str) -> None:
        """Open a sidebar page programmatically (dashboard shortcuts)."""
        self.nav_buttons[key].setChecked(True)
        self.stack.setCurrentIndex([k for k, _ in NAV].index(key))

    def _add_to_bill(self, service_id: int, quantity, copies: int, details: dict, rate: int | None = None) -> None:
        self.go("new_bill")
        billing = self.pages["new_bill"]
        billing.show_new_bill()
        billing.new_bill.add_service_line(service_id, quantity, copies, details, rate)

    def _quick_action(self, action: str) -> None:
        if action == "add_expense":
            self.go("expenses")
            self.pages["expenses"].add()

    def set_language(self, code: str) -> None:
        if code not in LANGUAGES:
            return
        with session_scope(self._sf) as s:
            settings_service.update_shop_settings(s, preferred_language=code)
        self._t.set_language(code)
        self.retranslate()

    def refresh_header(self) -> None:
        with session_scope(self._sf) as s:
            name = settings_service.get_shop_settings(s).shop_name
        self.shop_label.setText(name)
        self.setWindowTitle(name)

    def retranslate(self) -> None:
        tr = self._t.tr
        for key, tkey in NAV:
            self.nav_buttons[key].setText(amp(tr(tkey)))
            self.pages[key].retranslate()
        self.lang_label.setText(tr("topbar.language"))
        self.lang_combo.clear()
        for code in LANGUAGES:
            self.lang_combo.addItem(tr(f"lang.{code}"), code)
        self.lang_combo.setCurrentIndex(LANGUAGES.index(self._t.language))
        self.date_label.setText(ist_today().strftime("%d-%m-%Y"))
        self.refresh_header()
