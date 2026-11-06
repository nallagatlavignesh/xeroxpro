import pytest
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from application.services import settings_service
from application.services.i18n import Translator
from database.connection import session_scope
from ui.main_window import NAV, MainWindow
from ui.theme import apply_theme


@pytest.fixture
def window(qapp, db):
    _, factory = db
    w = MainWindow(factory, Translator("en"))
    w.show()
    yield w
    w.close()


def test_eleven_pages_and_navigation(window):
    assert len(NAV) == 11 and window.stack.count() == 11
    for index, (key, _) in enumerate(NAV):
        window.nav_buttons[key].click()
        assert window.stack.currentIndex() == index
        assert window.nav_buttons[key].isChecked()
        assert sum(b.isChecked() for b in window.nav_buttons.values()) == 1  # one active indicator


def test_starts_on_dashboard_with_english_labels(window):
    assert window.stack.currentIndex() == 0
    assert window.nav_buttons["new_bill"].text() == "New Bill"
    assert window.shop_label.text() == "XeroxPro"


def test_ampersand_is_shown_not_eaten_as_shortcut(window):
    assert window.nav_buttons["customers"].text() == "Customers && Udhar"  # && renders as a literal &
    assert window.nav_buttons["backup"].text() == "Backup && Restore"


def test_language_switch_relabels_everything_and_persists(window, db):
    te = Translator("te")
    window.lang_combo.setCurrentIndex(1)
    window.set_language("te")
    for key, tkey in NAV:
        assert window.nav_buttons[key].text() == te.tr(tkey).replace("&", "&&")
        assert window.pages[key].title.text() == te.tr(tkey)
    assert window.lang_combo.currentData() == "te"
    _, factory = db
    with session_scope(factory) as s:
        assert settings_service.get_shop_settings(s).preferred_language == "te"


def test_settings_page_saves_shop_name_and_updates_header(window, db):
    page = window.pages["settings"]
    page.shop_name.setText("Sri Lakshmi Xerox")
    page.phone.setText("98480 00000")
    page._save()
    assert window.shop_label.text() == "Sri Lakshmi Xerox"
    _, factory = db
    with session_scope(factory) as s:
        row = settings_service.get_shop_settings(s)
        assert (row.shop_name, row.phone) == ("Sri Lakshmi Xerox", "98480 00000")


def test_settings_page_rejects_empty_shop_name(window, db):
    page = window.pages["settings"]
    page.shop_name.setText("  ")
    page._save()
    assert page.status.objectName() == "statusError"
    assert "required" in page.status.text()
    assert window.shop_label.text() == "XeroxPro"


def test_settings_language_selector_switches_app(window):
    page = window.pages["settings"]
    page.language.setCurrentIndex(1)
    page.language_chosen.emit(page.language.currentData())
    assert window.lang_combo.currentData() == "te"
    assert window.nav_buttons["settings"].text() == Translator("te").tr("nav.settings")


def test_telugu_font_is_bundled_and_loaded(qapp):
    assert "Noto Sans Telugu" in QFontDatabase.families()


def test_fits_1366x768(window):
    assert window.width() <= 1366 and window.height() <= 768
