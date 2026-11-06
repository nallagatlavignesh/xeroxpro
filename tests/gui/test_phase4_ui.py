from decimal import Decimal

import pymupdf
import pytest
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from application.services import customer_service, inventory_service, job_service, printer_service
from application.services.i18n import Translator
from database.connection import session_scope
from database.models import Bill, Product
from infrastructure.printers.fake import FakePrinterGateway
from infrastructure.printers.gateway import PrinterCaps
from ui.inventory.inventory_page import MovementDialog, ProductDialog
from ui.jobs.jobs_page import JobDialog, JobPaymentDialog
from ui.applications.applications_page import ApplicationDialog
from ui.main_window import MainWindow
from ui.theme import apply_theme


@pytest.fixture
def gw():
    return FakePrinterGateway()


@pytest.fixture
def win(qapp, shop, gw):
    factory, _ = shop
    w = MainWindow(factory, Translator("en"), gw)
    w.show()
    yield w
    w.close()


@pytest.fixture
def warnings(monkeypatch):
    seen = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text, *a, **k: seen.append(text))
    return seen


@pytest.fixture
def yes(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)


@pytest.fixture
def pdf(tmp_path):
    doc = pymupdf.open()
    for i in range(5):
        doc.new_page(width=595, height=842).insert_text((72, 100), f"Page {i + 1}", fontsize=40)
    doc.save(tmp_path / "doc.pdf")
    return str(tmp_path / "doc.pdf")


def open_pdf(win, pdf):
    win.nav_buttons["pdf_printing"].click()
    page = win.pages["pdf_printing"]
    assert page.open_pdf(pdf)
    return page


# ---- PDF assistant ---------------------------------------------------------------------------

def test_open_pdf_shows_pages_size_and_preview(win, pdf):
    page = open_pdf(win, pdf)
    assert "5 pages" in page.info_label.text() and "A4" in page.info_label.text()
    assert not page.preview.pixmap().isNull() and page.page_label.text() == "1 / 5"
    page.next_btn.click()
    assert page.page_label.text() == "2 / 5"
    page._goto(99)
    assert page.page_label.text() == "2 / 5"
    assert page.selected_label.text() == "5 pages of the document" and page.override.value() == 5


def test_cost_updates_for_range_copies_and_sides(win, pdf):
    page = open_pdf(win, pdf)  # B&W is Rs5 per page in the test catalogue
    page.range.setText("2-4")
    assert page.selected_label.text().startswith("3 pages") and page.override.value() == 3
    assert "₹15.00" in page.estimate_label.text()
    page.copies.setValue(2)
    assert "Pages: 3 per copy x 2 copies = 6 pages" in page.estimate_label.text()
    assert "₹30.00" in page.estimate_label.text()
    page.double.setChecked(True)
    assert "Paper sheets: 2 per copy, 4 in total" in page.estimate_label.text()
    assert "₹30.00" in page.estimate_label.text()  # per-page service: every side is billed
    page.colour.setChecked(True)  # switches to Colour Printing (Rs10)
    assert page.service.currentText() == "Colour Printing" and "₹60.00" in page.estimate_label.text()


def test_manual_page_adjustment_and_reset_on_new_range(win, pdf):
    page = open_pdf(win, pdf)
    page.override.setValue(7)
    assert "₹35.00" in page.estimate_label.text() and page._manual
    page.range.setText("1")
    assert page.override.value() == 1 and not page._manual


def test_bad_ranges_show_a_message_and_block_printing(win, pdf):
    page = open_pdf(win, pdf)
    for text, word in (("9", "only has 5 pages"), ("3-1", "not valid"), ("x", "not valid")):
        page.range.setText(text)
        assert page.status.objectName() == "statusError" and word in page.status.text()
        assert not page.print_btn.isEnabled() and not page.bill_btn.isEnabled()
    page.range.setText("")
    assert page.print_btn.isEnabled()


def test_unreadable_pdf_is_refused(win, tmp_path):
    bad = tmp_path / "x.pdf"
    bad.write_bytes(b"nope")
    win.nav_buttons["pdf_printing"].click()
    page = win.pages["pdf_printing"]
    assert not page.open_pdf(str(bad))
    assert "could not be opened" in page.status.text() and not page.print_btn.isEnabled()


