import re
import sqlite3
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, StatementError

import config
from application.services import settings_service
from business.errors import ValidationError
from business.money import line_amount
from database.bootstrap import open_database
from database.connection import session_scope
from database.migrations.runner import SchemaTooNewError, latest_version, migrate
from database.models import Base, Bill, BillItem, Payment, Product, ShopSettings, Service, ServiceRate


def _schema(path_or_engine) -> set[tuple]:
    sql = "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE sql IS NOT NULL"
    if isinstance(path_or_engine, str):
        rows = sqlite3.connect(path_or_engine).execute(sql).fetchall()
    else:
        with path_or_engine.connect() as c:
            rows = c.exec_driver_sql(sql).fetchall()
    return {(t, n, tb, re.sub(r"\s+", " ", s)) for t, n, tb, s in rows}


def test_models_match_migrations(tmp_path):
    """Fails when someone edits a model without adding a migration."""
    path = tmp_path / "m.db"
    migrate(path)
    mem = create_engine("sqlite://")
    Base.metadata.create_all(mem)
    assert _schema(str(path)) == _schema(mem)


def test_all_expected_tables_exist(db):
    engine, _ = db
    with engine.connect() as c:
        tables = {r[0] for r in c.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables >= {
        "shop_settings", "services", "service_rates", "customers", "bills", "bill_items", "payments",
        "customer_ledger", "products", "inventory_transactions", "expenses", "job_orders",
        "job_status_history", "application_records", "printer_settings", "app_metadata",
        "audit_log", "daily_closings", "backup_history", "lookup_values",
    }


def test_pragmas_on_every_connection(db):
    engine, _ = db
    with engine.connect() as c:
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert c.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert c.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000


def test_foreign_key_violation_rejected(db):
    _, factory = db
    with pytest.raises(IntegrityError):
        with session_scope(factory) as s:
            s.add(ServiceRate(service_id=9999, rate=100, effective_from="2026-01-01T00:00:00"))


def test_seed_has_placeholders_but_no_rates_or_transactions(db):
    _, factory = db
    with session_scope(factory) as s:
        assert s.query(Service).count() == 8
        assert s.query(ServiceRate).count() == 0  # never invent prices
        assert s.query(Bill).count() == 0
        assert s.get(ShopSettings, 1).shop_name == "XeroxPro"


def test_open_is_idempotent_and_persists(tmp_path):
    path = tmp_path / "p.db"
    e1, f1 = open_database(path)
    with session_scope(f1) as s:
        settings_service.update_shop_settings(s, shop_name="Sri Xerox")
    e1.dispose()
    e2, f2 = open_database(path)  # restart
    with session_scope(f2) as s:
        assert settings_service.get_shop_settings(s).shop_name == "Sri Xerox"
        assert s.query(Service).count() == 8  # not re-seeded
    e2.dispose()


def test_settings_validation(db):
    _, factory = db
    with session_scope(factory) as s:
        with pytest.raises(ValidationError):
            settings_service.update_shop_settings(s, shop_name="   ")
        with pytest.raises(ValidationError):
            settings_service.update_shop_settings(s, preferred_language="fr")
        with pytest.raises(ValueError):
            settings_service.update_shop_settings(s, owner_pin_hash="x")


def test_refuses_newer_schema_and_leaves_it_untouched(tmp_path):
    path = tmp_path / "n.db"
    migrate(path)
    con = sqlite3.connect(path)
    con.execute("UPDATE app_metadata SET value='99' WHERE key='schema_version'")
    con.commit(); con.close()
    before = path.read_bytes()
    with pytest.raises(SchemaTooNewError):
        open_database(path)
    assert path.read_bytes() == before


def test_migration_keeps_data_and_backs_up_first(tmp_path):
    """Synthetic v2 migration on a DB that already holds data."""
    mig = tmp_path / "migs"
    mig.mkdir()
    base = config.resource_path().parent / "database" / "migrations" / "0001_baseline.sql"
    (mig / "0001_baseline.sql").write_text(base.read_text())
    db_file = tmp_path / "d.db"
    migrate(db_file, mig)
    con = sqlite3.connect(db_file)
    con.execute("INSERT INTO lookup_values(kind,value,sort_order) VALUES('unit','page',0)")
    con.commit(); con.close()

    (mig / "0002_test.sql").write_text("ALTER TABLE lookup_values ADD COLUMN note TEXT;")
    backups = tmp_path / "bk"
    assert migrate(db_file, mig, backups) == 2
    assert len(list(backups.glob("*pre-migration-v1*.db"))) == 1
    con = sqlite3.connect(db_file)
    assert con.execute("SELECT value, note FROM lookup_values").fetchall() == [("page", None)]
    assert con.execute("SELECT value FROM app_metadata WHERE key='schema_version'").fetchone()[0] == "2"
    con.close()


def test_failed_migration_rolls_back(tmp_path):
    mig = tmp_path / "migs"
    mig.mkdir()
    base = config.resource_path().parent / "database" / "migrations" / "0001_baseline.sql"
    (mig / "0001_baseline.sql").write_text(base.read_text())
    db_file = tmp_path / "d.db"
    migrate(db_file, mig)
    (mig / "0002_bad.sql").write_text("ALTER TABLE lookup_values ADD COLUMN ok TEXT;\nTHIS IS NOT SQL;")
    with pytest.raises(sqlite3.Error):
        migrate(db_file, mig, tmp_path / "bk")
    con = sqlite3.connect(db_file)
    cols = [r[1] for r in con.execute("PRAGMA table_info(lookup_values)")]
    assert "ok" not in cols  # half-applied change was rolled back
    assert con.execute("SELECT value FROM app_metadata WHERE key='schema_version'").fetchone()[0] == "1"
    con.close()


def test_latest_version_is_one():
    assert latest_version() == 2


# --- DB-level guard rails the later phases rely on ---------------------------------------------

def _bill(**kw):
    base = dict(bill_number="B1", bill_date="2026-11-05", subtotal=10000, discount=0, grand_total=10000,
                total_paid=0, outstanding_amount=10000, status="unpaid", idempotency_key="k1", customer_id=None)
    return Bill(**{**base, **kw})


def test_credit_bill_requires_customer(db):
    _, factory = db
    with pytest.raises(IntegrityError):
        with session_scope(factory) as s:
            s.add(_bill())  # outstanding 10000 but walk-in


def test_bill_totals_must_add_up(db):
    _, factory = db
    with pytest.raises(IntegrityError):
        with session_scope(factory) as s:
            s.add(_bill(total_paid=10000, outstanding_amount=500))
    with session_scope(factory) as s:
        s.add(_bill(total_paid=10000, outstanding_amount=0, status="paid"))  # valid


def test_duplicate_bill_idempotency_key_rejected(db):
    _, factory = db
    with session_scope(factory) as s:
        s.add(_bill(total_paid=10000, outstanding_amount=0, status="paid"))
    with pytest.raises(IntegrityError):
        with session_scope(factory) as s:
            s.add(_bill(bill_number="B2", total_paid=10000, outstanding_amount=0, status="paid"))


@pytest.mark.parametrize("qty, rate", [("50", 200), ("10", 2000), ("0.5", 5), ("2.5", 333), ("1.001", 999)])
def test_bill_item_amount_check_matches_python_rule(db, qty, rate):
    _, factory = db
    with session_scope(factory) as s:
        s.add(_bill(bill_number=f"B{qty}{rate}", idempotency_key=f"k{qty}{rate}", total_paid=10000,
                    outstanding_amount=0, status="paid"))
    with session_scope(factory) as s:
        bill_id = s.query(Bill).filter_by(bill_number=f"B{qty}{rate}").one().id
        s.add(BillItem(bill_id=bill_id, description="x", quantity=Decimal(qty), unit="page", unit_rate=rate,
                       amount=line_amount(Decimal(qty), rate)))  # DB CHECK would reject any disagreement


def test_bill_item_wrong_amount_and_zero_quantity_rejected(db):
    _, factory = db
    with session_scope(factory) as s:
        s.add(_bill(total_paid=10000, outstanding_amount=0, status="paid"))
    for qty, amount in [("50", 999), ("0", 0), ("-1", 0)]:
        with pytest.raises(IntegrityError):
            with session_scope(factory) as s:
                bid = s.query(Bill).one().id
                s.add(BillItem(bill_id=bid, description="x", quantity=Decimal(qty), unit="page",
                               unit_rate=200, amount=amount))


def test_payment_needs_exactly_one_target_and_positive_amount(db):
    _, factory = db
    for kw in (dict(bill_id=None, job_id=None), dict(amount=0)):
        with pytest.raises(IntegrityError):
            with session_scope(factory) as s:
                s.add(Payment(**{**dict(bill_id=None, job_id=None, amount=100, payment_method="cash",
                                        payment_date="2026-11-05", idempotency_key="p"), **kw}))


def test_quantity_roundtrip_exact(db):
    _, factory = db
    with session_scope(factory) as s:
        s.add(Product(product_name="Pen", stock_quantity=Decimal("2.5")))
    with session_scope(factory) as s:
        assert s.query(Product).one().stock_quantity == Decimal("2.500")
    with pytest.raises(StatementError, match="3 decimal places"):  # SQLAlchemy wraps the ValueError
        with session_scope(factory) as s:
            s.add(Product(product_name="Bad", stock_quantity=Decimal("0.0001")))


def test_real_migration_0002_keeps_existing_closings(tmp_path):
    """A v1 database that already has a daily closing must survive the upgrade to v2."""
    only_v1 = tmp_path / "v1"
    only_v1.mkdir()
    mdir = config.resource_path().parent / "database" / "migrations"
    (only_v1 / "0001_baseline.sql").write_text((mdir / "0001_baseline.sql").read_text())
    db_file = tmp_path / "d.db"
    migrate(db_file, only_v1)
    con = sqlite3.connect(db_file)
    con.execute("INSERT INTO daily_closings(closing_date, expected_cash, counted_cash, difference, notes, created_at) "
                "VALUES ('2026-02-10', 5000, 4900, -100, 'n', '2026-02-10T12:00:00')")
    con.commit(); con.close()
    assert migrate(db_file, backup_dir=tmp_path / "bk") == 2
    con = sqlite3.connect(db_file)
    assert con.execute("SELECT closing_date, opening_cash, expected_cash, difference FROM daily_closings").fetchall() \
        == [("2026-02-10", 0, 5000, -100)]
    assert len(list((tmp_path / "bk").glob("*pre-migration-v1*"))) == 1
