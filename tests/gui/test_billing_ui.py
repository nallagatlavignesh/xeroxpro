"""Drives the real widgets the way the shop owner would. Modal dialogs are replaced with canned answers."""
from decimal import Decimal

import pytest
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from application.services import auth_service, bill_queries, catalog_service, customer_service
from application.services.i18n import Translator
from database.connection import session_scope
from database.models import Bill, Payment, Product
from ui.main_window import MainWindow
from ui.theme import apply_theme


@pytest.fixture
def warnings(monkeypatch):
    seen = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text, *a, **k: seen.append(text))
    return seen


@pytest.fixture
def win(qapp, shop):
    factory, ids = shop
    w = MainWindow(factory, Translator("en"))
    w.show()
    w.nav_buttons["new_bill"].click()
    yield w
    w.close()


def pick(combo, text):
    index = combo.findText(text)
    assert index >= 0, [combo.itemText(i) for i in range(combo.count())]
    combo.setCurrentIndex(index)


def add_line(nb, service, qty, copies=1):
    pick(nb.item, service)
    nb.qty.setText(qty)
    nb.copies.setValue(copies)
    nb.add_btn.click()


def bills(factory):
    with session_scope(factory) as s:
        return s.query(Bill).order_by(Bill.id).all()


def test_billing_workflow_25_pages_2_copies_paid_in_cash(win, shop):
    factory, _ = shop
    nb = win.pages["new_bill"].new_bill
    add_line(nb, "Xerox / Photocopy", "25", 2)
    assert nb.table.rowCount() == 1
    assert [nb.table.item(0, c).text() for c in range(5)] == ["Xerox / Photocopy", "50", "page", "₹2.00", "₹100.00"]
    assert nb.total_l.text() == "₹100.00" and nb.due_l.text() == "₹100.00"
    nb.pay_full_btn.click()  # default method is cash
    assert nb.pay["cash"].text() == "100.00" and nb.due_l.text() == "₹0.00"
    nb.save_btn.click()
    [bill] = bills(factory)
    assert (bill.grand_total, bill.status, bill.customer_id) == (10000, "paid", None)
    assert nb.table.rowCount() == 0 and nb.total_l.text() == "₹0.00"  # form reset for the next customer
    assert nb._key  # new idempotency key
    assert win.pages["new_bill"].history.table.rowCount() == 1


def test_discount_percent_and_amount(win):
    nb = win.pages["new_bill"].new_bill
    add_line(nb, "Lamination", "10")
    nb.discount.setText("10")
    nb.discount_kind.setCurrentText("%")
    assert nb.total_l.text() == "₹180.00"
    nb.discount_kind.setCurrentText("₹")
    nb.discount.setText("5")
    assert nb.total_l.text() == "₹195.00"
    nb.discount.setText("999")
    assert nb.status.objectName() == "statusError" and not nb.save_btn.isEnabled()


def test_credit_without_customer_is_refused_with_message(win, shop, warnings):
    factory, _ = shop
    nb = win.pages["new_bill"].new_bill
    add_line(nb, "Xerox / Photocopy", "50")
    nb.pay["cash"].setText("60")
    assert nb.due_l.text() == "₹40.00"
    assert "customer" in nb.status.text().lower()
    nb.save_btn.click()
    assert warnings and "customer" in warnings[0].lower()
    assert bills(factory) == []


def test_credit_bill_with_new_customer(win, shop, monkeypatch):
    factory, _ = shop
    with session_scope(factory) as s:
        cid = customer_service.create_customer(s, "Ramu", "9848012345").id
    nb = win.pages["new_bill"].new_bill
    nb.reload_catalog()
    add_line(nb, "Xerox / Photocopy", "50")
    nb.pay["cash"].setText("60")
    pick(nb.customer, "Ramu (9848012345)")
    nb.save_btn.click()
    [bill] = bills(factory)
    assert (bill.customer_id, bill.total_paid, bill.outstanding_amount, bill.status) == (cid, 6000, 4000, "partial")


@pytest.mark.parametrize("qty", ["0", "-2", "abc", ""])
def test_bad_quantity_is_rejected_before_adding(win, warnings, qty):
    nb = win.pages["new_bill"].new_bill
    add_line(nb, "Xerox / Photocopy", qty)
    assert nb.table.rowCount() == 0 and len(warnings) == 1


def test_service_without_rate_cannot_be_added(win, warnings):
    nb = win.pages["new_bill"].new_bill
    pick(nb.item, "Scanning")
    assert nb.hint.text() and nb.rate.text() == ""
    nb.add_btn.click()
    assert nb.table.rowCount() == 0 and warnings


def test_remove_line_updates_totals(win):
    nb = win.pages["new_bill"].new_bill
    add_line(nb, "Xerox / Photocopy", "10")
    add_line(nb, "Lamination", "1")
    assert nb.total_l.text() == "₹40.00"
    nb.table.selectRow(0)
    nb.remove_btn.click()
    assert nb.table.rowCount() == 1 and nb.total_l.text() == "₹20.00"


def test_save_is_ignored_while_a_save_is_running(win, shop):
    factory, _ = shop
    nb = win.pages["new_bill"].new_bill
    add_line(nb, "Xerox / Photocopy", "50")
    nb.pay_full_btn.click()
    nb._saving = True
    nb.save_btn.click()
    nb._save(False)
    assert bills(factory) == []


