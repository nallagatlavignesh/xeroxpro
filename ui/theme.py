"""Fonts and stylesheet. Segoe UI for Latin on Windows; bundled Noto Sans Telugu so Telugu never depends on the PC."""
from __future__ import annotations

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

import config
from infrastructure.pdf.receipt import ensure_fonts


def apply_theme(app: QApplication) -> None:
    ensure_fonts()  # once per process: registering the same fonts again only slows Qt's font database down
    font = QFont()
    font.setFamilies(["Segoe UI", "Noto Sans", "Noto Sans Telugu", "Nirmala UI"])
    font.setPointSize(11)
    app.setFont(font)
    app.setWindowIcon(QIcon(str(config.resource_path("icons", "xeroxpro.png"))))
    qss = config.resource_path("styles", "app.qss").read_text(encoding="utf-8")
    qss = qss.replace("@ICONS@", config.resource_path("icons").as_posix())  # QSS url() needs forward slashes
    if app.styleSheet() != qss:  # re-applying an identical stylesheet re-polishes every widget: slow once many exist
        app.setStyleSheet(qss)
