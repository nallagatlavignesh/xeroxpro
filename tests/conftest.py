import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # before any Qt import

import pytest

from database.bootstrap import open_database


@pytest.fixture
def db(tmp_path):
    """Fresh migrated + seeded database. Yields (engine, session_factory)."""
    engine, factory = open_database(tmp_path / "test.db")
    yield engine, factory
    engine.dispose()


T0 = "2026-01-01T00:00:00"  # fixed clocks make rate history deterministic


def clock(iso: str):
    return lambda: iso


@pytest.fixture
def shop(db):
    """db + rates set for the seeded services (₹2 xerox, ₹5 B&W, ₹10 colour, ₹20 lamination)."""
    from application.services import catalog_service
    from database.connection import session_scope
    from database.models import Service

    _, factory = db
    ids = {}
    with session_scope(factory) as s:
        for name, rate in [("Xerox / Photocopy", 200), ("B&W Printing", 500), ("Colour Printing", 1000),
                           ("Lamination", 2000)]:
            sid = s.query(Service).filter_by(service_name=name).one().id
            catalog_service.set_rate(s, sid, rate, clock(T0))
            ids[name] = sid
    return factory, ids


@pytest.fixture(autouse=True)
def no_real_printers(monkeypatch):
    """Tests never touch the machine's real printers (slow CUPS probing on Linux, and not what is under test)."""
    from infrastructure.printers.fake import FakePrinterGateway
    monkeypatch.setattr("ui.main_window.QtPrinterGateway", FakePrinterGateway)


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Nothing in the test suite may read or write the real user data/backup folders."""
    monkeypatch.setenv("XEROXPRO_DATA_DIR", str(tmp_path / "appdata"))


@pytest.fixture(scope="session")
def qapp():
    """One QApplication with the theme applied once for the whole run (a fresh theme per module made later modules slower)."""
    from PySide6.QtWidgets import QApplication
    from ui.theme import apply_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app
