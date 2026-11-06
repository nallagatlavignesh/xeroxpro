# ARCHITECTURE — XeroxPro

## 1. Layers and dependency rule

```
ui/  (PySide6 screens, widgets)            ← only layer that imports PySide6 widgets
  │  calls
application/  (use cases: SaveBill, RecordPayment, CancelBill, RestoreBackup, ...)
  │  orchestrates one DB transaction per use case
business/  (pure Python: pricing, billing, payments, inventory, accounting — no DB, no Qt)
  │  used by
database/  (SQLAlchemy models, repositories, migrations)
infrastructure/  (pdf, printers, backups, exports — talk to OS/files)
```

Rules (checked by a test that scans imports):
- `business/` imports nothing from `ui`, `database`, `infrastructure`, `PySide6`, `sqlalchemy`. Pure functions over `Decimal`/int paise → trivially unit-testable.
- `ui/` never computes money. It calls `application/` and displays results.
- `application/` owns the transaction boundary (`with session.begin():`), repositories never commit.
- Infrastructure is injected into use cases (printer, clock, filesystem) so tests can fake it.

## 2. Folder structure (kept from the prompt, with two adjustments)

```
xeroxpro/                      (repo root = this folder)
├── main.py                    entry: single-instance lock, logging, DB open+migrate, Qt app
├── config.py                  data dir, backup dir, app version (no Qt import)
├── requirements.txt           runtime deps, pinned          requirements-dev.txt: pytest, pyinstaller
├── README.md REQUIREMENTS.md ARCHITECTURE.md DATABASE_DESIGN.md DEVELOPMENT_PLAN.md
├── database/
│   ├── connection.py          engine, PRAGMAs (foreign_keys, WAL, busy_timeout), session factory
│   ├── models/                one file per aggregate (bills.py, customers.py, ...)
│   ├── repositories/          thin query classes
│   └── migrations/            0001_baseline.py, 0002_...  + runner (see DATABASE_DESIGN §8)
├── application/
│   ├── services/              clock, settings, i18n service, audit
│   └── use_cases/             one module per workflow
├── business/                  billing.py pricing.py payments.py inventory.py accounting.py money.py
├── ui/
│   ├── main_window.py  theme.py  widgets/ (money edit, table, chart, pin dialog)
│   └── dashboard/ billing/ printing/ jobs/ customers/ inventory/ expenses/ applications/ reports/ settings/ backup/
├── infrastructure/
│   ├── pdf/                   pdf_info.py (PyMuPDF), receipt.py + report.py (QPdfWriter)
│   ├── printers/              capabilities.py, print_job.py (QPrinter), fake.py (tests)
│   ├── backups/               backup.py (sqlite3 backup API), validate.py, scheduler.py
│   └── exports/               excel.py (openpyxl), report_pdf.py
├── resources/ icons/ styles/ translations/{en,te}.json fonts/ (Noto Sans Telugu, OFL)
├── tests/ unit/ integration/ gui/
├── packaging/ xeroxpro.spec  build_windows.bat  installer.iss (optional)
└── docs/ USER_MANUAL.md  BACKUP_RESTORE.md  KNOWN_LIMITATIONS.md  TEST_REPORT.md   (Phase 6)
```
Adjustment 1: added `ui/backup/` (the prompt lists no UI folder for it). Adjustment 2: `docs/` for user-facing documents.

## 3. Stack decisions and deviations

