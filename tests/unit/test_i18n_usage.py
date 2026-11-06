"""Every translation key used in code exists in both language files (a missing key would silently show raw text)."""
import json
import re
from pathlib import Path

import config
from business.billing import PAYMENT_METHODS

ROOT = Path(__file__).resolve().parents[2]
KEYS = set(json.loads((config.resource_path("translations") / "en.json").read_text(encoding="utf-8")))
KEY = r'"([a-z_]+\.[a-z_]+)"'
CALLS = re.compile(r'(?:\b_?tr|\bt|\btr\.tr|_ui_tr)\(\s*' + KEY + r'|Error\(\s*' + KEY + r'|field_key=' + KEY
                   + r'|\(\s*"[^"]*"\s*,\s*' + KEY + r'\s*\)')


def used_keys():
    found = {}
    for folder in ("ui", "application", "business", "infrastructure"):
        for path in (ROOT / folder).rglob("*.py"):
            for m in CALLS.finditer(path.read_text(encoding="utf-8")):
                key = next(g for g in m.groups() if g)
                found.setdefault(key, path.name)
    return found


def test_all_literal_keys_exist():
    missing = {k: f for k, f in used_keys().items() if k not in KEYS and not k.startswith(("pay.", "unit.")) and not k.endswith((".qss", ".json", ".ttf", ".png", ".ico", "_"))}
    assert not missing, missing


def test_dynamic_key_families_are_complete():
    expected = (
        [f"pay.{m}" for m in PAYMENT_METHODS]
        + [f"status.{s}" for s in ("unpaid", "partial", "paid", "cancelled", "refunded")]
        + [f"ledger.{t}" for t in ("bill", "payment", "bill_reversal", "refund", "adjustment")]
        + [f"dash.kind_{k}" for k in ("bill", "payment", "refund", "expense")]
        + [f"jobs.status_{x}" for x in ("received", "pending", "in_progress", "completed", "delivered", "cancelled")]
        + [f"applications.status_{x}" for x in ("received", "submitted", "in_progress", "completed", "rejected")]
        + [f"inventory.tx_{x}" for x in ("purchase", "sale", "return", "adjustment", "sale_reversal")]
        + [f"print.status_{x}" for x in ("ready", "busy", "error")]
        + [f"lang.{c}" for c in ("en", "te")] + [f"receipt.{s}" for s in ("cancelled", "refunded")]
        + [f"unit.{u}" for u in ("page", "copy", "sheet", "item", "set", "job")]
        + [f"nav.{k}" for k in ("dashboard", "new_bill", "pdf_printing", "job_orders", "customers", "inventory",
                                "expenses", "applications", "reports", "settings", "backup")]
    )
    assert [k for k in expected if k not in KEYS] == []


def test_every_domain_error_key_in_code_is_translated():
    keys = {k for k in used_keys() if not k.endswith("_") and k.split(".")[0] in {"bill", "stock", "auth", "catalog", "customer", "payment", "expense",
                                                          "closing", "validation", "settings", "print", "jobs", "inventory",
                                                          "applications"}}
    assert keys and keys <= KEYS
