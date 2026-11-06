"""Telugu/Latin glyph coverage of the bundled fonts, error messages, and the packaging self-test."""
import json
import sqlite3
import unicodedata

import pytest
from PySide6.QtGui import QFontDatabase, QRawFont
from PySide6.QtWidgets import QApplication
from sqlalchemy.exc import OperationalError

import config
from application.services.i18n import Translator
from ui import errors

FONTS = ["NotoSans-Regular.ttf", "NotoSans-Bold.ttf", "NotoSansTelugu-Regular.ttf", "NotoSansTelugu-Bold.ttf"]


@pytest.fixture(scope="module")
def qt():
    return QApplication.instance() or QApplication([])


def test_fonts_are_bundled_with_their_licence_notice():
    for name in FONTS:
        assert config.resource_path("fonts", name).stat().st_size > 50_000, name
    assert "SIL Open Font License" in config.resource_path("fonts", "NOTICE-NotoSans-OFL.txt").read_text()


@pytest.mark.parametrize("lang", ["en", "te"])
def test_every_character_we_display_exists_in_a_bundled_font(qt, lang):
    """No 'tofu' boxes: each visible character of every UI string must be drawable with the bundled fonts."""
    fonts = [QRawFont(str(config.resource_path("fonts", n)), 12) for n in FONTS]
    strings = json.loads((config.resource_path("translations") / f"{lang}.json").read_text(encoding="utf-8"))
    strings = list(strings.values()) + ["₹0123456789.,-+%:/·–›×−…()'\"&"]
    missing = {}
    for text in strings:
        for ch in text:
            if unicodedata.category(ch) in ("Cc", "Cf", "Zs") or ch in "{}\n":
                continue  # invisible/format characters (spaces, ZWNJ, ZWJ) need no glyph
            if not any(f.supportsCharacter(ord(ch)) for f in fonts):
                missing[ch] = f"U+{ord(ch):04X} in {text[:30]!r}"
    assert not missing, missing


def test_telugu_font_loads_under_the_expected_family_names(qt):
    ids = [QFontDatabase.addApplicationFont(str(config.resource_path("fonts", n))) for n in FONTS]
    assert all(i >= 0 for i in ids)
    families = set(QFontDatabase.families())
    assert {"Noto Sans", "Noto Sans Telugu"} <= families


def test_error_descriptions_are_friendly_and_translated():
    t = Translator("en").tr
    locked = OperationalError("INSERT", {}, sqlite3.OperationalError("database is locked"))
    assert errors.describe(locked)[0] == "error.db_locked"
    assert errors.describe(sqlite3.OperationalError("database or disk is full"))[0] == "error.disk_full"
    assert errors.describe(sqlite3.OperationalError("attempt to write a readonly database"))[0] == "error.db_readonly"
    key, params = errors.describe(ZeroDivisionError("x"))
    assert key == "error.unexpected" and "logs" in params["path"]
    for lang in ("en", "te"):
        tr = Translator(lang).tr
        for k in ("error.db_locked", "error.disk_full", "error.db_readonly"):
            assert tr(k) != k


def test_excepthook_logs_shows_a_dialog_and_never_raises(qt, monkeypatch, caplog):
    import sys
    from PySide6.QtWidgets import QMessageBox

    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda parent, title, text: shown.append(text))
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # restored after the test
    errors.install_excepthook(Translator("en"))
    with caplog.at_level("ERROR", logger="xeroxpro"):
        try:
            raise OperationalError("UPDATE", {}, sqlite3.OperationalError("database or disk is full"))
        except OperationalError:
            sys.excepthook(*sys.exc_info())
    assert shown and "disk is full" in shown[0] and "unhandled exception" in caplog.text
    # even if the dialog itself explodes, the hook swallows it (and logs) instead of crashing the app
    monkeypatch.setattr(QMessageBox, "critical", lambda *a: (_ for _ in ()).throw(RuntimeError("no display")))
    try:
        raise ValueError("boom")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    assert "could not show the error dialog" in caplog.text


# ---- the packaging self-test ------------------------------------------------------------------

def test_selftest_passes_and_writes_its_report(qt, tmp_path, monkeypatch):
    import selftest

    monkeypatch.setenv("XEROXPRO_DATA_DIR", str(tmp_path / "x"))
    report = tmp_path / "report.txt"
    code = selftest.run(str(report), skip_printers=True)
    text = report.read_text(encoding="utf-8")
    assert code == 0, text
    assert text.strip().endswith("SELFTEST PASSED") and text.count("OK ") >= 8 and "FAIL" not in text


def test_selftest_really_detects_a_broken_installation(qt, tmp_path, monkeypatch):
    """If a bundled file were missing the self-test must fail loudly, otherwise it proves nothing."""
    import selftest

    real = config.resource_path
    monkeypatch.setattr(config, "resource_path",
                        lambda *parts: tmp_path / "missing" if parts[:1] == ("fonts",) and len(parts) > 1 else real(*parts))
    monkeypatch.setenv("XEROXPRO_DATA_DIR", str(tmp_path / "x"))
    report = tmp_path / "bad.txt"
    assert selftest.run(str(report), skip_printers=True) == 1
    text = report.read_text(encoding="utf-8")
    assert "FAIL  bundled files" in text and text.strip().endswith("(s))") or "FAILED" in text


def test_selftest_flag_from_the_command_line(tmp_path):
    import os, subprocess, sys
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", XEROXPRO_DATA_DIR=str(tmp_path / "real-data"))
    out = tmp_path / "cli.txt"
    r = subprocess.run([sys.executable, str(config.resource_path().parent / "main.py"), "--selftest", str(out),
                        "--skip-printers"], env=env, capture_output=True, text=True, timeout=120,
                       cwd=str(config.resource_path().parent))
    assert r.returncode == 0, r.stderr[-500:]
    assert out.read_text().strip().endswith("SELFTEST PASSED")
    assert not (tmp_path / "real-data").exists()  # the self-test never touches the real data folder
