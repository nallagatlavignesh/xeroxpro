"""`XeroxPro.exe --selftest [report.txt] [--skip-printers]`

Exercises every moving part that a bad packaging or a bad PC could break (bundled files, database + migrations,
Telugu PDF, Excel, backup/restore, printers, building every screen) in a throw-away data folder, then exits 0 or 1.
A windowed exe has no console, so results can be written to a file.
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from datetime import datetime
from decimal import Decimal
from pathlib import Path


def run(report_path: str | None = None, skip_printers: bool = False) -> int:
    lines: list[str] = []
    failures = 0

    def step(name, fn):
        nonlocal failures
        try:
            detail = fn() or ""
            lines.append(f"OK    {name} {detail}".rstrip())
        except Exception as exc:  # report every failure, do not stop at the first
            failures += 1
            lines.append(f"FAIL  {name}: {type(exc).__name__}: {exc}")
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            lines.append(f"      at {Path(frame.filename).name}:{frame.lineno} in {frame.name}")

    with tempfile.TemporaryDirectory(prefix="xeroxpro-selftest-") as tmp:
        tmp = Path(tmp)
        os.environ["XEROXPRO_DATA_DIR"] = str(tmp / "data")
        ctx: dict = {}

        def resources():
            import config
            for name in ("NotoSans-Regular.ttf", "NotoSans-Bold.ttf", "NotoSansTelugu-Regular.ttf",
                         "NotoSansTelugu-Bold.ttf"):
                assert config.resource_path("fonts", name).is_file(), f"missing font {name}"
            for name in ("en.json", "te.json"):
                assert config.resource_path("translations", name).is_file(), f"missing {name}"
            assert config.resource_path("styles", "app.qss").is_file()
            return f"(app {config.APP_VERSION})"

        def translations():
            from application.services.i18n import Translator
            en, te = Translator("en"), Translator("te")
            assert en.tr("nav.dashboard") == "Dashboard" and te.tr("nav.dashboard") != "Dashboard"
            assert te.tr("nav.dashboard") != "nav.dashboard"

        def database():
            from database.bootstrap import open_database
            from database.migrations.runner import latest_version
            from database.connection import session_scope
            from database.models import Service
            import config
            engine, factory = open_database(config.db_path())
            ctx["engine"], ctx["factory"] = engine, factory
            with session_scope(factory) as s:
                assert s.query(Service).count() == 8
            with engine.connect() as c:
                version = c.exec_driver_sql("SELECT value FROM app_metadata WHERE key='schema_version'").scalar()
            assert int(version) == latest_version() >= 2, version
            return f"(schema v{version})"

        def bill_and_receipt():
            from PySide6.QtGui import QGuiApplication
            import pymupdf
            from application.services import catalog_service, receipt_service
            from application.services.i18n import Translator
            from application.use_cases.save_bill import BillRequest, LineRequest, save_bill
            from business.billing import PaymentInput
            from database.connection import session_scope
            from infrastructure.pdf import receipt
            assert QGuiApplication.instance() is not None
            with session_scope(ctx["factory"]) as s:
                svc = catalog_service.list_services(s)[0]
                catalog_service.set_rate(s, svc.id, 200)
                saved = save_bill(s, BillRequest("selftest", [LineRequest(Decimal(25), "page", 200, 2, service_id=svc.id)],
                                                 payments=[PaymentInput(10000, "cash")]))
                data = receipt_service.build_receipt_data(s, saved.bill_id)
            pdf = tmp / "receipt-te.pdf"
            receipt.write_pdf(data, Translator("te").tr, pdf)
            doc = pymupdf.open(pdf)
            assert len(doc) == 1 and any("Telugu" in f[3] for f in doc[0].get_fonts()), "Telugu font not embedded"
            ctx["bill_id"] = saved.bill_id

        def reports_and_exports():
            from datetime import date
            from application.services import reports
            from application.services.i18n import Translator
            from database.connection import session_scope
            from infrastructure.exports import excel, report_pdf
            import pymupdf
            from openpyxl import load_workbook
            with session_scope(ctx["factory"]) as s:
                r = reports.sales_report(s, date.today(), date.today())
            tr = Translator("te").tr
            report_pdf.write_pdf(r, tr, "XeroxPro", datetime.now(), tmp / "r.pdf")
            excel.write_excel(r, tr, "XeroxPro", datetime.now(), tmp / "r.xlsx")
            assert len(pymupdf.open(tmp / "r.pdf")) >= 1 and load_workbook(tmp / "r.xlsx").active["A1"].value == "XeroxPro"

        def backup_roundtrip():
            import config
            from application.services import backup_service
            from application.services.auth_service import has_pin  # noqa: F401  (import check)
            from database.connection import session_scope
            from database.models import Bill
            engine, factory = ctx["engine"], ctx["factory"]
            b = backup_service.run_backup(engine, factory, "manual", dest=tmp / "backups")
            assert backup_service.check(b.path).ok
            backup_service.restore(engine, factory, b.path, None)
            with session_scope(factory) as s:
                assert s.query(Bill).count() == 1

        def printers():
            if skip_printers:
                return "(skipped)"
            from infrastructure.printers.gateway import QtPrinterGateway
            gw = QtPrinterGateway()
            rows = gw.list_printers()
            for r in rows:
                gw.capabilities(r.name)
            return f"({len(rows)} printer(s) found)"

        def window():
            from application.services.i18n import Translator
            from infrastructure.printers.fake import FakePrinterGateway
            from ui.main_window import MainWindow
            from ui.theme import apply_theme
            from PySide6.QtWidgets import QApplication
            apply_theme(QApplication.instance())
            gateway = FakePrinterGateway() if skip_printers else None
            w = MainWindow(ctx["factory"], Translator("en"), gateway)
            w.set_language("te")
            w.set_language("en")
            assert w.stack.count() == 11
            w.close()

        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        for name, fn in (("bundled files", resources), ("translations", translations), ("database + migrations", database),
                         ("bill + Telugu receipt PDF", bill_and_receipt), ("reports PDF + Excel", reports_and_exports),
                         ("backup + restore", backup_roundtrip), ("printers", printers), ("all screens", window)):
            step(name, fn)
        if "engine" in ctx:
            ctx["engine"].dispose()
        del app

    lines.append("SELFTEST " + ("PASSED" if not failures else f"FAILED ({failures} problem(s))"))
    text = "\n".join(lines) + "\n"
    if report_path:
        Path(report_path).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 1 if failures else 0