| Prompt item | Decision | Reason |
|---|---|---|
| Python 3 | **3.12** | Verified wheels for PySide6/PyMuPDF/PyInstaller on win_amd64 cp312. The conda default here is 3.14; not used. |
| PySide6 | **PySide6_Essentials** on the Windows build | Includes QtWidgets, QtPrintSupport, QtGui; skips ~1 GB of unused add-ons. |
| SQLAlchemy | 2.x, declarative typed models | |
| Migrations | **Own tiny runner + numbered scripts**, not Alembic | One more dependency and config for a single-file SQLite DB isn't justified. |
| ReportLab | **Dropped** (see §5) | Wrong Telugu rendering, proven by spike. |
| Receipt/report PDF | **Qt `QPdfWriter` + `QTextDocument` (HTML/table)** | Correct HarfBuzz Telugu shaping, automatic multi-page, same engine as the GUI. |
| Pillow | Kept for PDF-page thumbnails only if needed; PyMuPDF can render to `QImage` directly, so Pillow may also be dropped in Phase 4. | Minimal dependencies. |
| Excel | openpyxl | |
| Charts | Small custom `QPainter` bar chart widget, not QtCharts | Avoids another large module for two simple charts. |
| i18n | JSON key→text files + `tr(key, **params)`; test asserts en/te have identical key sets | Maintainable, no Qt Linguist tooling for the owner/translator. |
| Packaging | PyInstaller **onedir** + optional Inno Setup installer | onefile unpacks to a temp dir every launch, is slower and flagged more often by antivirus. User data is never stored beside the exe. |

## 4. Cross-cutting design

