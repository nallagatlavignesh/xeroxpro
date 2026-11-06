from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pymupdf
import pytest
from openpyxl import load_workbook
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

import config
from application.services import auth_service, backup_service, customer_service, expense_service
from application.services.i18n import Translator
from application.use_cases.save_bill import BillRequest, LineRequest, save_bill
from business.billing import PaymentInput
from business.timeutil import ist_today
from database.connection import session_scope
from database.models import Bill, ShopSettings
from ui.main_window import MainWindow
from ui.reports.reports_page import REPORTS
from ui.theme import apply_theme


@pytest.fixture
def win(qapp, shop, tmp_path):
    factory, ids = shop
    with session_scope(factory) as s:
        s.get(ShopSettings, 1).backup_dir = str(tmp_path / "backups")
        s.get(ShopSettings, 1).shop_name = "Sri Xerox"
    w = MainWindow(factory, Translator("en"))
    w.show()
    yield w
    w.close()


def sell(factory, ids, key, pages=50, paid=True, customer=None):
    with session_scope(factory) as s:
        save_bill(s, BillRequest(key, [LineRequest(Decimal(pages), "page", 200, service_id=ids["Xerox / Photocopy"])],
                                 payments=[PaymentInput(pages * 200, "cash")] if paid else [], customer_id=customer))


def seed(factory, ids):
    with session_scope(factory) as s:
        cid = customer_service.create_customer(s, "Ramu", "9848012345").id
        expense_service.add_expense(s, "Paper", "ream", 3000, "cash", ist_today().isoformat())
    sell(factory, ids, "a")
    sell(factory, ids, "b", 25, paid=False, customer=cid)


# ---- reports ---------------------------------------------------------------------------------

def test_every_report_displays(win, shop):
    factory, ids = shop
    seed(factory, ids)
    win.nav_buttons["reports"].click()
    page = win.pages["reports"]
    for index, (key, title, _) in enumerate(REPORTS):
        page.which.setCurrentIndex(index)
        page._controls()
        assert page.report is not None and page.report.key == key, key
        assert page.table.columnCount() == len(page.report.columns)
        assert page.table.rowCount() >= len(page.report.rows)
        assert page.notes.text() and page.pdf_btn.isEnabled()


def test_sales_report_figures_and_period_buttons(win, shop):
    factory, ids = shop
    seed(factory, ids)
    win.nav_buttons["reports"].click()
    page = win.pages["reports"]
    assert page.which.currentData() == "sales" and page.period.currentData() == "day"
    assert [page.table.item(0, c).text() for c in (1, 2, 3)] == ["2", "₹150.00", "₹100.00"]  # bills, sales, cash in
    assert "Money received" in page.summary.text() and "₹100.00" in page.summary.text()
    page.period.setCurrentIndex(page.period.findData("week"))
    page._controls()
    assert page.table.rowCount() == 8  # 7 days + total
    assert page.to_d.date().toPython() - page.from_d.date().toPython() >= timedelta(days=0)
    page.period.setCurrentIndex(page.period.findData("month"))
    page._controls()
    assert page.table.rowCount() >= 29
    assert page.table.item(page.table.rowCount() - 1, 2).text() == "₹150.00"  # totals row


def test_custom_range_and_bad_range(win, shop):
    factory, ids = shop
    seed(factory, ids)
    win.nav_buttons["reports"].click()
    page = win.pages["reports"]
    page.period.setCurrentIndex(page.period.findData("custom"))
    page._controls()
    assert page.to_d.isEnabled()
    today = ist_today()
    page.from_d.setDate(page.to_d.date())  # same day
    page.to_d.setDate(page.from_d.date().addDays(-1))
    assert page.report is None and "before" in page.summary.text() and not page.pdf_btn.isEnabled()
    page.to_d.setDate(page.from_d.date().addDays(2))
    assert page.report is not None and page.pdf_btn.isEnabled()


