import os
import sqlite3
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import config
from application.services import auth_service, backup_service, customer_service
from application.use_cases.save_bill import BillRequest, LineRequest, save_bill
from business.billing import PaymentInput
from business.errors import AuthorizationError, ValidationError
from business.timeutil import IST
from database.bootstrap import open_database
from database.connection import session_scope
from database.migrations.runner import latest_version, migrate
from database.models import AuditLog, Bill, BackupHistory, ShopSettings
from infrastructure.backups import backup as bk
from infrastructure.backups.backup import BackupError

D = Decimal
NOW = datetime(2026, 2, 10, 14, 30, tzinfo=IST)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A migrated database with data, plus a backup folder (kept apart from the data folder)."""
    monkeypatch.setenv("XEROXPRO_DATA_DIR", str(tmp_path / "data"))
    engine, factory = open_database(config.db_path())
    with session_scope(factory) as s:
        from application.services import catalog_service
        from database.models import Service
        sid = s.query(Service).filter_by(service_name="Xerox / Photocopy").one().id
        catalog_service.set_rate(s, sid, 200, lambda: "2026-01-01T00:00:00")
        s.get(ShopSettings, 1).backup_dir = str(tmp_path / "backups")
        s.get(ShopSettings, 1).shop_name = "Sri Xerox"
    yield engine, factory, tmp_path
    engine.dispose()


def add_bill(factory, key, pages=50, paid=None):
    with session_scope(factory) as s:
        from database.models import Service
        sid = s.query(Service).filter_by(service_name="Xerox / Photocopy").one().id
        pay = [PaymentInput(pages * 200 if paid is None else paid, "cash")]
        save_bill(s, BillRequest(key, [LineRequest(D(pages), "page", 200, service_id=sid)], payments=pay),
                  lambda: "2026-02-10T08:00:00")


def count_bills(path):
    con = sqlite3.connect(path)
    try:
        return con.execute("SELECT COUNT(*) FROM bills").fetchone()[0]
    finally:
        con.close()


# ---- creating backups ----------------------------------------------------------------------

def test_backup_is_a_valid_timestamped_copy(env):
    engine, factory, tmp = env
    add_bill(factory, "a")
    b = bk.create_backup(config.db_path(), tmp / "backups", "manual", NOW)
    assert b.path.name == "xeroxpro-20260210-143000-manual.db" and b.size > 0
    check = bk.validate_backup(b.path, latest_version())
    assert (check.ok, check.schema_version, check.bills, check.customers) == (True, latest_version(), 1, 0)
    assert count_bills(b.path) == 1
    assert not list((tmp / "backups").glob("*.tmp"))
    # one self-contained file, not a WAL database that needs side files
    assert sqlite3.connect(b.path).execute("PRAGMA journal_mode").fetchone()[0] == "delete"


def test_backups_never_overwrite_each_other(env):
    _, factory, tmp = env
    first = bk.create_backup(config.db_path(), tmp / "b", "manual", NOW)
    add_bill(factory, "a")
    second = bk.create_backup(config.db_path(), tmp / "b", "manual", NOW)  # same second, same kind
    assert first.path != second.path and first.path.exists() and second.path.exists()
    assert count_bills(first.path) == 0 and count_bills(second.path) == 1
    names = [b.path.name for b in bk.list_backups(tmp / "b")]
    assert len(names) == 2 and names[0].endswith("-1.db")


def test_backup_while_the_app_is_connected_and_writing(env):
    engine, factory, tmp = env
    with session_scope(factory) as s:  # an open write transaction on the live database
        customer_service.create_customer(s, "Mid-transaction", "9848012345")
        b = bk.create_backup(config.db_path(), tmp / "b", "manual", NOW)
    assert bk.validate_backup(b.path, latest_version()).ok  # a consistent snapshot, uncommitted row not half-written


def test_unwritable_destination_and_missing_database(env):
    _, _, tmp = env
    blocker = tmp / "afile"
    blocker.write_text("x")
    with pytest.raises(BackupError) as e:
        bk.create_backup(config.db_path(), blocker / "sub", "manual", NOW)  # a "folder" under a file
    assert e.value.key == "backup.dest_unwritable"
    with pytest.raises(BackupError) as e:
        bk.create_backup(tmp / "nothing.db", tmp / "b", "manual", NOW)
    assert e.value.key == "backup.failed"


def test_not_enough_disk_space(env, monkeypatch):
    _, _, tmp = env
    monkeypatch.setattr(bk, "_free_space_ok", lambda *a: False)
    with pytest.raises(BackupError) as e:
        bk.create_backup(config.db_path(), tmp / "b", "manual", NOW)
    assert e.value.key == "backup.no_space" and not list((tmp / "b").glob("*.db"))


def test_interrupted_backup_leaves_no_partial_file_and_keeps_old_ones(env, monkeypatch):
    _, factory, tmp = env
    good = bk.create_backup(config.db_path(), tmp / "b", "manual", NOW)
    add_bill(factory, "a")

    def crash(*a, **k):
        raise OSError("power cut")

    monkeypatch.setattr(bk.os, "replace", crash)  # dies at the very last step
    with pytest.raises(BackupError):
        bk.create_backup(config.db_path(), tmp / "b", "manual", NOW + timedelta(minutes=1))
    assert [b.path for b in bk.list_backups(tmp / "b")] == [good.path]
    assert not list((tmp / "b").glob("*.tmp"))
    assert bk.validate_backup(good.path, latest_version()).ok


def test_stale_tmp_from_a_killed_backup_is_ignored_then_cleaned(env):
    _, factory, tmp = env
    folder = tmp / "b"
    folder.mkdir()
    (folder / "xeroxpro-20260210-100000-auto.db.tmp").write_bytes(b"half written")
    assert bk.list_backups(folder) == []
    assert bk.remove_stale_tmp(folder) == 1 and not list(folder.glob("*.tmp"))


# ---- validation: bad files must be rejected --------------------------------------------------

def bad_files(tmp: Path, good: Path) -> dict[str, Path]:
    data = good.read_bytes()
    files = {
        "empty": b"", "text": b"this is not a database at all",
        "truncated": data[: len(data) // 2], "random": os.urandom(8192),
        "header_only": data[:100],
    }
    corrupt = bytearray(data)
    for i in range(4096 * 2, min(len(corrupt), 4096 * 4)):  # scribble over table pages
        corrupt[i] = 0xFF
    files["corrupt_pages"] = bytes(corrupt)
    out = {}
    for name, content in files.items():
        out[name] = tmp / f"{name}.db"
        out[name].write_bytes(content)
    other = tmp / "other.db"  # a valid SQLite file that is not ours
    c = sqlite3.connect(other)
    c.execute("CREATE TABLE t(x)")
    c.commit()
    c.close()
    out["foreign_sqlite"] = other
    return out


def test_invalid_backups_are_rejected(env):
    _, factory, tmp = env
    add_bill(factory, "a")
    good = bk.create_backup(config.db_path(), tmp / "b", "manual", NOW)
    for name, path in bad_files(tmp, good.path).items():
        assert not bk.validate_backup(path, latest_version()).ok, name
    assert not bk.validate_backup(tmp / "does-not-exist.db", latest_version()).ok


def test_backup_from_a_newer_version_is_refused(env):
    _, _, tmp = env
    b = bk.create_backup(config.db_path(), tmp / "b", "manual", NOW)
    con = sqlite3.connect(b.path)
    con.execute("UPDATE app_metadata SET value='99' WHERE key='schema_version'")
    con.commit()
    con.close()
    check = bk.validate_backup(b.path, latest_version())
    assert (check.ok, check.error_key, check.schema_version) == (False, "backup.too_new", 99)


# ---- restore ---------------------------------------------------------------------------------

def test_backup_mutate_restore_gives_back_the_original_data(env):
    engine, factory, tmp = env
    add_bill(factory, "one")
    backup = backup_service.run_backup(engine, factory, "manual")
    add_bill(factory, "two")
    add_bill(factory, "three")
    with session_scope(factory) as s:
        s.get(ShopSettings, 1).shop_name = "Changed after backup"
    assert count_bills(config.db_path()) == 3

    safety = backup_service.restore(engine, factory, backup.path, None)

    with session_scope(factory) as s:  # the same engine/session factory keeps working after the swap
        assert s.query(Bill).count() == 1
        assert s.get(ShopSettings, 1).shop_name == "Sri Xerox"
        assert s.query(AuditLog).filter_by(action="backup_restored").count() == 1
    assert bk.validate_backup(config.db_path(), latest_version()).ok
    # the data that was replaced is still available in the safety copy
    assert safety is not None and safety.kind == "pre_restore" and count_bills(safety.path) == 3
    assert not Path(str(config.db_path()) + ".restoring").exists()


def test_restore_can_be_undone_from_the_safety_copy(env):
    engine, factory, tmp = env
    add_bill(factory, "one")
    backup = backup_service.run_backup(engine, factory, "manual")
    add_bill(factory, "two")
    safety = backup_service.restore(engine, factory, backup.path, None)
    backup_service.restore(engine, factory, safety.path, None)
    with session_scope(factory) as s:
        assert s.query(Bill).count() == 2


def test_invalid_backup_is_refused_and_current_data_untouched(env):
    engine, factory, tmp = env
    add_bill(factory, "one")
    good = backup_service.run_backup(engine, factory, "manual")
    for name, path in bad_files(tmp, good.path).items():
        with pytest.raises(BackupError):
            backup_service.restore(engine, factory, path, None)
    with session_scope(factory) as s:
        assert s.query(Bill).count() == 1
    assert [b.kind for b in bk.list_backups(tmp / "backups")] == ["manual"]  # no safety copy made for refused files


def test_restore_needs_the_pin_when_one_is_set(env):
    engine, factory, tmp = env
    add_bill(factory, "one")
    b = backup_service.run_backup(engine, factory, "manual")
    add_bill(factory, "two")
    with session_scope(factory) as s:
        auth_service.set_pin(s, "1234")
    for pin in (None, "0000"):
        with pytest.raises(AuthorizationError):
            backup_service.restore(engine, factory, b.path, pin)
    with session_scope(factory) as s:
        assert s.query(Bill).count() == 2  # nothing happened
    backup_service.restore(engine, factory, b.path, "1234")
    with session_scope(factory) as s:
        assert s.query(Bill).count() == 1


def test_restoring_an_older_schema_backup_upgrades_it(env):
    engine, factory, tmp = env
    v1 = tmp / "v1"
    (v1).mkdir()
    base = Path(config.resource_path().parent / "database" / "migrations")
    (v1 / "0001_baseline.sql").write_text((base / "0001_baseline.sql").read_text())
    old_db = tmp / "old.db"
    migrate(old_db, v1)
    con = sqlite3.connect(old_db)
    con.execute("INSERT INTO daily_closings(closing_date, expected_cash, counted_cash, difference, notes, created_at) "
                "VALUES ('2026-01-01', 1, 1, 0, '', '2026-01-01T00:00:00')")
    con.commit()
    con.close()
    backup_service.restore(engine, factory, old_db, None)
    con = sqlite3.connect(config.db_path())
    assert con.execute("SELECT value FROM app_metadata WHERE key='schema_version'").fetchone()[0] == str(latest_version())
    assert con.execute("SELECT closing_date, opening_cash FROM daily_closings").fetchall() == [("2026-01-01", 0)]
    con.close()


# ---- automatic daily backup, history, retention -------------------------------------------------

def test_auto_backup_runs_once_a_day(env):
    engine, factory, tmp = env
    first = backup_service.run_auto_backup_if_due(engine, factory)
    again = backup_service.run_auto_backup_if_due(engine, factory)
    assert first is not None and first.kind == "auto" and again is None
    with session_scope(factory) as s:
        assert s.query(BackupHistory).filter_by(kind="auto", status="ok").count() == 1
    # a different day is due again
    tomorrow = first.created.date() + timedelta(days=1)
    assert backup_service.run_auto_backup_if_due(engine, factory, today=tomorrow) is not None


def test_exit_backup_captures_the_days_work_but_not_every_restart(env):
    engine, factory, tmp = env
    morning = backup_service.run_auto_backup_if_due(engine, factory)
    add_bill(factory, "afternoon sale")
    assert backup_service.run_exit_backup(engine, factory, now=morning.created + timedelta(hours=1)) is None
    evening = backup_service.run_exit_backup(engine, factory, now=morning.created + timedelta(hours=9))
    assert evening is not None and count_bills(evening.path) == 1 and count_bills(morning.path) == 0


def test_auto_backup_failure_is_recorded_not_raised(env):
    engine, factory, tmp = env
    blocker = tmp / "afile"
    blocker.write_text("x")
    with session_scope(factory) as s:
        s.get(ShopSettings, 1).backup_dir = str(blocker / "sub")
    assert backup_service.run_auto_backup_if_due(engine, factory) is None
    with session_scope(factory) as s:
        row = s.query(BackupHistory).one()
        assert (row.kind, row.status) == ("auto", "failed") and "dest_unwritable" in row.message


def test_prune_keeps_recent_autos_and_never_touches_manual_copies(env):
    _, _, tmp = env
    folder = tmp / "b"
    for day in range(1, 8):
        bk.create_backup(config.db_path(), folder, "auto", NOW + timedelta(days=day))
    manual = bk.create_backup(config.db_path(), folder, "manual", NOW - timedelta(days=100))
    removed = bk.prune_auto(folder, keep=3)
    kinds = [(b.kind, b.created.day) for b in bk.list_backups(folder)]
    assert len(removed) == 4
    assert [k for k, _ in kinds].count("auto") == 3 and manual.path.exists()
    assert [d for k, d in kinds if k == "auto"] == [17, 16, 15]  # the newest three survive


def test_prune_never_removes_the_only_valid_backup(env):
    _, _, tmp = env
    folder = tmp / "b"
    newest = bk.create_backup(config.db_path(), folder, "auto", NOW)
    for i in range(3):  # older, but corrupt
        (folder / f"xeroxpro-2026010{i + 1}-100000-auto.db").write_bytes(b"junk")
    bk.prune_auto(folder, keep=1)
    assert newest.path.exists()
    bk.prune_auto(folder, keep=0)  # even a silly keep=0 keeps at least one
    assert newest.path.exists()


def test_stale_detection_and_folder_listing(env):
    engine, factory, tmp = env
    with session_scope(factory) as s:
        assert backup_service.is_stale(s) and backup_service.newest_backup(s) is None
    b = backup_service.run_backup(engine, factory, "manual")
    with session_scope(factory) as s:
        assert not backup_service.is_stale(s)
        assert backup_service.is_stale(s, now=b.created + timedelta(days=2))
        assert [x.kind for x in backup_service.list_all(s)] == ["manual"]


def test_export_to_another_folder_does_not_disturb_the_backup_folder(env):
    engine, factory, tmp = env
    usb = tmp / "usb"
    exported = backup_service.run_backup(engine, factory, "export", dest=usb)
    assert exported.path.parent == usb and exported.kind == "export"
    assert bk.list_backups(tmp / "backups") == [] and bk.validate_backup(exported.path, latest_version()).ok


def test_backup_folder_choice_is_checked_and_warns_when_next_to_the_data(env):
    engine, factory, tmp = env
    with session_scope(factory) as s:
        chosen = backup_service.set_backup_dir(s, str(tmp / "elsewhere"))
        assert chosen.is_dir() and backup_service.backup_dir(s) == chosen
        assert not backup_service.is_inside_data_dir(chosen, engine)
        assert backup_service.is_inside_data_dir(config.db_path().parent / "backups", engine)
        with pytest.raises(ValidationError):
            backup_service.set_backup_dir(s, "  ")
        (tmp / "file").write_text("x")
        with pytest.raises(BackupError):
            backup_service.set_backup_dir(s, str(tmp / "file" / "sub"))


# ---- reliability -------------------------------------------------------------------------------

def test_records_survive_restart(env):
    engine, factory, tmp = env
    add_bill(factory, "a")
    engine.dispose()
    engine2, factory2 = open_database(config.db_path())  # "restart the application"
    with session_scope(factory2) as s:
        assert s.query(Bill).count() == 1
    engine2.dispose()


def test_process_killed_mid_transaction_leaves_a_consistent_database(env):
    """A real crash: the child process dies (os._exit) after writing but before COMMIT."""
    engine, factory, tmp = env
    add_bill(factory, "committed")
    engine.dispose()
    script = textwrap.dedent(f"""
        import os, sys
        sys.path.insert(0, {str(Path(config.resource_path().parent))!r})
        from database.connection import make_engine
        e = make_engine({str(config.db_path())!r})
        c = e.connect()
        c.exec_driver_sql("INSERT INTO customers(customer_name, phone, notes, is_active, created_at, updated_at)"
                          " VALUES ('ghost','', '', 1, 'x', 'x')")
        c.exec_driver_sql("UPDATE shop_settings SET shop_name='half done'")
        os._exit(1)  # killed before commit
    """)
    assert subprocess.run([sys.executable, "-I", "-c", script], capture_output=True).returncode == 1
    con = sqlite3.connect(config.db_path())
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert con.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0
    assert con.execute("SELECT shop_name FROM shop_settings").fetchone()[0] == "Sri Xerox"
    assert con.execute("SELECT COUNT(*) FROM bills").fetchone()[0] == 1
    con.close()
    e2, f2 = open_database(config.db_path())  # and the app opens it normally
    e2.dispose()
