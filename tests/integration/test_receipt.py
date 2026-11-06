from datetime import datetime
from decimal import Decimal

import pymupdf
import pytest
from PySide6.QtGui import QGuiApplication

from application.services import receipt_service
from application.services.i18n import Translator
from application.use_cases.cancel_bill import cancel_bill
from application.use_cases.save_bill import BillRequest, LineRequest, save_bill
from business.billing import PaymentInput
from database.connection import session_scope
from infrastructure.pdf.receipt import ReceiptData, ReceiptLine, write_pdf


@pytest.fixture(scope="module", autouse=True)
def qt():
    return QGuiApplication.instance() or QGuiApplication([])


def sample(n_lines=3, status="partial", phone="98480 00000"):
    lines = [ReceiptLine(f"Item {i}", Decimal(50), "page", 200, 10000) for i in range(n_lines)]
    total = 10000 * n_lines
    return ReceiptData("శ్రీ లక్ష్మి జిరాక్స్", "Main Road\nGuntur", phone, "ధన్యవాదాలు! Thank you.", "2026-000001",
                       datetime(2026, 2, 10, 13, 30), "రాము", lines, total, 500, total - 500, 5000,
                       total - 5500, [("cash", 3000), ("upi", 2000)], status)


def pdf(tmp_path, lang, data):
    path = tmp_path / f"r_{lang}.pdf"
    write_pdf(data, Translator(lang).tr, path)
    return pymupdf.open(path)


def test_english_receipt_is_one_a4_page_with_all_fields(tmp_path):
    doc = pdf(tmp_path, "en", sample())
    assert len(doc) == 1 and (round(doc[0].rect.width), round(doc[0].rect.height)) == (595, 842)
    text = doc[0].get_text()
    for expected in ["2026-000001", "₹300.00", "-₹5.00", "₹295.00", "₹50.00", "₹245.00", "Subtotal", "Discount",
                     "Balance due", "Cash ₹30.00, UPI ₹20.00", "10-02-2026", "Thank you",
                     "Phone: 98480 00000", "Item 2"]:
        assert expected in text, expected


def test_telugu_receipt_embeds_telugu_font_and_draws_ink(tmp_path):
    doc = pdf(tmp_path, "te", sample())
    fonts = {f[3] for f in doc[0].get_fonts()}
    assert any("NotoSansTelugu" in f for f in fonts), fonts
    # English and Telugu receipts must differ visibly (labels are translated, not left in English)
    en = pdf(tmp_path, "en", sample())[0].get_pixmap(dpi=50).samples
    te = doc[0].get_pixmap(dpi=50).samples
    assert en != te
    assert "Subtotal" not in doc[0].get_text() and "₹295.00" in doc[0].get_text()


def test_long_bill_paginates_and_repeats_header(tmp_path):
    doc = pdf(tmp_path, "en", sample(n_lines=120))
    assert len(doc) >= 3
    assert "Description" in doc[1].get_text()  # table header repeated on page 2
    all_text = "".join(p.get_text() for p in doc)
    assert "Item 119" in all_text
    assert "₹12,000.00" in all_text and "₹11,995.00" in all_text  # 120 x Rs100, less Rs5 discount


def test_phone_can_be_hidden(tmp_path):
    assert "Phone" not in pdf(tmp_path, "en", sample(phone=""))[0].get_text()


def test_receipt_from_stored_bill_and_cancelled_banner(shop, tmp_path):
    factory, ids = shop
    with session_scope(factory) as s:
        saved = save_bill(s, BillRequest("k", [LineRequest(Decimal(25), "page", 200, 2, service_id=ids["Xerox / Photocopy"])],
                                         payments=[PaymentInput(10000, "cash")]), lambda: "2026-02-10T08:00:00")
        data = receipt_service.build_receipt_data(s, saved.bill_id)
        assert (data.grand_total, data.total_paid, data.outstanding, data.status) == (10000, 10000, 0, "paid")
        assert data.created_at.strftime("%d-%m-%Y %H:%M") == "10-02-2026 13:30"  # UTC 08:00 -> IST 13:30
        assert data.lines[0].quantity == Decimal(50)
        cancel_bill(s, saved.bill_id, "test")
        cancelled = receipt_service.build_receipt_data(s, saved.bill_id)
    assert cancelled.status == "refunded" and cancelled.grand_total == 10000 and cancelled.outstanding == 0
    assert "CANCELLED" in pdf(tmp_path, "en", cancelled)[0].get_text()
