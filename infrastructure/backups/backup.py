"""SQLite-safe backups and restores. No Qt, no SQLAlchemy: plain files + sqlite3.

Rules: a backup is written to `<name>.tmp`, verified, then renamed (so a crash leaves only a `.tmp` that is ignored);
an existing backup is never overwritten; a restore always saves the current data first and swaps the file last.
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from business.errors import DomainError
from business.timeutil import IST

KINDS = ("auto", "manual", "export", "pre_restore")
_NAME = re.compile(r"^xeroxpro-(\d{8})-(\d{6})-(auto|manual|export|pre_restore)(?:-(\d+))?\.db$")
_REQUIRED_TABLES = {"app_metadata", "shop_settings", "bills", "payments", "customers", "customer_ledger"}
ANY_SCHEMA = 10**9


class BackupError(DomainError):
    pass


@dataclass(frozen=True)
class BackupFile:
    path: Path
    created: datetime  # IST, from the file name
    kind: str
    size: int


@dataclass(frozen=True)
class BackupCheck:
    ok: bool
    error_key: str | None = None
    schema_version: int | None = None
    bills: int = 0
    customers: int = 0


def validate_backup(path: Path | str, max_schema: int) -> BackupCheck:
    """Open read-only and check the file really is a complete XeroxPro database this app can use."""
    path = Path(path)
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return BackupCheck(False, "backup.invalid")
        con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return BackupCheck(False, "backup.invalid")
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not _REQUIRED_TABLES <= tables:
                return BackupCheck(False, "backup.invalid")
            if con.execute("PRAGMA foreign_key_check").fetchall():
                return BackupCheck(False, "backup.invalid")
            row = con.execute("SELECT value FROM app_metadata WHERE key='schema_version'").fetchone()
            version = int(row[0])
            if version > max_schema:
                return BackupCheck(False, "backup.too_new", version)
            return BackupCheck(True, None, version, con.execute("SELECT COUNT(*) FROM bills").fetchone()[0],
                               con.execute("SELECT COUNT(*) FROM customers").fetchone()[0])
        finally:
            con.close()
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return BackupCheck(False, "backup.invalid")


def _name(now: datetime, kind: str) -> str:
    return f"xeroxpro-{now:%Y%m%d-%H%M%S}-{kind}.db"


def _unique(directory: Path, name: str) -> Path:
    """Never reuse a name: two backups in the same second get -1, -2 ..."""
    target = directory / name
    stem, n = target.stem, 0
    while target.exists():
        n += 1
        target = directory / f"{stem}-{n}.db"
    return target


def _free_space_ok(directory: Path, needed: int) -> bool:
    return shutil.disk_usage(directory).free >= needed * 2 + 1_000_000


def create_backup(db_path: Path | str, dest_dir: Path | str, kind: str = "manual", now: datetime | None = None) -> BackupFile:
    """Consistent copy of the live database (sqlite3 backup API), verified before it gets its final name."""
    db_path, dest_dir = Path(db_path), Path(dest_dir)
    if kind not in KINDS:
        raise ValueError(kind)
    now = now or datetime.now(IST)
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        if not os.access(dest_dir, os.W_OK):
            raise OSError("not writable")
    except OSError:
        raise BackupError("backup.dest_unwritable") from None
    if not db_path.is_file():
        raise BackupError("backup.failed", detail="database file not found")
    if not _free_space_ok(dest_dir, db_path.stat().st_size):
        raise BackupError("backup.no_space")
    final = _unique(dest_dir, _name(now, kind))
    tmp = final.with_name(final.name + ".tmp")
    src = dst = None
    try:
        src, dst = sqlite3.connect(db_path), sqlite3.connect(tmp)
        src.backup(dst)
        dst.execute("PRAGMA journal_mode=DELETE")  # one self-contained file, safe to copy to a USB stick
        dst.commit()
        dst.close()
        dst = None
        with open(tmp, "rb+") as handle:
            os.fsync(handle.fileno())
        check = validate_backup(tmp, ANY_SCHEMA)
        if not check.ok:
            raise BackupError("backup.failed", detail="the new copy failed verification")
        os.replace(tmp, final)
    except BackupError:
        tmp.unlink(missing_ok=True)
        raise
    except (sqlite3.Error, OSError) as exc:
        tmp.unlink(missing_ok=True)
        raise BackupError("backup.failed", detail=str(exc)) from None
    finally:
        for con in (src, dst):
            if con is not None:
                con.close()
    return BackupFile(final, now, kind, final.stat().st_size)


def list_backups(directory: Path | str) -> list[BackupFile]:
    """Backups found in the folder, newest first. Half-written `.tmp` files are not listed."""
    directory = Path(directory)
    found: list[tuple[int, BackupFile]] = []
    if directory.is_dir():
        for p in directory.iterdir():
            m = _NAME.match(p.name)
            if m and p.is_file():
                created = datetime.strptime(m[1] + m[2], "%Y%m%d%H%M%S").replace(tzinfo=IST)
                found.append((int(m[4] or 0), BackupFile(p, created, m[3], p.stat().st_size)))
    # same-second backups carry -1, -2 ...: a higher number is newer
    return [b for _, b in sorted(found, key=lambda t: (t[1].created, t[0]), reverse=True)]


def remove_stale_tmp(directory: Path | str) -> int:
    """Delete leftovers of backups that were interrupted (power cut, crash)."""
    count = 0
    for p in Path(directory).glob("xeroxpro-*.db.tmp"):
        p.unlink(missing_ok=True)
        count += 1
    return count


def prune_auto(directory: Path | str, keep: int = 30) -> list[Path]:
    """Keep the newest `keep` automatic backups. Manual/export/pre-restore copies are never touched, and the
    newest valid backup of any kind is never removed."""
    backups = list_backups(directory)
    newest_valid = next((b for b in backups if validate_backup(b.path, ANY_SCHEMA).ok), None)
    autos = [b for b in backups if b.kind == "auto"]
    removed = []
    for b in autos[max(keep, 1):]:
        if newest_valid and b.path == newest_valid.path:
            continue
        b.path.unlink(missing_ok=True)
        removed.append(b.path)
    return removed


def restore_backup(backup_path: Path | str, db_path: Path | str, safety_dir: Path | str, max_schema: int,
                   now: datetime | None = None) -> BackupFile | None:
    """Replace the live database with a verified backup. The caller must have closed every connection to `db_path`.

    Returns the safety copy of the data that was replaced (None if there was no database yet).
    """
    backup_path, db_path = Path(backup_path), Path(db_path)
    check = validate_backup(backup_path, max_schema)
    if not check.ok:
        raise BackupError(check.error_key)
    safety = create_backup(db_path, safety_dir, "pre_restore", now) if db_path.is_file() else None
    staging = db_path.with_name(db_path.name + ".restoring")
    src = dst = None
    try:
        src = sqlite3.connect(f"{backup_path.resolve().as_uri()}?mode=ro", uri=True)
        dst = sqlite3.connect(staging)
        src.backup(dst)
        dst.commit()
        dst.close()
        dst = None
        if not validate_backup(staging, max_schema).ok:
            raise BackupError("backup.invalid")
        for suffix in ("-wal", "-shm"):  # leftovers of the old database must not be replayed onto the new one
            Path(str(db_path) + suffix).unlink(missing_ok=True)
        os.replace(staging, db_path)
    except BackupError:
        staging.unlink(missing_ok=True)
        raise
    except (sqlite3.Error, OSError) as exc:
        staging.unlink(missing_ok=True)
        raise BackupError("backup.failed", detail=str(exc)) from None
    finally:
        for con in (src, dst):
            if con is not None:
                con.close()
    return safety