def test_printer_capabilities_are_shown_and_enforced(win, pdf, gw):
    page = open_pdf(win, pdf)
    assert page.printer.currentData() == "Office Laser"
    assert "Colour: no" in page.caps_label.text() and "Double-sided: yes" in page.caps_label.text()
    page.colour.setChecked(True)
    assert not page.print_btn.isEnabled() and "does not support colour" in page.status.text()
    page.printer.setCurrentIndex(page.printer.findData("Colour Inkjet"))
    page._on_printer()
    assert page.print_btn.isEnabled()
    page.double.setChecked(True)
    assert not page.print_btn.isEnabled() and "double-sided" in page.status.text()
    assert page.paper.findData("A3") >= 0 and page.paper.findData("Letter") < 0  # only what this printer lists


def test_undetected_capabilities_are_stated_not_assumed(win, pdf, gw):
    gw.printers = {"Mystery": ("ready", PrinterCaps(None, None, ()))}
    gw.default = "Mystery"
    page = open_pdf(win, pdf)
    page.load_printers()
    assert page.caps_label.text().count("not detected") == 3
    page.colour.setChecked(True)
    page.double.setChecked(True)
    assert page.print_btn.isEnabled()  # allowed, never claimed supported
    assert page.paper.count() >= 3  # falls back to the standard sizes


def test_no_printers_found(win, pdf, gw):
    gw.printers = {}
    page = open_pdf(win, pdf)
    page.load_printers()
    assert not page.print_btn.isEnabled() and page.printer.currentData() is None


def test_print_sends_the_selected_pages_and_never_says_printed(win, pdf, gw, yes):
    page = open_pdf(win, pdf)
    page.range.setText("2-4")
    page.copies.setValue(2)
    page.double.setChecked(True)
    page._print()
    [(name, req)] = gw.jobs
    assert (name, req.pages, req.copies, req.duplex, req.colour, req.paper) == ("Office Laser", [2, 3, 4], 2, True, False, "A4")
    assert "queue" in page.status.text() and "6 pages" in page.status.text()
    assert "printed" not in page.status.text().lower().replace("be printed", "")


def test_print_declined_or_failed(win, pdf, gw, monkeypatch, warnings):
    page = open_pdf(win, pdf)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    page._print()
    assert gw.jobs == []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    gw.fail_with = "spooler stopped"
    page._print()
    assert gw.jobs == [] and page.status.objectName() == "statusError" and "spooler stopped" in page.status.text()
    assert warnings
    gw.fail_with = None
    gw.printers["Office Laser"] = ("error", gw.printers["Office Laser"][1])
    page._print()
    assert gw.jobs == [] and "reports an error" in page.status.text()
    del gw.printers["Office Laser"]  # unplugged between selecting and printing
    page._print()
    assert gw.jobs == [] and "not found" in page.status.text()


def test_add_to_bill_creates_a_billing_line(win, pdf):
    page = open_pdf(win, pdf)
    page.range.setText("1-5")
    page.copies.setValue(3)
    page.bill_btn.click()
    nb = win.pages["new_bill"].new_bill
    assert win.stack.currentWidget() is win.pages["new_bill"]
    assert [nb.table.item(0, c).text() for c in range(5)] == ["B&W Printing", "15", "page", "₹5.00", "₹75.00"]
    assert nb.total_l.text() == "₹75.00"


def test_manual_page_count_flows_to_the_bill(win, pdf):
    page = open_pdf(win, pdf)
    page.override.setValue(8)
    page.bill_btn.click()
    nb = win.pages["new_bill"].new_bill
    assert nb.table.item(0, 1).text() == "8" and nb.total_l.text() == "₹40.00"


def test_printer_settings_tab_lists_and_saves_defaults(win, shop, gw):
    win.nav_buttons["settings"].click()
    tab = win.pages["settings"].printers
    tab.refresh()
    assert tab.table.rowCount() == 2 and tab.table.item(0, 0).text() == "Office Laser"
    assert tab.table.item(1, 2).text() == "yes" and tab.table.item(1, 3).text() == "no"
    tab.receipt.setCurrentIndex(tab.receipt.findData("Colour Inkjet"))
    tab.documents.setCurrentIndex(tab.documents.findData("Office Laser"))
    tab._save()
    factory, _ = shop
    with session_scope(factory) as s:
        assert printer_service.get_default(s, "receipt_a4").printer_name == "Colour Inkjet"
        assert printer_service.get_default(s, "documents").printer_name == "Office Laser"
    win.nav_buttons["pdf_printing"].click()
    assert win.pages["pdf_printing"].printer.currentData() == "Office Laser"