def test_period_controls_only_for_reports_that_need_them(win, shop):
    win.nav_buttons["reports"].click()
    page = win.pages["reports"]
    page.which.setCurrentIndex(page.which.findData("outstanding"))
    page._controls()
    assert not page.period.isEnabled() and not page.from_d.isEnabled()
    page.which.setCurrentIndex(page.which.findData("expenses"))
    page._controls()
    assert page.period.isEnabled()


def test_save_pdf_and_excel_through_the_buttons(win, shop, tmp_path, monkeypatch):
    factory, ids = shop
    seed(factory, ids)
    win.nav_buttons["reports"].click()
    page = win.pages["reports"]
    pdf, xlsx = tmp_path / "out.pdf", tmp_path / "out.xlsx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(pdf), ""))
    page.pdf_btn.click()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(xlsx), ""))
    page.xlsx_btn.click()
    text = pymupdf.open(pdf)[0].get_text()
    assert "Sri Xerox" in text and "Sales report" in text and "₹150.00" in text
    ws = load_workbook(xlsx).active
    assert ws["A1"].value == "Sri Xerox" and "saved" in page.notes.text().lower()


def test_save_cancelled_or_unwritable(win, shop, tmp_path, monkeypatch):
    win.nav_buttons["reports"].click()
    page = win.pages["reports"]
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    page.pdf_btn.click()  # cancelled: nothing happens
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda p, t, text, *a, **k: shown.append(text))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(tmp_path / "no" / "such" / "dir" / "x.xlsx"), ""))
    page.xlsx_btn.click()
    assert shown and "Could not save" in shown[0]


def test_reports_in_telugu(win, shop):
    factory, ids = shop
    seed(factory, ids)
    win.nav_buttons["reports"].click()
    win.set_language("te")
    page = win.pages["reports"]
    te = Translator("te").tr
    assert page.which.itemText(0) == te("report.sales") and page.pdf_btn.text() == te("reports.pdf")
    assert page.table.horizontalHeaderItem(0).text() == te("report.c_date")
    assert te("report.s_sales") in page.summary.text()


# ---- backup page -------------------------------------------------------------------------------

def test_backup_now_lists_the_file_and_check_says_it_is_good(win, shop, tmp_path):
    factory, ids = shop
    sell(factory, ids, "a")
    win.nav_buttons["backup"].click()
    page = win.pages["backup"]
    assert page.table.rowCount() == 0 and "No backup" in page.last.text()
    page.now_btn.click()
    assert page.table.rowCount() == 1 and page.table.item(0, 1).text() == "Manual"
    assert (tmp_path / "backups" / page.table.item(0, 3).text()).is_file()
    assert "Backup saved" in page.status.text() and "Last backup" in page.last.text()
    page.table.selectRow(0)
    page.check_btn.click()
    assert "good: 1 bills" in page.status.text()


def test_restore_replaces_data_and_reloads_every_screen(win, shop, monkeypatch):
    factory, ids = shop
    sell(factory, ids, "one")
    win.nav_buttons["backup"].click()
    page = win.pages["backup"]
    page.now_btn.click()
    sell(factory, ids, "two")
    with session_scope(factory) as s:
        s.get(ShopSettings, 1).preferred_language = "te"
        s.get(ShopSettings, 1).shop_name = "Changed"
    win.nav_buttons["new_bill"].click()
    win.pages["new_bill"].new_bill.add_service_line(ids["Xerox / Photocopy"], Decimal(3))  # a half-made bill
    win.nav_buttons["backup"].click()
    page.table.selectRow(0)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    page.restore_btn.click()
    with session_scope(factory) as s:
        assert s.query(Bill).count() == 1 and s.get(ShopSettings, 1).shop_name == "Sri Xerox"
    assert win.shop_label.text() == "Sri Xerox"  # header reloaded from the restored data
    assert win._t.language == "en"  # language came back with the data
    assert win.pages["new_bill"].new_bill._drafts == []  # no stale half-made bill
    assert "safety copy" in page.status.text()
    assert page.table.rowCount() == 2 and {page.table.item(r, 1).text() for r in range(2)} == {
        "Manual", "Safety copy before restore"}


