import json
import string

import pytest

import config
from application.services.i18n import Translator

DIR = config.resource_path("translations")
en = json.loads((DIR / "en.json").read_text(encoding="utf-8"))
te = json.loads((DIR / "te.json").read_text(encoding="utf-8"))


def placeholders(text: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


def test_same_keys():
    assert set(en) == set(te)


def test_no_empty_strings():
    assert all(v.strip() for v in en.values()) and all(v.strip() for v in te.values())


def test_same_placeholders():
    assert {k: placeholders(v) for k, v in en.items()} == {k: placeholders(v) for k, v in te.items()}


def test_telugu_is_actually_telugu():
    # catches an English string pasted into te.json; these are brand names / language names
    latin_only = {k for k, v in te.items() if not any("ఀ" <= ch <= "౿" for ch in v)}
    assert latin_only == {"lang.en", "pay.upi"}


def test_switching_and_fallback():
    t = Translator("en")
    assert t.tr("nav.dashboard") == "Dashboard"
    t.set_language("te")
    assert t.tr("nav.dashboard") == te["nav.dashboard"]
    assert t.tr("no.such.key") == "no.such.key"
    assert t.tr("validation.required", field="X").startswith("X")
    with pytest.raises(ValueError):
        t.set_language("fr")
