from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem,
)

from application.services import backup_service
from business.errors import DomainError
from database.connection import session_scope
from infrastructure.backups.backup import BackupFile
from ui.page import Page, amp, request_pin, show_domain_error


def _size(n: int) -> str:
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


class BackupPage(Page):
    restored = Signal()  # the data was replaced: other screens must reload

    def __init__(self, session_factory, translator) -> None:
        super().__init__("nav.backup", translator.tr)
        self._sf = session_factory
        self._engine = session_factory.kw["bind"]
        self._files: list[BackupFile] = []
        self.folder = QLabel()
        self.folder.setStyleSheet("font-weight: 700;")
        self.folder.setWordWrap(True)
        self.warning = QLabel()
        self.warning.setObjectName("statusError")
        self.warning.setWordWrap(True)
        self.last = QLabel()
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.help = QLabel()
        self.help.setObjectName("hint")
        self.help.setWordWrap(True)
        bar = QHBoxLayout()
        self.now_btn, self.export_btn, self.folder_btn = QPushButton(), QPushButton(), QPushButton()
        for b in (self.now_btn, self.export_btn, self.folder_btn):
            bar.addWidget(b)
        bar.addStretch(1)
        self.table = QTableWidget(0, 4)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        row2 = QHBoxLayout()
        self.check_btn, self.restore_btn, self.restore_file_btn = QPushButton(), QPushButton(), QPushButton()
        for b in (self.check_btn, self.restore_btn, self.restore_file_btn):
            row2.addWidget(b)
        row2.addStretch(1)
        for w in (self.folder, self.warning, self.last):
            self.layout_.addWidget(w)
        self.layout_.addLayout(bar)
        self.layout_.addWidget(self.status)
        self.layout_.addWidget(self.table, 1)
        self.layout_.addLayout(row2)
        self.layout_.addWidget(self.help)
        self.now_btn.clicked.connect(self._now)
        self.export_btn.clicked.connect(self._export)
        self.folder_btn.clicked.connect(self._change_folder)
        self.check_btn.clicked.connect(self._check)
        self.restore_btn.clicked.connect(lambda: self._restore(self._selected()))
        self.restore_file_btn.clicked.connect(self._restore_from_file)
        self.table.itemSelectionChanged.connect(self._buttons)
        self.retranslate()

    def on_show(self) -> None:
        self.reload()

    def _report(self, text: str, error: bool = False) -> None:
        self.status.setObjectName("statusError" if error else "status")
        self.status.setText(text)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _fail(self, err: DomainError) -> None:
        from ui.page import message_for

        self._report(message_for(err, self._tr), True)
        show_domain_error(self, err, self._tr)

    def reload(self) -> None:
        t = self._tr
        with session_scope(self._sf) as s:
            folder = backup_service.backup_dir(s)
            self._files = backup_service.list_all(s)
            newest = backup_service.newest_backup(s)
        self.folder.setText(f"{t('backup.folder')}: {folder}")
        self.warning.setText(t("backup.inside_data") if backup_service.is_inside_data_dir(folder, self._engine) else "")
        self.last.setText(t("backup.last", when=newest.created.strftime("%d-%m-%Y %H:%M")) if newest
                          else t("backup.none_yet"))
        self.table.setRowCount(len(self._files))
        for r, b in enumerate(self._files):
            cells = [b.created.strftime("%d-%m-%Y %H:%M:%S"), t(f"backup.kind_{b.kind}"), _size(b.size), b.path.name]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, c, item)
        self._buttons()

    def _selected(self) -> BackupFile | None:
        row = self.table.currentRow()
        return self._files[row] if 0 <= row < len(self._files) else None

    def _buttons(self) -> None:
        has = self._selected() is not None
        self.check_btn.setEnabled(has)
        self.restore_btn.setEnabled(has)

    # ---- actions ---------------------------------------------------------------------------------
    def _now(self) -> None:
        try:
            result = backup_service.run_backup(self._engine, self._sf, "manual")
        except DomainError as err:
            self._fail(err)
            return
        self._report(self._tr("backup.done", name=result.path.name))
        self.reload()

    def _export(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self._tr("backup.export"))
        if not folder:
            return
        try:
            result = backup_service.run_backup(self._engine, self._sf, "export", dest=Path(folder))
        except DomainError as err:
            self._fail(err)
            return
        self._report(self._tr("backup.exported", path=str(result.path)))

    def _change_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self._tr("backup.change_folder"))
        if not folder:
            return
        try:
            with session_scope(self._sf) as s:
                backup_service.set_backup_dir(s, folder)
        except DomainError as err:
            self._fail(err)
            return
        self.reload()

    def _check(self) -> None:
        b = self._selected()
        if b is None:
            return
        result = backup_service.check(b.path)
        if result.ok:
            self._report(self._tr("backup.valid", bills=result.bills, customers=result.customers))
        else:
            self._report(self._tr(result.error_key), True)

    def _restore_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self._tr("backup.restore_file"), "", "XeroxPro backup (*.db)")
        if path:
            self._restore(BackupFile(Path(path), datetime.fromtimestamp(Path(path).stat().st_mtime), "manual", 0))

    def _restore(self, backup: BackupFile | None) -> None:
        if backup is None:
            return
        t = self._tr
        result = backup_service.check(backup.path)  # verify before frightening the owner with a confirmation
        if not result.ok:
            self._report(t(result.error_key), True)
            QMessageBox.warning(self, t("common.error"), t(result.error_key))
            return
        ask = QMessageBox.question(self, t("backup.restore"),
                                   t("backup.confirm_restore", when=backup.created.strftime("%d-%m-%Y %H:%M")))
        if ask != QMessageBox.StandardButton.Yes:
            return
        proceed, pin = request_pin(self, self._sf, t)
        if not proceed:
            return
        try:
            safety = backup_service.restore(self._engine, self._sf, backup.path, pin)
        except DomainError as err:
            self._fail(err)
            return
        self.restored.emit()
        self._report(t("backup.restored", name=safety.path.name if safety else "-"))
        self.reload()

    def retranslate(self) -> None:
        super().retranslate()
        t = self._tr
        self.now_btn.setText(amp(t("backup.now")))
        self.export_btn.setText(amp(t("backup.export")))
        self.folder_btn.setText(amp(t("backup.change_folder")))
        self.check_btn.setText(amp(t("backup.check")))
        self.restore_btn.setText(amp(t("backup.restore")))
        self.restore_file_btn.setText(amp(t("backup.restore_file")))
        self.help.setText(t("backup.instructions"))
        self.table.setHorizontalHeaderLabels([t(k) for k in (
            "backup.col_when", "backup.col_type", "backup.col_size", "backup.col_file")])
        self.reload()

