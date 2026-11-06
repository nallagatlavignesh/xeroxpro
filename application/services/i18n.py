"""Translations from resources/translations/<lang>.json (flat key -> text). Falls back to English, then to the key."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import config

log = logging.getLogger(__name__)
LANGUAGES = ("en", "te")


class Translator:
    def __init__(self, language: str = "en", directory: Path | None = None) -> None:
        directory = directory or config.resource_path("translations")
        self._tables = {
            code: json.loads((directory / f"{code}.json").read_text(encoding="utf-8")) for code in LANGUAGES
        }
        self.language = "en"
        self.set_language(language)

    def set_language(self, code: str) -> None:
        if code not in self._tables:
            raise ValueError(f"unsupported language: {code}")
        self.language = code

    def tr(self, key: str, **params: object) -> str:
        text = self._tables[self.language].get(key) or self._tables["en"].get(key)
        if text is None:
            log.warning("missing translation key: %s", key)
            return key
        try:
            return text.format(**params) if params else text
        except (KeyError, IndexError):
            log.warning("bad parameters for translation key %s: %s", key, params)
            return text