# ---- jobs ------------------------------------------------------------------------------------

def test_job_workflow_through_the_screen(win, shop, monkeypatch, warnings):
    factory, _ = shop
    with session_scope(factory) as s:
        customer_service.create_customer(s, "Ramu", "9848012345")
    win.nav_buttons["job_orders"].click()
    page = win.pages["job_orders"]
    d = JobDialog(win, factory, win._t.tr)
    d.description.setText("100 wedding cards")
    d.total.setText("500")
    d.advance.setText("200")
    d.has_delivery.setChecked(True)
    d._save()
    page.reload()
    assert page.table.rowCount() == 1
    assert [page.table.item(0, c).text() for c in (0, 1, 4, 5, 6, 8)] == [
        "J" + page.table.item(0, 0).text()[1:], "Ramu", "₹500.00", "₹200.00", "₹300.00", "Received"]
    page.table.selectRow(0)
    assert page.edit_btn.isEnabled() and page.pay_btn.isEnabled()
    # cannot deliver while money is owed
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("Delivered", True))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("", True))
    page._change_status()
    assert warnings and "balance" in warnings[0].lower()
    pay = JobPaymentDialog(win, factory, win._t.tr, page._selected())
    assert pay.amount.text() == "300.00"
    pay._save()
    page.reload()
    page.table.selectRow(0)
    assert page.table.item(0, 6).text() == "₹0.00" and not page.pay_btn.isEnabled()
    page._change_status()
    page.reload()
    assert page.table.item(0, 8).text() == "Delivered"
    page.table.selectRow(0)
    assert not page.edit_btn.isEnabled() and not page.status_btn.isEnabled() and page.hist_btn.isEnabled()


def test_job_screen_filters_and_search(win, shop):
    factory, _ = shop
    with session_scope(factory) as s:
        a = customer_service.create_customer(s, "Anil").id
        b = customer_service.create_customer(s, "Bhanu").id
        job_service.create_job(s, a, "x", "", 100, 0, "cash", "1")
        j = job_service.create_job(s, b, "y", "", 100, 0, "cash", "2")
        job_service.change_status(s, j.id, "completed")
    win.nav_buttons["job_orders"].click()
    page = win.pages["job_orders"]
    assert page.table.rowCount() == 2
    page.search.setText("bha")
    assert page.table.rowCount() == 1
    page.search.setText("")
    page.status.setCurrentIndex(page.status.findData("completed"))
    page.reload()
    assert page.table.rowCount() == 1 and page.table.item(0, 1).text() == "Bhanu"


# ---- inventory -------------------------------------------------------------------------------

def test_inventory_workflow(win, shop, monkeypatch, warnings, yes):
    factory, _ = shop
    win.nav_buttons["inventory"].click()
    page = win.pages["inventory"]
    d = ProductDialog(win, factory, win._t.tr)
    d.name.setText("Notebook")
    d.purchase.setText("18")
    d.selling.setText("25")
    d.minimum.setText("5")
    d._save()
    page.reload()
    assert page.table.rowCount() == 1 and page.table.item(0, 7).text() == "LOW"  # nothing in stock yet
    page.table.selectRow(0)
    buy = MovementDialog(win, factory, win._t.tr, "purchase", page._selected())
    buy.qty.setText("10")
    buy.cost.setText("20")
    buy._save()
    page.reload()
    assert page.table.item(0, 2).text() == "10 item" and page.table.item(0, 7).text() == "" and "₹200.00" in page.total.text()
    page.table.selectRow(0)
    # an adjustment that would go below zero asks for confirmation (and the PIN if set)
    adj = MovementDialog(win, factory, win._t.tr, "adjust", page._selected())
    adj.qty.setText("-12")
    adj.note.setText("recount")
    adj._save()
    page.reload()
    assert page.table.item(0, 2).text() == "-2 item"
    page.table.selectRow(0)
    bad = MovementDialog(win, factory, win._t.tr, "purchase", page._selected())
    bad.qty.setText("0")
    bad._save()
    assert warnings


