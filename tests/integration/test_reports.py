from datetime import date, datetime
from decimal import Decimal

import pymupdf
import pytest
from openpyxl import load_workbook
from PySide6.QtGui import QGuiApplication
from sqlalchemy import text

from application.services import accounting_queries as aq
from application.services import customer_service, expense_service, inventory_service, job_service, reports
from application.services.i18n import Translator
from application.use_cases.cancel_bill import cancel_bill
from application.use_cases.record_payment import record_customer_payment
from application.use_cases.save_bill import BillRequest, LineRequest, save_bill
from business.billing import PaymentInput
from business.errors import ValidationError
from business.report_model import format_value, period_range
from database.connection import session_scope
from infrastructure.exports import excel, report_pdf

D = Decimal


@pytest.fixture(scope="module", autouse=True)
def qt():
    return QGuiApplication.instance() or QGuiApplication([])


def at(iso):
    return lambda: iso


def line(ids, pages, name="Xerox / Photocopy", rate=200):
    return LineRequest(D(pages), "page", rate, service_id=ids[name])


@pytest.fixture
def busy(shop):
    """Three days of mixed activity: cash/UPI/credit bills, a discount, a cancellation, udhar recovery,
    a job advance, expenses and stock."""
    factory, ids = shop
    with session_scope(factory) as s:
        a, b = (customer_service.create_customer(s, n, "9848012345").id for n in ("Anil", "Bhanu"))
        d1, d2, d3 = "2026-02-10T08:00:00", "2026-02-11T08:00:00", "2026-02-12T08:00:00"
        save_bill(s, BillRequest("1", [line(ids, 50)], payments=[PaymentInput(10000, "cash")]), at(d1))  # Rs100 cash
        save_bill(s, BillRequest("2", [line(ids, 50), line(ids, 2, "Lamination", 2000)], discount=1000,
                                 payments=[PaymentInput(5000, "upi")], customer_id=a), at(d1))  # Rs140-10, Rs50 paid
        gone = save_bill(s, BillRequest("3", [line(ids, 25)], payments=[PaymentInput(5000, "cash")]), at(d2))
        cancel_bill(s, gone.bill_id, "mistake", clock=at(d2))
        save_bill(s, BillRequest("4", [line(ids, 100)], customer_id=b), at(d2))  # Rs200 on credit
        record_customer_payment(s, a, 4000, "cash", "pay1", clock=at(d3))
        save_bill(s, BillRequest("5", [line(ids, 10, "B&W Printing", 500)], payments=[PaymentInput(5000, "upi")]), at(d3))
        job_service.create_job(s, b, "wedding cards", "Printing", 30000, 10000, "cash", "j1", clock=at(d2))
        expense_service.add_expense(s, "Paper", "ream", 3000, "cash", "2026-02-10")
        expense_service.add_expense(s, "Electricity", "", 7000, "upi", "2026-02-11")
        voided = expense_service.add_expense(s, "Other", "typo", 999, "cash", "2026-02-11")
        expense_service.void_expense(s, voided.id, "typo")
        p = inventory_service.create_product(s, "Pen", "Stationery", "item", 500, 1000, D(5))
        inventory_service.purchase(s, p.id, D(3), 500)
    return factory, ids


RANGE = (date(2026, 2, 10), date(2026, 2, 12))


def test_period_ranges():
    assert period_range("day", date(2026, 2, 12)) == (date(2026, 2, 12),) * 2
    assert period_range("week", date(2026, 2, 12)) == (date(2026, 2, 9), date(2026, 2, 15))  # Mon..Sun
    assert period_range("week", date(2026, 2, 15)) == (date(2026, 2, 9), date(2026, 2, 15))
    assert period_range("month", date(2026, 2, 12)) == (date(2026, 2, 1), date(2026, 2, 28))
    assert period_range("month", date(2024, 2, 5)) == (date(2024, 2, 1), date(2024, 2, 29))
    assert period_range("month", date(2026, 12, 31)) == (date(2026, 12, 1), date(2026, 12, 31))
    with pytest.raises(ValidationError):
        period_range("year", date(2026, 1, 1))


