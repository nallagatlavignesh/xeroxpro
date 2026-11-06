from datetime import date
from decimal import Decimal

import pytest
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from application.services import customer_service, expense_service
from application.services.i18n import Translator
from application.use_cases.save_bill import BillRequest, LineRequest, save_bill
from business.billing import PaymentInput
from business.timeutil import ist_today
from database.connection import session_scope
from database.models import Bill, DailyClosing, Expense, Payment
from ui.customers.payment_dialog import PaymentDialog
from ui.dashboard.closing_dialog import ClosingDialog
from ui.expenses.expenses_page import ExpenseDialog
from ui.main_window import MainWindow
from ui.theme import apply_theme


@pytest.fixture
def warnings(monkeypatch):
    seen = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text, *a, **k: seen.append(text))
    return seen


@pytest.fixture
def win(qapp, shop):
    factory, _ = shop
    w = MainWindow(factory, Translator("en"))
    w.show()
    yield w
    w.close()


def make_credit_bill(factory, ids, paid=6000, name="Ramu"):
    with session_scope(factory) as s:
        cid = customer_service.create_customer(s, name, "9848012345").id
        save_bill(s, BillRequest("k-" + name, [LineRequest(Decimal(50), "page", 200, service_id=ids["Xerox / Photocopy"])],
                                 payments=[PaymentInput(paid, "cash")] if paid else [], customer_id=cid))
    return cid


def test_customers_page_lists_balance_and_ledger(win, shop):
    factory, ids = shop
    cid = make_credit_bill(factory, ids)
    win.nav_buttons["customers"].click()  # on_show reloads
    page = win.pages["customers"]
    assert page.table.rowCount() == 1
    assert [page.table.item(0, c).text() for c in range(3)] == ["Ramu", "9848012345", "₹40.00"]
    page.table.selectRow(0)
    assert "₹40.00" in page.balance.text()
    # ledger newest first: payment then bill, with running balance
    assert [page.ledger_t.item(r, 1).text() for r in range(2)] == ["Payment", "Bill"]
    assert [page.ledger_t.item(r, 5).text() for r in range(2)] == ["₹40.00", "₹100.00"]
    assert page.bills_t.rowCount() == 1 and page.pay_t.rowCount() == 1


def test_outstanding_report_filter_and_search(win, shop):
    factory, ids = shop
    make_credit_bill(factory, ids, paid=0, name="Anil")
    make_credit_bill(factory, ids, paid=10000, name="Bhanu")
    win.nav_buttons["customers"].click()
    page = win.pages["customers"]
    assert page.table.rowCount() == 2
    page.only_owing.setChecked(True)
    assert page.table.rowCount() == 1 and page.table.item(0, 0).text() == "Anil"
    assert "₹100.00" in page.total.text()
    page.only_owing.setChecked(False)
    page.search.setText("bha")
    assert page.table.rowCount() == 1 and page.table.item(0, 0).text() == "Bhanu"


def test_receive_payment_dialog_clears_balance_and_blocks_double_submit(win, shop):
    factory, ids = shop
    cid = make_credit_bill(factory, ids)
    dialog = PaymentDialog(win, factory, win._t.tr, cid)
    assert dialog.amount.text() == "40.00" and "₹40.00" in dialog.preview.text()
    dialog._save()
    dialog._save()  # same dialog, same idempotency key: must not pay twice
    with session_scope(factory) as s:
        assert customer_service.balance_of(s, cid) == 0
        assert s.query(Payment).filter_by(kind="payment").count() == 2
        assert s.query(Bill).one().status == "paid"


def test_payment_dialog_rejects_overpayment(win, shop):
    factory, ids = shop
    cid = make_credit_bill(factory, ids)
    dialog = PaymentDialog(win, factory, win._t.tr, cid)
    dialog.amount.setText("50")
    assert not dialog.buttons.button(dialog.buttons.StandardButton.Ok).isEnabled()
    assert "more than" in dialog.preview.text()
    dialog.amount.setText("abc")
    assert not dialog.buttons.button(dialog.buttons.StandardButton.Ok).isEnabled()


def test_pay_selected_bill_from_customers_page(win, shop, monkeypatch):
    factory, ids = shop
    make_credit_bill(factory, ids)
    win.nav_buttons["customers"].click()
    page = win.pages["customers"]
    page.table.selectRow(0)
    page.bills_t.selectRow(0)
    seen = {}
    monkeypatch.setattr("ui.customers.customers_page.PaymentDialog",
                        lambda parent, sf, tr, cid, bill_id: type("D", (), {"exec": lambda self: seen.update(c=cid, b=bill_id) or 1})())
    page._receive_for_bill()
    assert seen["b"] is not None


