# XeroxPro — Xerox Shop Management System

Offline Windows desktop application for a small Xerox / printing shop: billing and A4 receipts, udhar (credit),
stationery stock, expenses, job orders, PDF printing, online-application records, reports (PDF/Excel) and backups.
English and Telugu. Python 3.12 · PySide6 · SQLite/SQLAlchemy · PyMuPDF · openpyxl.

**Status: all six phases built. Windows build and real-printer checks are still to be run** (see "What is verified").

| Read this | For |
|---|---|
| [docs/USER_MANUAL.md](docs/USER_MANUAL.md) | the shop owner: setup, daily use, reports, backups |
| [INSTALL.md](INSTALL.md) | installing on the shop PC, and building the Windows program (GitHub Actions or a Windows PC) |
| [docs/BACKUP_RESTORE.md](docs/BACKUP_RESTORE.md) | backup and restore, step by step |
| [docs/SHOP_PC_CHECKLIST.md](docs/SHOP_PC_CHECKLIST.md) | checks to do once on the real PC and printers |
| [docs/TEST_REPORT.md](docs/TEST_REPORT.md) | what was tested, with the actual results |
| [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) | what it does not do, and where it was not tested |
| [REQUIREMENTS.md](REQUIREMENTS.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [DATABASE_DESIGN.md](DATABASE_DESIGN.md) · [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) | design documents |

## Run from source (developers)

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q        # whole test suite, headless
.venv/bin/python main.py                              # start the app
.venv/bin/python main.py --selftest --skip-printers   # packaging/installation check
```

User data goes to `%LOCALAPPDATA%\XeroxPro` (Windows) or `~/.local/share/XeroxPro` (Linux); set `XEROXPRO_DATA_DIR`
to use another folder.

## What is verified (and what is not)

- **Verified here (Linux, headless):** the full automated test suite; the PyInstaller bundle built on Linux starts,
  finds its bundled fonts/migrations, and passes `--selftest` from a different folder with no Python; the single-instance
  lock; backups, restore, killed-process recovery.
- **Not verified yet:** the Windows `.exe` itself (it must be built on Windows — see INSTALL.md), any real printer,
  Windows fonts and antivirus behaviour. The checklist in `docs/SHOP_PC_CHECKLIST.md` covers these.
