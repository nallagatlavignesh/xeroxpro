"""Tiny migration runner: numbered `NNNN_name.sql` files applied in order, each in one transaction.

shortcut: SQL-only migrations, add Python migrations when a data transform needs real code.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)
DEFAULT_DIR = Path(__file__).parent
_NAME = re.compile(r"^(\d{4})_.+\.sql$")


class SchemaTooNewError(Exception):
    def __init__(self, db_version: int, app_version: int) -> None:
        super().__init__(f"database schema v{db_version} is newer than this app (v{app_version})")
        self.db_version = db_version
        self.app_version = app_version


def _available(directory: Path) -> list[tuple[int, Path]]:
    found = sorted((int(m.group(1)), p) for p in directory.glob("*.sql") if (m := _NAME.match(p.name)))
    return found


def current_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT value FROM app_metadata WHERE key='schema_version'").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row[0]) if row else 0


def latest_version(directory: Path = DEFAULT_DIR) -> int:
    return max((v for v, _ in _available(directory)), default=0)


def migrate(db_path: Path | str, directory: Path = DEFAULT_DIR, backup_dir: Path | None = None) -> int:
    """Bring the database to the latest schema. Returns the resulting version.

    Raises SchemaTooNewError (and touches nothing) if the DB is newer than this app.
    Before changing an existing database, a copy is written to backup_dir.
    """
    db_path = Path(db_path)
    migrations = _available(directory)
    latest = migrations[-1][0] if migrations else 0
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        version = current_version(conn)
        if version > latest:
            raise SchemaTooNewError(version, latest)
        pending = [(v, p) for v, p in migrations if v > version]
        if not pending:
            return version
        if version > 0:
            _backup_before(conn, db_path, version, backup_dir or db_path.parent / "pre-migration")
        for number, path in pending:
            log.info("applying migration %s", path.name)
            script = (
                "BEGIN;\n"
                f"{path.read_text(encoding='utf-8')}\n"
                "INSERT INTO app_metadata(key, value) VALUES('schema_version', '%d') "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value;\n"
                "COMMIT;"
            ) % number
            try:
                conn.executescript(script)
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
        return current_version(conn)
    finally:
        conn.close()


def _backup_before(conn: sqlite3.Connection, db_path: Path, version: int, backup_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{db_path.stem}-pre-migration-v{version}-{datetime.now():%Y%m%d-%H%M%S}.db"
    dest = sqlite3.connect(target)
    try:
        conn.backup(dest)
    finally:
        dest.close()
