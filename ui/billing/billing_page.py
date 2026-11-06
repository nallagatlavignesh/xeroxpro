from __future__ import annotations

from PySide6.QtWidgets import QTabWidget

from ui.billing.history import HistoryWidget
from ui.billing.new_bill import NewBillWidget
from ui.billing.receipt_dialog import ReceiptDialog
from ui.page import Page, amp


class BillingPage(Page):
    def __init__(self, session_factory, translator) -> None:
        super().__init__("nav.new_bill", translator.tr)
        self._sf, self._translator = session_factory, translator
        self.tabs = QTabWidget()
        self.new_bill = NewBillWidget(session_factory, translator.tr)
        self.history = HistoryWidget(session_factory, translator.tr, self.show_receipt)
        self.tabs.addTab(self.new_bill, "")
        self.tabs.addTab(self.history, "")
        self.layout_.addWidget(self.tabs, 1)
        self.new_bill.bill_saved.connect(self._on_saved)
        self.tabs.currentChanged.connect(self._on_tab)
        self.retranslate()

    def _on_saved(self, bill_id: int, view_receipt: bool) -> None:
        self.history.refresh()
        if view_receipt:
            self.show_receipt(bill_id)

    def _on_tab(self, index: int) -> None:
        if index == 1:
            self.history.refresh()
        else:
            self.new_bill.reload_catalog()  # rates/customers may have changed meanwhile

    def on_show(self) -> None:
        self.new_bill.reload_catalog()

    def show_new_bill(self) -> None:
        self.tabs.setCurrentIndex(0)

    def show_receipt(self, bill_id: int) -> None:
        dialog = ReceiptDialog(self, self._sf, self._translator, bill_id)
        dialog.changed.connect(self.history.refresh)
        dialog.exec()

    def retranslate(self) -> None:
        super().retranslate()
        self.tabs.setTabText(0, amp(self._tr("bill.tab_new")))
        self.tabs.setTabText(1, amp(self._tr("bill.tab_history")))
        self.new_bill.retranslate()
        self.history.retranslate()