def test_rate_change_checkbox_requires_correct_pin(win, shop, monkeypatch, warnings):
    factory, _ = shop
    with session_scope(factory) as s:
        auth_service.set_pin(s, "1234")
    nb = win.pages["new_bill"].new_bill
    pick(nb.item, "Xerox / Photocopy")
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("0000", True))
    nb.change_rate.setChecked(True)
    assert not nb.change_rate.isChecked() and nb.rate.isReadOnly()
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("1234", True))
    nb.change_rate.setChecked(True)
    assert nb.change_rate.isChecked() and not nb.rate.isReadOnly()
    nb.rate.setText("1.50")
    nb.qty.setText("50")
    nb.add_btn.click()
    nb.pay_full_btn.click()
    assert nb.total_l.text() == "₹75.00"
    nb.save_btn.click()
    [bill] = bills(factory)
    assert bill.grand_total == 7500


def test_stationery_product_sold_from_billing_screen(win, shop):
    factory, _ = shop
    with session_scope(factory) as s:
        s.add(Product(product_name="Notebook", selling_price=2500, purchase_price=1800, stock_quantity=Decimal(10)))
    nb = win.pages["new_bill"].new_bill
    nb.reload_catalog()
    add_line(nb, "Inventory: Notebook", "2")
    nb.pay_full_btn.click()
    nb.save_btn.click()
    with session_scope(factory) as s:
        assert s.query(Product).one().stock_quantity == Decimal(8)


def test_history_search_receipt_and_cancel(win, shop, monkeypatch, qapp):
    factory, _ = shop
    nb = win.pages["new_bill"].new_bill
    add_line(nb, "Xerox / Photocopy", "50")
    nb.pay_full_btn.click()
    nb.save_btn.click()
    hist = win.pages["new_bill"].history
    hist.search.setText("nomatch")
    hist.refresh()
    assert hist.table.rowCount() == 0 and hist.empty.text()
    hist.search.setText("-000001")
    hist.refresh()
    assert hist.table.rowCount() == 1 and hist.table.item(0, 6).text() == "Paid"

    from ui.billing.receipt_dialog import ReceiptDialog
    dialog = ReceiptDialog(win, factory, win._t, bills(factory)[0].id)
    assert dialog.view.document().toPlainText().count("₹100.00") >= 1
    dialog.lang.setCurrentIndex(1)
    dialog._render()  # Telugu receipt preview
    assert "Subtotal" not in dialog.view.document().toPlainText()
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("mistake", True))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    dialog._cancel_bill()
    assert not dialog.cancel_btn.isEnabled()
    with session_scope(factory) as s:
        assert s.get(Bill, bills(factory)[0].id).status == "refunded"
        assert s.query(Payment).filter_by(kind="refund").count() == 1
    hist.refresh()
    assert hist.table.item(0, 6).text() == "Refunded"
    dialog.close()


def test_language_switch_translates_billing_screen(win):
    nb = win.pages["new_bill"].new_bill
    win.set_language("te")
    te = Translator("te").tr
    assert nb.add_btn.text() == te("bill.add_line")
    assert win.pages["new_bill"].tabs.tabText(1) == te("bill.tab_history")
    assert nb.table.horizontalHeaderItem(4).text() == te("bill.col_amount")


def test_rates_tab_sets_rate_and_keeps_history(win, shop, monkeypatch):
    factory, ids = shop
    rates = win.pages["settings"].rates
    rates.refresh()
    row = next(i for i, r in enumerate(rates._rows) if r.name == "Lamination")
    rates.table.selectRow(row)
    assert rates.table.item(row, 2).text() == "₹20.00"
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("25.50", True))
    rates._set_rate()
    assert rates.table.item(row, 2).text() == "₹25.50"
    with session_scope(factory) as s:
        assert [r for _, r in catalog_service.rate_history(s, ids["Lamination"])][0] == 2550


def test_rate_input_validation(win, shop, monkeypatch, warnings):
    rates = win.pages["settings"].rates
    rates.table.selectRow(0)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("-5", True))
    rates._set_rate()
    assert warnings
    assert rates.table.item(0, 2).text() == "₹2.00"


def test_settings_pin_roundtrip(win, shop):
    factory, _ = shop
    page = win.pages["settings"]
    page.pin_new.setText("12")
    page._set_pin()
    assert page.status.objectName() == "statusError"
    page.pin_new.setText("1234")
    page._set_pin()
    with session_scope(factory) as s:
        assert auth_service.has_pin(s)
    page.pin_current.setText("1234")
    page._remove_pin()
    with session_scope(factory) as s:
        assert not auth_service.has_pin(s)


def test_settings_default_method_and_prefix_persist(win, shop):
    factory, _ = shop
    page = win.pages["settings"]
    page.prefix.setText("SX-")
    page.default_method.setCurrentIndex(1)  # upi
    page._save()
    with session_scope(factory) as s:
        from application.services import settings_service
        row = settings_service.get_shop_settings(s)
        assert (row.bill_prefix, row.default_payment_method) == ("SX-", "upi")
    page.prefix.setText("bad prefix!")
    page._save()
    assert page.status.objectName() == "statusError"