def test_sales_report_reconciles_with_raw_transactions(busy):
    factory, _ = busy
    with session_scope(factory) as s:
        r = reports.sales_report(s, *RANGE)
        assert [row[0] for row in r.rows] == ["10-02-2026", "11-02-2026", "12-02-2026"]
        # columns: date, bills, sales, cash, upi, other, refunds, expenses, cash movement
        d1, d2, d3 = r.rows
        assert d1[1:] == [2, 10000 + 13000, 10000, 5000, 0, 0, 3000, 7000]  # cash 100 - paper 30
        assert d2[1:] == [1, 20000, 5000 + 10000, 0, 0, 5000, 7000, 5000 + 10000 - 5000]  # cancelled bill: no sale; its cash refunded; job advance in
        assert d3[1:] == [1, 5000, 4000, 5000, 0, 0, 0, 4000]
        # the total row is the column sums, and equals independent raw SQL
        for col in range(1, 9):
            assert r.total_row[col] == sum(row[col] for row in r.rows)
        raw = s.execute(text("SELECT SUM(grand_total) FROM bills WHERE status NOT IN ('cancelled','refunded') "
                             "AND bill_date BETWEEN '2026-02-10' AND '2026-02-12'")).scalar()
        assert r.total_row[2] == raw == 48000
        rec = s.execute(text("SELECT SUM(CASE kind WHEN 'payment' THEN amount ELSE -amount END) FROM payments "
                             "WHERE payment_date BETWEEN '2026-02-10' AND '2026-02-12'")).scalar()
        summary = {l.label: l.value for l in r.summary}
        assert summary["report.s_received"] == rec
        assert summary["pay.cash"] + summary["pay.upi"] + summary["pay.other"] == rec
        assert summary["report.s_sales"] == raw
        assert summary["report.s_sales"] != summary["report.s_received"]  # sold on credit is not money received
        assert summary["report.s_expenses"] == 10000  # voided expense excluded
        assert summary["report.s_cash_movement"] == r.total_row[8]
        assert summary["report.s_profit"] == aq.estimated_profit(s, "2026-02-10", "2026-02-12")
        assert summary["report.s_credit_now"] == customer_service.total_outstanding(s) == 4000 + 20000  # Anil 130-50-40, Bhanu 200


def test_single_day_and_each_day_matches_the_dashboard_numbers(busy):
    factory, _ = busy
    with session_scope(factory) as s:
        for day in (date(2026, 2, 10), date(2026, 2, 11), date(2026, 2, 12)):
            row = reports.sales_report(s, day, day).rows[0]
            sm = aq.day_summary(s, day.isoformat())
            assert row[1:4] == [sm.bill_count, sm.sales, sm.collections.collected["cash"]]
            assert row[8] == sm.cash_movement


def test_service_sales_report_ties_back_to_sales(busy):
    factory, _ = busy
    with session_scope(factory) as s:
        r = reports.service_sales_report(s, *RANGE)
        names = [row[0] for row in r.rows]
        assert names[0] == "Xerox / Photocopy" and "Lamination" in names and "B&W Printing" in names
        xerox = r.rows[0]  # 50 + 50 + 100 pages (cancelled bill excluded)
        assert (xerox[1], xerox[2], xerox[3]) == (D(200), 3, 40000)
        summary = {l.label: l.value for l in r.summary}
        assert summary["report.s_items"] - 1000 == summary["report.s_sales"]  # one Rs10 discount
        assert summary["report.s_sales"] == reports.sales_report(s, *RANGE).total_row[2]