def test_expense_page_add_edit_void(win, shop, monkeypatch, warnings):
    factory, _ = shop
    win.nav_buttons["expenses"].click()
    page = win.pages["expenses"]
    d = ExpenseDialog(win, factory, win._t.tr)
    d.category.setCurrentText("Paper")
    d.amount.setText("450")
    d._save()
    page.reload()
    assert page.table.rowCount() == 1 and page.table.item(0, 4).text() == "₹450.00"
    assert "₹450.00" in page.total.text() and "Paper" in page.by_category.text()
    page.table.selectRow(0)
    with session_scope(factory) as s:
        e = s.query(Expense).one()
    d2 = ExpenseDialog(win, factory, win._t.tr, e)
    d2.amount.setText("500")
    d2.method.setCurrentIndex(1)
    d2._save()
    page.reload()
    assert page.table.item(0, 4).text() == "₹500.00" and page.table.item(0, 3).text() == "UPI"
    page.table.selectRow(0)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("duplicate", True))
    page._void()
    assert page.table.item(0, 5).text() == "Cancelled" and "₹0.00" in page.total.text()
    assert not page.void_btn.isEnabled()


def test_expense_dialog_validation_and_stock_hint(win, shop, warnings):
    factory, _ = shop
    d = ExpenseDialog(win, factory, win._t.tr)
    d.amount.setText("0")
    d._save()
    assert warnings and "more than zero" in warnings[0]
    d.category.setCurrentText("Stationery purchases")
    assert "Inventory" in d.hint.text()
    d.category.setCurrentText("Paper")
    assert d.hint.text() == ""


def test_dashboard_shows_separate_numbers(win, shop):
    factory, ids = shop
    cid = make_credit_bill(factory, ids, paid=3000)  # Rs100 sale, Rs30 cash received, Rs70 udhar
    with session_scope(factory) as s:
        expense_service.add_expense(s, "Paper", "", 1000, "cash", ist_today().isoformat())
    win.nav_buttons["dashboard"].click()
    win.nav_buttons["new_bill"].click()
    win.nav_buttons["dashboard"].click()
    c = win.pages["dashboard"].cards
    assert c["sales"].value.text() == "₹100.00"
    assert c["collected"].value.text() == "₹30.00" and c["cash"].value.text() == "₹30.00"
    assert c["upi"].value.text() == "₹0.00"
    assert c["credit"].value.text() == "₹70.00"
    assert c["expenses"].value.text() == "₹10.00"
    assert c["movement"].value.text() == "₹20.00"  # 30 in - 10 out; NOT sales minus expenses
    assert c["bills"].value.text() == "1"
    dash = win.pages["dashboard"]
    assert dash.recent.rowCount() == 3  # bill, payment, expense
    assert dash.week._values[-1] == 10000 and len(dash.week._values) == 7
    assert dash.month._values[-1] == 10000


def test_dashboard_quick_actions_navigate(win, shop, monkeypatch):
    dash = win.pages["dashboard"]
    dash.btn_bill.click()
    assert win.stack.currentIndex() == 1
    win.nav_buttons["dashboard"].click()
    dash.btn_pay.click()
    assert win.stack.currentWidget() is win.pages["customers"]
    opened = []
    monkeypatch.setattr(win.pages["expenses"], "add", lambda: opened.append(1))
    win.nav_buttons["dashboard"].click()
    dash.btn_expense.click()
    assert opened and win.stack.currentWidget() is win.pages["expenses"]


def test_closing_dialog_saves_difference(win, shop):
    factory, ids = shop
    make_credit_bill(factory, ids, paid=6000)  # Rs60 cash in today
    d = ClosingDialog(win, factory, win._t.tr)
    assert d.movement_l.text() == "₹60.00" and d.expected_l.text() == "₹60.00"
    assert not d.buttons.button(d.buttons.StandardButton.Save).isEnabled()  # nothing counted yet
    d.counted.setText("58")
    assert d.diff_l.text() == "-₹2.00"
    d.opening.setText("100")
    assert d.expected_l.text() == "₹160.00"
    d.opening.setText("0")
    d._save()
    with session_scope(factory) as s:
        c = s.query(DailyClosing).one()
        assert (c.expected_cash, c.counted_cash, c.difference) == (6000, 5800, -200)
    again = ClosingDialog(win, factory, win._t.tr)  # reopening shows what was saved
    assert again.counted.text() == "58.00"


def test_language_switch_translates_new_pages(win):
    win.set_language("te")
    te = Translator("te").tr
    assert win.pages["customers"].new_btn.text() == te("bill.new_customer")
    assert win.pages["expenses"].add_btn.text() == te("expense.add")
    assert win.pages["dashboard"].cards["sales"].title.text() == te("dash.sales")
    assert win.pages["dashboard"].recent_l.text() == te("dash.recent")
