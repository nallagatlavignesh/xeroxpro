# Test report

Generated from a real run on **Linux-7.2.6-76070206-generic-x86_64-with-glibc2.39**, Python 3.12.3, headless (`QT_QPA_PLATFORM=offscreen`).
Libraries: PySide6 6.12.0, SQLAlchemy 2.1.8, PyMuPDF 2.1, openpyxl 3.1.5, pytest 9.2.0, pyinstaller 6.22.3.

## Result

**317 tests, 317 passed, 0 failed**, total time 85 s (`pytest -q`).

| Test file | Tests | Failed | Time |
|---|---|---|---|
| tests/gui/test_accounts_ui.py | 11 | 0 | 6.2s |
| tests/gui/test_billing_ui.py | 19 | 0 | 11.3s |
| tests/gui/test_main_window.py | 9 | 0 | 4.8s |
| tests/gui/test_phase4_ui.py | 21 | 0 | 14.5s |
| tests/gui/test_phase5_ui.py | 17 | 0 | 13.2s |
| tests/integration/test_accounts.py | 21 | 0 | 1.4s |
| tests/integration/test_backup.py | 24 | 0 | 3.7s |
| tests/integration/test_billing_flow.py | 20 | 0 | 2.8s |
| tests/integration/test_catalog.py | 5 | 0 | 0.5s |
| tests/integration/test_concurrency.py | 2 | 0 | 0.4s |
| tests/integration/test_operations.py | 23 | 0 | 2.1s |
| tests/integration/test_printing.py | 17 | 0 | 3.4s |
| tests/integration/test_receipt.py | 5 | 0 | 0.7s |
| tests/integration/test_reports.py | 18 | 0 | 6.4s |
| tests/integration/test_schema.py | 23 | 0 | 1.3s |
| tests/integration/test_single_instance.py | 2 | 0 | 5.0s |
| tests/unit/test_architecture.py | 1 | 0 | 0.0s |
| tests/unit/test_billing.py | 16 | 0 | 0.0s |
| tests/unit/test_fonts_and_errors.py | 9 | 0 | 5.2s |
| tests/unit/test_i18n.py | 5 | 0 | 0.0s |
| tests/unit/test_i18n_usage.py | 3 | 0 | 0.1s |
| tests/unit/test_money.py | 13 | 0 | 0.0s |
| tests/unit/test_pricing.py | 33 | 0 | 0.0s |

## Additional checks run on the packaged program (Linux build of the same PyInstaller spec)

| Check | Result |
|---|---|
| `pyinstaller packaging/xeroxpro.spec` | built, 251 MB folder (Linux bundle includes the full PySide6; the Windows build uses PySide6-Essentials) |
| `XeroxPro --selftest` run from a different folder, no Python on the path | exit 0: bundled files, translations, database + migrations (v2), Telugu receipt PDF, PDF+Excel reports, backup + restore, all screens |
| same, after deleting a bundled font and a migration file | exit 1, both problems reported (the self-test is not a rubber stamp) |
| normal start of the bundle (headless) | stays running; creates the database, applies both migrations, makes the daily automatic backup |
| second copy started while the first runs | refused (also covered by two-process tests) |

## Requirements from the specification (section 12) and where they are tested

| Requirement | Test |
|---|---|
| 25 pages x 2 copies x Rs2 = Rs100; 10 x Rs20 = Rs200; several items; discounts; partial payment | `unit/test_billing.py`, `integration/test_billing_flow.py`, `gui/test_billing_ui.py` |
| zero/negative quantity and invalid price rejected | `unit/test_billing.py`, `gui/test_billing_ui.py::test_bad_quantity...`, `integration/test_schema.py` (database CHECKs) |
| old bills keep their rate after a price change | `integration/test_billing_flow.py::test_historical_rate_is_kept_after_price_change` |
| Rs100 bill, Rs60 paid -> Rs40 due; later Rs40 clears it; ledger; duplicate payment; history | `integration/test_accounts.py` |
| stock 10, sell 2 -> 8; purchase increases; cancel reverses; negative blocked unless authorised | `integration/test_operations.py`, `integration/test_billing_flow.py` |
| daily expense totals; cash vs UPI separate; sales vs collections; credit not counted as received; purchases not double-counted | `integration/test_accounts.py`, `integration/test_reports.py` |
| PDF page count, page ranges, copies, single/double-sided cost, printer selection, disconnected printer, submit failure, Telugu PDF | `unit/test_pricing.py`, `integration/test_printing.py`, `gui/test_phase4_ui.py` |
| restart persistence; backup/restore; invalid backup rejected; interrupted operation; migration; duplicate/concurrent submission | `integration/test_backup.py` (incl. killed process), `integration/test_schema.py`, `integration/test_concurrency.py` (12 threads), `integration/test_single_instance.py` |
| Telugu text can be drawn (no missing glyphs) in UI and PDFs | `unit/test_fonts_and_errors.py`, `integration/test_receipt.py`, `integration/test_reports.py` |
| every translation key exists in English and Telugu | `unit/test_i18n.py`, `unit/test_i18n_usage.py` |

## Acceptance criteria (section 17)

| Criterion | Status |
|---|---|
| Launches on Windows | **Not yet verified** - needs the Windows build (GitHub Actions workflow or `packaging/build_windows.bat`). Linux bundle verified. |
| Core modules work | Verified by automated workflow tests (headless) |
| Billing calculations accurate | Verified (unit + database-level CHECKs agree with the Python rule) |
| A4 receipts print correctly | PDF output verified (page size, margins, multi-page, header repeat) and viewed as images. **Printing to a real printer not verified.** |
| English and Telugu work | Verified headless + screenshots; **Telugu wording needs review by a native reader** |
| Multiple installed printers selectable | Verified with fake printers and the real Qt gateway (no printers on the dev machine); **real printers not verified** |
| Customer credit accurate | Verified (ledger always equals sum of open bills, tested after saves, payments and cancellations) |
| Inventory updates correctly | Verified (stock always equals the sum of its movements) |
| Daily reports reconcile with transactions | Verified against independent SQL totals and the dashboard |
| Backups can be restored | Verified (incl. older-schema backup, undo from safety copy, PIN) |
| Critical automated tests pass | **317/317** |
| Packaged exe runs without Python | Verified for the Linux bundle; **Windows exe not yet built** |

## Bugs found by this testing (all fixed)

Found during development by the tests or by looking at screenshots: `&` swallowed in menu text; `to_paise("abc")` wrong exception type;
unflushed new-service id; migration 0002 failing on a database that already had a closing; Excel header/formatting one row off;
print routine ~20x too slow and memory-hungry at 1200 dpi; default unit "page" for new stationery; arrow character missing from the bundled fonts;
same-second backups listed in the wrong order; test-suite slowness from re-applying the stylesheet (suite 5 min -> 1.5 min).

## Not tested (see also docs/KNOWN_LIMITATIONS.md)

Real printers, Windows (fonts, file locking, antivirus, SmartScreen), the Windows installer, screen sizes other than the
default test window, a Telugu-speaking reader's review, very large databases (years of data), and several people using
the program at once on one database over a network share (not supported).