def test_cash_and_upi_collection_reports_are_separate(busy):
    factory, _ = busy
    with session_scope(factory) as s:
        cash = reports.collections_report(s, *RANGE, "cash")
        upi = reports.collections_report(s, *RANGE, "upi")
        assert [(r[1], r[3], r[4]) for r in cash.rows if r[3] == "report.k_refund"] == [("2026-000003", "report.k_refund", -5000)]
        assert cash.total_row[4] == 10000 + 5000 - 5000 + 4000 + 10000 == 24000  # incl. udhar payment and job advance
        assert upi.total_row[4] == 5000 + 5000
        assert not any(r[4] < 0 for r in upi.rows)
        c = {l.label: l.value for l in cash.summary}
        assert c["report.s_cash_movement"] == 24000 - 3000  # minus the cash expense
        assert "report.s_cash_movement" not in {l.label for l in upi.summary}
        assert any(r[1].startswith("J2026") for r in cash.rows)  # job advance is a cash collection
        with pytest.raises(ValidationError):
            reports.collections_report(s, *RANGE, "cheque")


def test_outstanding_report_matches_ledger(busy):
    factory, _ = busy
    with session_scope(factory) as s:
        r = reports.outstanding_report(s)
        assert [(row[0], row[2], row[4]) for row in r.rows] == [("Bhanu", 1, 20000), ("Anil", 1, 4000)]
        assert r.rows[1][3] == "10-02-2026"
        assert r.total_row[4] == customer_service.total_outstanding(s)


def test_expense_report_excludes_voided_and_groups(busy):
    factory, _ = busy
    with session_scope(factory) as s:
        r = reports.expense_report(s, *RANGE)
        assert [row[1] for row in r.rows] == ["Paper", "Electricity"] and r.total_row[4] == 10000
        cats = {l.label: l.value for l in r.summary if not l.translate}
        assert cats == {"Electricity": 7000, "Paper": 3000}


def test_inventory_and_job_reports(busy):
    factory, _ = busy
    with session_scope(factory) as s:
        inv = reports.inventory_report(s)
        assert inv.rows[0][0] == "Pen" and inv.rows[0][7] == "report.k_low" and inv.total_row[6] == inventory_service.stock_value(s)
        jobs = reports.job_status_report(s, *RANGE)
        assert [r[0] for r in jobs.rows] == ["J2026-00001"] and jobs.rows[0][8] == "jobs.status_received"
        counts = {l.label: l.value for l in jobs.summary}
        assert counts["jobs.status_received"] == 1 and counts["jobs.status_delivered"] == 0
        assert reports.job_status_report(s, date(2026, 3, 1), date(2026, 3, 2)).rows == []


def test_bad_range_rejected(busy):
    factory, _ = busy
    with session_scope(factory) as s:
        with pytest.raises(ValidationError) as e:
            reports.sales_report(s, date(2026, 2, 12), date(2026, 2, 10))
        assert e.value.key == "report.range_invalid"


def test_empty_database_reports_are_empty_not_errors(db):
    _, f = db
    with session_scope(f) as s:
        r = reports.sales_report(s, date(2026, 2, 10), date(2026, 2, 11))
        assert [row[1:] for row in r.rows] == [[0] * 8, [0] * 8]
        assert reports.outstanding_report(s).rows == [] and reports.service_sales_report(s, *RANGE).rows == []


def test_format_value():
    assert format_value(12345678, "money") == "₹1,23,456.78"
    assert format_value(D("2.500"), "qty") == "2.5" and format_value(None, "money") == "" and format_value(3, "int") == "3"
    assert format_value("pay.cash", "key", Translator("en").tr) == "Cash"


# ---- exports -----------------------------------------------------------------------------------

def all_reports(s):
    return [reports.sales_report(s, *RANGE), reports.service_sales_report(s, *RANGE),
            reports.collections_report(s, *RANGE, "cash"), reports.collections_report(s, *RANGE, "upi"),
            reports.collections_report(s, *RANGE, "other"), reports.outstanding_report(s),
            reports.expense_report(s, *RANGE), reports.inventory_report(s), reports.job_status_report(s, *RANGE)]