def test_restore_declined_changes_nothing(win, shop, monkeypatch):
    factory, ids = shop
    win.nav_buttons["backup"].click()
    page = win.pages["backup"]
    page.now_btn.click()
    sell(factory, ids, "later")
    page.table.selectRow(0)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    page.restore_btn.click()
    with session_scope(factory) as s:
        assert s.query(Bill).count() == 1
    assert page.table.rowCount() == 1


def test_restore_with_pin(win, shop, monkeypatch):
    factory, ids = shop
    win.nav_buttons["backup"].click()
    page = win.pages["backup"]
    page.now_btn.click()
    sell(factory, ids, "later")
    with session_scope(factory) as s:
        auth_service.set_pin(s, "1234")
    page.table.selectRow(0)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda p, t, text, *a, **k: shown.append(text))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("0000", True))
    page.restore_btn.click()
    assert shown and "PIN" in shown[0]
    with session_scope(factory) as s:
        assert s.query(Bill).count() == 1  # not restored
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("1234", True))
    page.restore_btn.click()
    with session_scope(factory) as s:
        assert s.query(Bill).count() == 0


def test_a_bad_file_is_rejected_before_any_warning_about_replacing_data(win, shop, tmp_path, monkeypatch):
    factory, ids = shop
    sell(factory, ids, "keep me")
    bad = tmp_path / "junk.db"
    bad.write_bytes(b"not a database")
    win.nav_buttons["backup"].click()
    page = win.pages["backup"]
    asked, shown = [], []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(1) or QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda p, t, text, *a, **k: shown.append(text))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(bad), ""))
    page.restore_file_btn.click()
    assert not asked and shown and "not a valid" in shown[0]
    with session_scope(factory) as s:
        assert s.query(Bill).count() == 1


def test_export_and_change_folder(win, shop, tmp_path, monkeypatch):
    win.nav_buttons["backup"].click()
    page = win.pages["backup"]
    usb = tmp_path / "usb"
    usb.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(usb))
    page.export_btn.click()
    assert len(list(usb.glob("*-export.db"))) == 1 and "Copied to" in page.status.text()
    assert page.table.rowCount() == 0  # exports do not clutter the main backup folder
    newdir = tmp_path / "moved"
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(newdir))
    page.folder_btn.click()
    assert str(newdir) in page.folder.text() and newdir.is_dir()


def test_folder_inside_the_data_folder_is_flagged(win, shop, monkeypatch):
    win.nav_buttons["backup"].click()
    page = win.pages["backup"]
    inside = config.db_path().parent / "backups"
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(inside))
    page.folder_btn.click()
    assert "same drive area" in page.warning.text()


def test_unwritable_backup_folder_shows_an_error(win, shop, tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    factory, _ = shop
    with session_scope(factory) as s:
        s.get(ShopSettings, 1).backup_dir = str(blocker / "sub")
    win.nav_buttons["backup"].click()
    page = win.pages["backup"]
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda p, t, text, *a, **k: shown.append(text))
    page.now_btn.click()
    assert shown and "Cannot write" in shown[0] and page.status.objectName() == "statusError"


def test_dashboard_reminds_when_backups_are_stale(win, shop):
    win.nav_buttons["dashboard"].click()
    dash = win.pages["dashboard"]
    assert "No backup" in dash.backup_banner.text()
    win.nav_buttons["backup"].click()
    win.pages["backup"].now_btn.click()
    win.nav_buttons["dashboard"].click()
    assert dash.backup_banner.text() == ""


def test_backup_page_in_telugu(win, shop):
    win.set_language("te")
    te = Translator("te").tr
    page = win.pages["backup"]
    assert page.now_btn.text() == te("backup.now") and page.restore_btn.text() == te("backup.restore")