def test_negative_adjustment_refused_without_confirmation(win, shop, monkeypatch):
    factory, _ = shop
    with session_scope(factory) as s:
        p = inventory_service.create_product(s, "Pen", "", "item", 100, 200)
        inventory_service.purchase(s, p.id, Decimal(3), 100)
    win.nav_buttons["inventory"].click()
    page = win.pages["inventory"]
    page.table.selectRow(0)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, t, text, *a, **k: shown.append(text))
    d = MovementDialog(win, factory, win._t.tr, "adjust", page._selected())
    d.qty.setText("-9")
    d.note.setText("test")
    d._save()
    assert shown and "below zero" in shown[0]
    with session_scope(factory) as s:
        assert s.query(Product).one().stock_quantity == 3


def test_low_stock_filter_and_search(win, shop):
    factory, _ = shop
    with session_scope(factory) as s:
        a = inventory_service.create_product(s, "Alpha", "", "item", 1, 2, Decimal(5))
        b = inventory_service.create_product(s, "Beta", "", "item", 1, 2, Decimal(1))
        inventory_service.purchase(s, a.id, Decimal(2), 1)
        inventory_service.purchase(s, b.id, Decimal(9), 1)
    win.nav_buttons["inventory"].click()
    page = win.pages["inventory"]
    assert page.table.rowCount() == 2
    page.low_only.setChecked(True)
    assert [page.table.item(r, 0).text() for r in range(page.table.rowCount())] == ["Alpha"]
    page.low_only.setChecked(False)
    page.search.setText("bet")
    assert page.table.rowCount() == 1
    win.nav_buttons["dashboard"].click()
    assert win.pages["dashboard"].cards["low"].value.text() == "1"  # dashboard agrees


# ---- applications ----------------------------------------------------------------------------

def test_applications_workflow_and_secret_screening(win, shop, warnings):
    factory, _ = shop
    with session_scope(factory) as s:
        customer_service.create_customer(s, "Ramu", "9848012345")
    win.nav_buttons["applications"].click()
    page = win.pages["applications"]
    d = ApplicationDialog(win, factory, win._t.tr)
    d.type.setCurrentText("PAN Card")
    d.charge.setText("150")
    d.notes.setText("password: abc123")
    d._save()
    assert warnings and "password" in warnings[0].lower()
    page.reload()
    assert page.table.rowCount() == 0
    d.notes.setText("documents collected")
    d.reference.setText("REF123")
    d._save()
    page.reload()
    assert [page.table.item(0, c).text() for c in (1, 2, 3, 4, 5, 6)] == [
        "Ramu", "PAN Card", "₹150.00", "REF123", "Received", "Not billed"]
    page.search.setText("zzz")
    assert page.table.rowCount() == 0


def test_bill_this_charge_goes_to_billing_as_a_pin_protected_override(win, shop, monkeypatch):
    factory, ids = shop
    with session_scope(factory) as s:
        from application.services import catalog_service
        from database.models import Service

        sid = s.query(Service).filter_by(service_name="Online Application Assistance").one().id
        catalog_service.set_rate(s, sid, 5000, lambda: "2026-01-01T00:00:00")
        cid = customer_service.create_customer(s, "Ramu", "9848012345").id
        from application.services import application_service, auth_service
        application_service.save_application(s, cid, "PAN Card", 15000, "2026-02-10")
        auth_service.set_pin(s, "1234")
    win.nav_buttons["applications"].click()
    page = win.pages["applications"]
    page.table.selectRow(0)
    page.bill_btn.click()
    nb = win.pages["new_bill"].new_bill
    assert win.stack.currentWidget() is win.pages["new_bill"]
    assert nb.table.item(0, 3).text() == "₹150.00" and nb._drafts[0].override  # charge differs from list rate
    nb.pay["cash"].setText("150")
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("0000", True))
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, t, text, *a, **k: shown.append(text))
    nb.save_btn.click()  # wrong PIN: refused
    assert shown and "PIN" in shown[0]
    with session_scope(factory) as s:
        assert s.query(Bill).count() == 0
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("1234", True))
    nb.save_btn.click()
    with session_scope(factory) as s:
        assert s.query(Bill).one().grand_total == 15000


def test_language_switch_translates_phase4_pages(win):
    win.set_language("te")
    te = Translator("te").tr
    assert win.pages["pdf_printing"].open_btn.text() == te("print.open")
    assert win.pages["job_orders"].new_btn.text() == te("jobs.new")
    assert win.pages["inventory"].buy_btn.text() == te("inventory.purchase")
    assert win.pages["applications"].new_btn.text() == te("applications.new")
    assert win.pages["settings"].tabs.tabText(2) == te("settings.tab_printers")