@pytest.mark.parametrize("lang", ["en", "te"])
def test_every_report_exports_to_pdf_and_excel(busy, tmp_path, lang):
    factory, _ = busy
    tr = Translator(lang).tr
    with session_scope(factory) as s:
        for r in all_reports(s):
            pdf, xlsx = tmp_path / f"{r.key}.pdf", tmp_path / f"{r.key}.xlsx"
            report_pdf.write_pdf(r, tr, "Sri Xerox", datetime(2026, 2, 13, 9, 0), pdf)
            excel.write_excel(r, tr, "Sri Xerox", datetime(2026, 2, 13, 9, 0), xlsx)
            doc = pymupdf.open(pdf)
            assert len(doc) >= 1 and doc[0].get_text().strip(), r.key
            ws = load_workbook(xlsx).active
            assert ws.max_row > len(r.rows), r.key
            assert ws["A1"].value == "Sri Xerox"


def test_pdf_has_figures_and_orientation(busy, tmp_path):
    factory, _ = busy
    tr = Translator("en").tr
    with session_scope(factory) as s:
        r = reports.sales_report(s, *RANGE)
    path = tmp_path / "s.pdf"
    report_pdf.write_pdf(r, tr, "Sri Xerox", datetime(2026, 2, 13, 9, 0), path)
    doc = pymupdf.open(path)
    text_ = doc[0].get_text()
    for expected in ("Sri Xerox", "Sales report", "10-02-2026 – 12-02-2026", "₹480.00", "Estimated", "Cash movement"):
        assert expected in text_, expected
    assert doc[0].rect.width > doc[0].rect.height  # 9 columns -> landscape
    out = pymupdf.open(path)
    assert any("Telugu" in f[3] for f in pymupdf.open(path)[0].get_fonts()) is False  # English report: no Telugu font needed


def test_telugu_pdf_embeds_telugu_font(busy, tmp_path):
    factory, _ = busy
    with session_scope(factory) as s:
        r = reports.outstanding_report(s)
    path = tmp_path / "te.pdf"
    report_pdf.write_pdf(r, Translator("te").tr, "శ్రీ జిరాక్స్", datetime(2026, 2, 13), path)
    assert any("Telugu" in f[3] for f in pymupdf.open(path)[0].get_fonts())


def test_long_report_repeats_header_on_each_page(busy, tmp_path):
    factory, _ = busy
    with session_scope(factory) as s:
        r = reports.sales_report(s, date(2026, 1, 1), date(2026, 12, 31))  # 365 rows
    path = tmp_path / "long.pdf"
    report_pdf.write_pdf(r, Translator("en").tr, "X", datetime(2026, 2, 13), path)
    doc = pymupdf.open(path)
    assert len(doc) >= 5 and all("Cash movement" in p.get_text() for p in list(doc)[:-1])  # last page may hold only the notes


def test_excel_money_is_numeric_and_totals_are_present(busy, tmp_path):
    factory, _ = busy
    with session_scope(factory) as s:
        r = reports.sales_report(s, *RANGE)
    path = tmp_path / "s.xlsx"
    excel.write_excel(r, Translator("en").tr, "Sri Xerox", datetime(2026, 2, 13), path)
    ws = load_workbook(path).active
    header = next(row for row in ws.iter_rows() if row[0].value == "Date")
    first = ws.cell(row=header[0].row + 1, column=3)
    assert first.value == 230 and first.number_format == '"₹"#,##0.00'  # Rs230, a number, not text
    total = ws.cell(row=header[0].row + 1 + len(r.rows), column=3)
    assert total.value == 480 and total.font.bold
    assert ws.freeze_panes == f"A{header[0].row + 1}"
    labels = {row[0].value: row[1].value for row in ws.iter_rows(min_row=1, max_row=header[0].row) if row[0].value}
    assert labels["Sales (amount billed)"] == 480 and labels["Money received (after refunds)"] == 340


def test_excel_keeps_telugu_text(busy, tmp_path):
    factory, _ = busy
    with session_scope(factory) as s:
        r = reports.expense_report(s, *RANGE)
    path = tmp_path / "te.xlsx"
    excel.write_excel(r, Translator("te").tr, "శ్రీ లక్ష్మి జిరాక్స్", datetime(2026, 2, 13), path)
    ws = load_workbook(path).active
    assert ws["A1"].value == "శ్రీ లక్ష్మి జిరాక్స్" and ws["A2"].value == Translator("te").tr("report.expenses")
