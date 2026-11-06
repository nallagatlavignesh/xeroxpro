"""Last-resort error handling: log everything, tell the owner in plain words, never crash silently."""
from __future__ import annotations

import logging
import sys
import traceback

from PySide6.QtWidgets import QMessageBox

import config

log = logging.getLogger("xeroxpro")


def describe(exc: BaseException) -> tuple[str, dict]:
    """(translation key, params) for the message shown to the owner."""
    text = str(getattr(exc, "orig", exc)).lower()
    if "database is locked" in text:
        return "error.db_locked", {}
    if "disk is full" in text or "database or disk is full" in text:
        return "error.disk_full", {}
    if "readonly database" in text or "read-only" in text or "permission denied" in text:
        return "error.db_readonly", {}
    return "error.unexpected", {"path": str(config.log_dir())}


def install_excepthook(translator) -> None:
    """Route unhandled exceptions (including those raised inside Qt slots) to the log plus a friendly dialog."""

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.error("unhandled exception\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        key, params = describe(exc)
        try:
            QMessageBox.critical(None, translator.tr("common.error"), translator.tr(key, **params))
        except Exception:  # the dialog itself must never raise out of the hook
            log.exception("could not show the error dialog")

    sys.excepthook = hook
