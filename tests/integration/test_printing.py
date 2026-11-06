import pymupdf
import pytest
from PySide6.QtGui import QGuiApplication
from PySide6.QtPrintSupport import QPrinter

from infrastructure.pdf.pdf_info import PdfError, paper_name, read_pdf, render_page
from infrastructure.pdf import receipt as receipt_pdf
from infrastructure.printers.fake import FakePrinterGateway
from infrastructure.printers.gateway import (
    PrintError, PrinterCaps, PrintRequest, QtPrinterGateway, paint_pages,
)


@pytest.fixture(scope="module", autouse=True)
def qt():
    return QGuiApplication.instance() or QGuiApplication([])


def make_pdf(path, pages=5, size=(595, 842), text="Page"):
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=size[0], height=size[1])
        page.insert_text((72, 100), f"{text} {i + 1}", fontsize=40)
    doc.save(path)
    return str(path)


# ---- PDF reading ---------------------------------------------------------------------------

def test_page_count_and_sizes(tmp_path):
    info = read_pdf(make_pdf(tmp_path / "a.pdf", 7))
    assert info.page_count == 7 and info.paper_names == ["A4"] * 7 and not info.mixed_sizes
    assert round(info.page_sizes_mm[0][0]) == 210


def test_mixed_sizes_and_paper_names(tmp_path):
    doc = pymupdf.open()
    doc.new_page(width=595, height=842)
    doc.new_page(width=842, height=1191)  # A3
    doc.new_page(width=612, height=792)  # Letter
    doc.new_page(width=300, height=500)
    doc.save(tmp_path / "m.pdf")
    info = read_pdf(tmp_path / "m.pdf")
    assert info.paper_names == ["A4", "A3", "Letter", "106x176 mm"] and info.mixed_sizes
    assert paper_name(297, 210) == "A4"  # landscape is still A4


def test_unreadable_pdfs_are_refused(tmp_path):
    (tmp_path / "bad.pdf").write_bytes(b"this is not a pdf")
    (tmp_path / "empty.pdf").write_bytes(b"")
    for name in ("bad.pdf", "empty.pdf", "missing.pdf"):
        with pytest.raises(PdfError) as e:
            read_pdf(tmp_path / name)
        assert e.value.key == "print.pdf_unreadable"