- **Money**: integer paise everywhere in DB and `business/`. `Quantity` uses `Decimal` (3 dp) because services such as "per kg"/fractional units may occur; amount = `round_half_up(qty * rate_paise)`. UI formats `₹1,23,456.50` (Indian digit grouping) in one function.
- **Time**: stored UTC ISO text; `clock` service injected; `to_ist()` fixed +05:30. "Business date" for reports = IST calendar date.
- **Transactions & idempotency**: each use case = one `session.begin()`. `SaveBill` takes a client-generated `idempotency_key` (UUID created when the New Bill screen opens/resets); a UNIQUE index on `bills.idempotency_key` makes a double-click or retry return the existing bill instead of a second one. The Save button is also disabled while a save runs. Same pattern for `payments`. Ledger entries have a UNIQUE `(reference_type, reference_id, transaction_type)` so retries cannot duplicate them.
- **Ledger as source of truth for udhar**: `Customer outstanding = Σdebit − Σcredit`. A test reconciles it with Σ`bills.outstanding_amount` for the customer after every scenario.
- **Bill state machine**: `Unpaid → Partial → Paid`, and `Cancelled` / `Refunded`. Cancellation writes: reversing ledger rows, a refund payment row (negative, method chosen) if money had been collected, inventory `return` transactions for stationery lines, and an `audit_log` row with reason. Original rows stay untouched.
- **Audit trail**: `audit_log(id, at, action, entity, entity_id, reason, details_json)` for cancellations, refunds, rate overrides, stock adjustments, restores, settings changes to rates.
- **Errors**: domain exceptions (`ValidationError`, `StockError`, ...) carry translation keys; UI shows a translated message. Unexpected exceptions are logged with traceback to a rotating log file in the data dir and shown as a friendly dialog with the log location.
- **Data locations (Windows)**: DB `%LOCALAPPDATA%\XeroxPro\xeroxpro.db`, logs `…\XeroxPro\logs\`, backups default `%USERPROFILE%\Documents\XeroxPro Backups\` (different folder and preferably different drive from the DB; configurable; optional second copy to USB/folder). `XEROXPRO_DATA_DIR` env var overrides for tests/dev.
- **Backups**: `sqlite3.Connection.backup()` (consistent even with open connection) → write to `name.tmp` → `PRAGMA integrity_check` + schema-version check on the copy → atomic rename to `xeroxpro-YYYYMMDD-HHMMSS.db`. Never overwrite; keep last N (default 30) + never delete the newest valid one. Restore: validate → warn → take a pre-restore backup of the current DB → swap → reopen. Interrupted backup leaves only a `.tmp` that is ignored/cleaned.
- **Concurrency**: single instance via `QLockFile`; WAL mode; `busy_timeout`.

## 5. Risks and mitigations

| # | Risk | Evidence / status | Mitigation |
|---|---|---|---|
| R1 | **Telugu receipt rendering** | **Spike done.** ReportLab rendered "ధన్యవాదాలు" with a visible virama and broken conjuncts (న్య). Qt `QPdfWriter` with Noto Sans Telugu rendered it correctly. | Use Qt for all PDFs. Bundle Noto Sans Telugu (SIL OFL allows bundling). Phase 2 test renders a Telugu receipt with PyMuPDF and checks the font is embedded and text extracts; **visual check by eye is also required** and is on the Phase 2 gate. Final check on the shop printer. |
| R2 | **Multiple-printer integration** | `QPrinterInfo` exposes colour/duplex/paper-size/state APIs. No printer exists on this dev box (0 printers), so real behaviour is **untestable here**. | Hide Qt behind a `PrinterGateway` interface; fake gateway for tests; unit-test cost/sheet logic separately; real-device checklist in TEST_REPORT to be run on the shop PC. Drivers may misreport capabilities → UI shows "not detected" and allows manual override. Spooler acceptance ≠ printed (A8). |
| R3 | **Windows packaging from Linux** | PyInstaller cannot cross-compile; Wine absent. Windows wheels confirmed downloadable. | Open question #1. Plan: `packaging/xeroxpro.spec` + `build_windows.bat`; build on GitHub Actions Windows runner or a Windows machine. I cannot claim the `.exe` works until it has been built and launched on Windows. |
| R4 | PDF printing fidelity (rendering PDF via PyMuPDF→QPrinter) | Rasterizing at printer resolution is reliable but large for big PDFs and loses vector quality. | Render per page at printer DPI (capped), stream page-by-page; add "open in default PDF viewer to print" fallback. |
| R5 | Duplex/sheet math | Duplex sheets = ceil(pages/2) per copy; collated copies vs. page-ranges. | Pure function in `business/pricing.py`, table-driven tests incl. odd page counts and ranges. Billing unit (per page vs per sheet) is per-service configuration. |
| R6 | Data loss on owner's PC (disk failure, accidental delete) | | Daily auto-backup on startup/exit, USB export, restore tested in CI. Backup reminder on dashboard if last backup > 2 days. |
| R7 | PyInstaller + Qt plugins missing in bundle (platforms, printsupport, imageformats) | Common failure mode | `.spec` explicit hooks; smoke test launches the built exe with `--selftest` flag that opens DB, renders a Telugu PDF, lists printers, exits 0. |
| R8 | Antivirus false positive on unsigned exe | Likely with PyInstaller | Use onedir, document in INSTALL; code signing is out of budget. |
| R9 | Telugu UI strings correctness | I can draft but not guarantee idiomatic wording | Open question #4. |
| R10 | Scope size | 11 modules | Strict phase gates; billing first. |

## 6. Telugu/Font specifics
- Bundle `NotoSansTelugu-Regular/Bold.ttf` (found on this box at `/usr/share/fonts/truetype/noto/`; same OFL licence on Windows build). Load with `QFontDatabase.addApplicationFont` at startup; UI font stack: `"Segoe UI", "Noto Sans Telugu"` so English uses the native font and Telugu falls back correctly. Windows' own *Nirmala UI* also covers Telugu as a second fallback.
- Latin digits/₹ glyph: verify the chosen Latin font has ₹ (Segoe UI does); receipt uses Noto Sans (Latin) + Noto Sans Telugu.


## Final notes (as built)

- PDF output (receipts, reports) is Qt (`QTextDocument` -> `QPdfWriter`); ReportLab and Pillow are not used.
- Printing uses `QPrinterInfo`/`QPrinter` behind `PrinterGateway` (fake gateway for tests). Copies are produced by the
  program (not the driver) so the page order does not depend on the driver.
- Migrations are numbered SQL files (`database/migrations/NNNN_*.sql`) run by a small runner; a test compares the
  models with the migrated schema so they cannot drift.
- Startup self-check: `XeroxPro.exe --selftest [report.txt] [--skip-printers]`.
- Packaging: `packaging/xeroxpro.spec` (onedir), `packaging/build_windows.bat`, `packaging/installer.iss`,
  `.github/workflows/build-windows.yml`.
