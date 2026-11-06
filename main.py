"""XeroxPro entry point."""
from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

import config
from application.services import backup_service
from application.services.i18n import Translator
from application.services.logging_setup import setup_logging
from application.services import settings_service
from database.bootstrap import open_database
from database.connection import session_scope
from database.migrations.runner import SchemaTooNewError
from ui import single_instance
from ui.errors import install_excepthook
from ui.main_window import MainWindow
from ui.theme import apply_theme

log = logging.getLogger("xeroxpro")


def main() -> int:
    if "--selftest" in sys.argv:  # packaging/installation check; touches no real data (see selftest.py)
        import selftest

        args = [a for a in sys.argv[2:] if not a.startswith("--")]
        return selftest.run(args[0] if args else None, skip_printers="--skip-printers" in sys.argv)
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    apply_theme(app)
    translator = Translator("en")

    lock = single_instance.acquire(config.data_dir() / "xeroxpro.lock")
    if lock is None:
        QMessageBox.warning(None, config.APP_NAME, translator.tr("error.already_running"))
        return 1

    install_excepthook(translator)

    try:
        engine, factory = open_database()
    except SchemaTooNewError:
        QMessageBox.critical(None, translator.tr("common.error"), translator.tr("error.db_too_new"))
        return 2
    with session_scope(factory) as s:
        translator.set_language(settings_service.get_shop_settings(s).preferred_language)

    backup_service.run_auto_backup_if_due(engine, factory)  # one automatic backup per day
    window = MainWindow(factory, translator)
    window.show()
    daily = QTimer()  # the shop PC may stay on past midnight
    daily.timeout.connect(lambda: backup_service.run_auto_backup_if_due(engine, factory))
    daily.start(60 * 60 * 1000)
    app.aboutToQuit.connect(lambda: backup_service.run_exit_backup(engine, factory))
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