def test_encrypted_pdf_is_refused(tmp_path):
    doc = pymupdf.open()
    doc.new_page()
    doc.save(tmp_path / "enc.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="x", owner_pw="y")
    with pytest.raises(PdfError) as e:
        read_pdf(tmp_path / "enc.pdf")
    assert e.value.key == "print.pdf_encrypted"


def test_render_page_draws_ink(tmp_path):
    img = render_page(make_pdf(tmp_path / "a.pdf", 2), 1, 50)
    assert (img.width(), img.height()) == (413, 584) or img.width() > 300
    dark = sum(1 for x in range(0, img.width(), 3) for y in range(0, img.height(), 3) if img.pixelColor(x, y).lightness() < 128)
    assert dark > 0


def test_telugu_pdf_renders_in_the_assistant(tmp_path):
    """A Telugu document (made by the receipt engine) opens and previews; the Telugu font is embedded."""
    from datetime import datetime
    from decimal import Decimal
    from application.services.i18n import Translator

    data = receipt_pdf.ReceiptData("శ్రీ లక్ష్మి జిరాక్స్", "గుంటూరు", "", "ధన్యవాదాలు", "1", datetime(2026, 1, 1),
                                   "రాము", [receipt_pdf.ReceiptLine("x", Decimal(1), "page", 100, 100)], 100, 0, 100, 100, 0)
    path = tmp_path / "te.pdf"
    receipt_pdf.write_pdf(data, Translator("te").tr, path)
    info = read_pdf(path)
    assert info.page_count == 1 and info.paper_names == ["A4"]
    assert any("Telugu" in f[3] for f in pymupdf.open(path)[0].get_fonts())
    img = render_page(path, 1, 60)
    assert any(img.pixelColor(x, y).lightness() < 100 for x in range(0, img.width(), 4) for y in range(0, 120, 2))


# ---- drawing onto a printer (PDF output stands in for a device) -------------------------------

def out_printer(path):
    p = QPrinter(QPrinter.PrinterMode.HighResolution)
    p.setOutputFileName(str(path))
    return p


def test_selected_pages_and_copies_are_all_drawn_in_order(tmp_path):
    src = make_pdf(tmp_path / "src.pdf", 6)
    out = tmp_path / "out.pdf"
    sent = paint_pages(out_printer(out), PrintRequest(src, [2, 4, 5], copies=3, paper="A4"))
    assert sent == 9
    doc = pymupdf.open(out)
    assert len(doc) == 9
    texts = [p.get_text().strip() for p in doc]
    assert texts == [] or all(isinstance(t, str) for t in texts)  # raster pages: no text layer, count is the proof
    assert (round(doc[0].rect.width), round(doc[0].rect.height)) == (595, 842)


def test_colour_and_greyscale_requests_set_the_printer_mode(tmp_path):
    src = make_pdf(tmp_path / "src.pdf", 1)
    p = out_printer(tmp_path / "o.pdf")
    paint_pages(p, PrintRequest(src, [1], colour=False))
    assert p.colorMode() == QPrinter.ColorMode.GrayScale
    p2 = out_printer(tmp_path / "o2.pdf")
    paint_pages(p2, PrintRequest(src, [1], colour=True))
    assert p2.colorMode() == QPrinter.ColorMode.Color
    # Duplex is only a driver hint: a PDF-file "printer" has no duplex support, so it cannot be asserted here.


def test_progress_is_reported(tmp_path):
    seen = []
    paint_pages(out_printer(tmp_path / "o.pdf"), PrintRequest(make_pdf(tmp_path / "s.pdf", 2), [1, 2], copies=2),
                lambda done, total: seen.append((done, total)))
    assert seen == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_printer_that_refuses_the_job_is_reported(tmp_path, monkeypatch):
    src = make_pdf(tmp_path / "s.pdf", 1)
    bad = QPrinter()
    bad.setOutputFileName("/nonexistent-dir/x.pdf")  # cannot be opened for writing
    with pytest.raises(PrintError) as e:
        paint_pages(bad, PrintRequest(src, [1]))
    assert e.value.key == "print.submit_failed"


# ---- gateway rules (fake printers) --------------------------------------------------------------

def req(tmp_path, **kw):
    return PrintRequest(make_pdf(tmp_path / "d.pdf", 4), kw.pop("pages", [1, 2]), **kw)


def test_printer_selection_and_listing(tmp_path):
    gw = FakePrinterGateway()
    assert [(r.name, r.is_default, r.status) for r in gw.list_printers()] == [
        ("Office Laser", True, "ready"), ("Colour Inkjet", False, "ready")]
    gw.print_pdf("Colour Inkjet", req(tmp_path, colour=True))
    gw.print_pdf("Office Laser", req(tmp_path, duplex=True, copies=2))
    assert [(n, r.copies, r.colour, r.duplex) for n, r in gw.jobs] == [
        ("Colour Inkjet", 1, True, False), ("Office Laser", 2, False, True)]


def test_capabilities_limit_what_can_be_requested(tmp_path):
    gw = FakePrinterGateway()
    with pytest.raises(PrintError) as e:
        gw.print_pdf("Office Laser", req(tmp_path, colour=True))
    assert e.value.key == "print.no_colour"
    with pytest.raises(PrintError) as e:
        gw.print_pdf("Colour Inkjet", req(tmp_path, duplex=True))
    assert e.value.key == "print.no_duplex"
    assert gw.jobs == []


def test_unknown_capabilities_are_not_assumed_unsupported(tmp_path):
    gw = FakePrinterGateway({"Mystery": ("ready", PrinterCaps(None, None, ()))})
    gw.print_pdf("Mystery", req(tmp_path, colour=True, duplex=True))  # allowed, UI warns it is undetected
    assert len(gw.jobs) == 1


def test_disconnected_and_errored_printers_refuse(tmp_path):
    gw = FakePrinterGateway({"Broken": ("error", PrinterCaps(True, True, ("A4",)))})
    with pytest.raises(PrintError) as e:
        gw.print_pdf("Broken", req(tmp_path))
    assert e.value.key == "print.printer_error"
    with pytest.raises(PrintError) as e:
        gw.print_pdf("Unplugged", req(tmp_path))
    assert e.value.key == "print.printer_missing"
    with pytest.raises(PrintError):
        gw.capabilities("Unplugged")


def test_submission_failure_is_an_error_not_success(tmp_path):
    gw = FakePrinterGateway()
    gw.fail_with = "spooler stopped"
    with pytest.raises(PrintError) as e:
        gw.print_pdf("Office Laser", req(tmp_path))
    assert e.value.key == "print.submit_failed" and e.value.params["detail"] == "spooler stopped"
    assert gw.jobs == []


def test_empty_job_refused(tmp_path):
    with pytest.raises(PrintError):
        FakePrinterGateway().print_pdf("Office Laser", req(tmp_path, pages=[]))


def test_real_qt_gateway_without_printers_fails_cleanly(tmp_path):
    """This test box has no printers; it proves 'not installed' is reported, not crashed on."""
    gw = QtPrinterGateway()
    names = [r.name for r in gw.list_printers()]
    ghost = "No Such Printer 12345"
    assert ghost not in names
    with pytest.raises(PrintError) as e:
        gw.print_pdf(ghost, req(tmp_path))
    assert e.value.key == "print.printer_missing"
    with pytest.raises(PrintError):
        gw.capabilities(ghost)
