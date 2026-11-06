"""Backup use cases: manual, daily automatic, export to another folder, restore."""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

import config
from application.services import auth_service, settings_service
from business.errors import DomainError, ValidationError
from business.timeutil import IST, ist_today, utc_now_iso
from database.connection import session_scope
from database.migrations.runner import latest_version, migrate
from database.models import AuditLog, BackupHistory
from infrastructure.backups import backup as engine_backup
from infrastructure.backups.backup import BackupError, BackupFile

log = logging.getLogger(__name__)
STALE_AFTER_DAYS = 2


def db_path_of(engine: Engine) -> Path:
    return Path(engine.url.database)


def backup_dir(session: Session) -> Path:
    configured = settings_service.get_shop_settings(session).backup_dir
    return Path(configured) if configured else config.default_backup_dir()


def set_backup_dir(session: Session, folder: str) -> Path:
    """Remember a backup folder after proving we can write to it."""
    path = Path(folder.strip()) if folder.strip() else None
    if path is None:
        raise ValidationError("validation.required", field_key="backup.folder")
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".xeroxpro-write-test"
        probe.write_text("ok")
        probe.unlink()
    except OSError:
        raise BackupError("backup.dest_unwritable") from None
    settings_service.get_shop_settings(session).backup_dir = str(path)
    return path


def is_inside_data_dir(folder: Path, engine: Engine) -> bool:
    """A backup next to the live database is lost together with it."""
    try:
        folder.resolve().relative_to(db_path_of(engine).resolve().parent)
        return True
    except ValueError:
        return False


def _record(factory: sessionmaker, kind: str, status: str, path: str, size: int, message: str = "") -> None:
    with session_scope(factory) as s:
        s.add(BackupHistory(file_path=path, kind=kind, status=status, size_bytes=size, message=message))


def run_backup(engine: Engine, factory: sessionmaker, kind: str = "manual", dest: Path | None = None,
               keep: int = 60) -> BackupFile:
    """Back up the live database. Failures are logged and recorded, then re-raised for the screen to show."""
    with session_scope(factory) as s:
        folder = dest or backup_dir(s)
    try:
        engine_backup.remove_stale_tmp(folder)
        result = engine_backup.create_backup(db_path_of(engine), folder, kind)
    except DomainError as err:
        log.error("backup failed (%s): %s %s", kind, err.key, err.params)
        _record(factory, kind, "failed", str(folder), 0, f"{err.key} {err.params}")
        raise
    _record(factory, kind, "ok", str(result.path), result.size)
    if kind == "auto":
        engine_backup.prune_auto(folder, keep)
    return result


def run_auto_backup_if_due(engine: Engine, factory: sessionmaker, today=None) -> BackupFile | None:
    """One automatic backup per day (checked against the files actually in the folder). Safe to call often."""
    today = today or ist_today()
    with session_scope(factory) as s:
        folder = backup_dir(s)
    if any(b.kind == "auto" and b.created.date() == today for b in engine_backup.list_backups(folder)):
        return None
    try:
        return run_backup(engine, factory, "auto")
    except DomainError:
        return None  # already logged and recorded; the dashboard banner tells the owner when backups go stale


def run_exit_backup(engine: Engine, factory: sessionmaker, now: datetime | None = None,
                    min_gap_hours: int = 4) -> BackupFile | None:
    """When the app closes: capture the day's work, unless an automatic backup was made in the last few hours
    (so repeated restarts do not pile up copies)."""
    now = now or datetime.now(IST)
    with session_scope(factory) as s:
        autos = [b for b in list_all(s) if b.kind == "auto"]
    if autos and (now - autos[0].created).total_seconds() < min_gap_hours * 3600:
        return None
    try:
        return run_backup(engine, factory, "auto")
    except DomainError:
        return None


def list_all(session: Session) -> list[BackupFile]:
    return engine_backup.list_backups(backup_dir(session))


def newest_backup(session: Session) -> BackupFile | None:
    return next((b for b in list_all(session) if b.kind in ("auto", "manual")), None)


def is_stale(session: Session, now: datetime | None = None) -> bool:
    """No automatic/manual backup for STALE_AFTER_DAYS days (or ever)."""
    newest = newest_backup(session)
    now = now or datetime.now(IST)
    return newest is None or (now - newest.created).days >= STALE_AFTER_DAYS


def check(path: Path | str) -> engine_backup.BackupCheck:
    return engine_backup.validate_backup(path, latest_version())


def restore(engine: Engine, factory: sessionmaker, backup_path: Path | str, pin: str | None) -> BackupFile | None:
    """Replace all current data with a backup. Needs the owner PIN when one is set.

    Order: verify backup -> authorise -> save current data aside -> close connections -> swap file ->
    upgrade schema if the backup is older -> note it in the audit log.
    """
    result = check(backup_path)
    if not result.ok:
        raise BackupError(result.error_key)
    with session_scope(factory) as s:
        auth_service.require_authorized(s, pin)
        safety_dir = backup_dir(s)
    db_path = db_path_of(engine)
    engine.dispose()  # no open file handles while the file is replaced (Windows would refuse otherwise)
    safety = engine_backup.restore_backup(backup_path, db_path, safety_dir, latest_version())
    migrate(db_path)
    with session_scope(factory) as s:
        s.add(AuditLog(action="backup_restored", entity_type="database", entity_id=None, at=utc_now_iso(),
                       reason="restored from backup", details=json.dumps({
                           "file": str(backup_path), "safety_copy": str(safety.path) if safety else None})))
        if safety:
            s.add(BackupHistory(file_path=str(safety.path), kind="pre_restore", status="ok", size_bytes=safety.size))
    return safety
