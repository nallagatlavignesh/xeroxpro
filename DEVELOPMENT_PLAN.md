# DEVELOPMENT_PLAN — XeroxPro

Gate rule: no phase starts until the previous phase's tests pass **and I have shown you the actual pytest output**. Every phase ends with a short report (what works, what is not done, what was not verified) and waits for your go-ahead.

## Phase overview and how each is tested

| Phase | Deliverable | Automated tests | Manual / visual check |
|---|---|---|---|
| **0 Architecture** (done) | 5 docs, folder plan, dependency check, Telugu spike | Spike script: ReportLab vs Qt Telugu → Qt correct | You review the docs |
| **1 Foundation** | Project skeleton, DB + models, migration runner, main window + sidebar, i18n framework (en/te), settings foundation, logging, single-instance | Models⇔migration schema parity; PRAGMAs on; FK violation rejected; migrate v0→v1; refuse newer DB; i18n key parity en/te; import-boundary test (business/ has no Qt/SQLAlchemy); `QT_QPA_PLATFORM=offscreen` smoke: window opens, all 11 pages switch, language toggle relabels | Screenshot of main window in English & Telugu |
| **2 Billing** | Service catalogue + rate history, billing screen, payments, A4 receipt EN/TE, bill history, reprint, cancel/refund | The full list in prompt §12 "Billing calculations" (8 cases) + payments, idempotent double-submit, rollback on failure, historical-rate test, bill-number uniqueness under repeated calls, receipt PDF: page count, long bill → multi-page, Telugu text extracts & font embedded; GUI workflow: create bill via widgets | Rendered receipt PNG (EN & TE) reviewed by eye, A4 margins |
| **3 Accounts** | Customers, ledger, udhar payments, expenses, daily closing, dashboard | Prompt §12 "Customer credit" (5), "Expenses and reporting" (5); ledger⇔bill outstanding reconciliation; duplicate payment blocked; dashboard numbers vs hand-computed fixture | Dashboard screenshot |
| **4 Printing & ops** | PDF assistant, printer config, cost calc, job orders, inventory, online applications | Prompt §12 "PDF and printing" (8), "Inventory" (4); sheet/duplex/range/copies table tests; fake-printer gateway: disconnected, submit failure, unsupported duplex/colour; stock reconciliation; job status history | **Real printer checklist on the shop PC** (cannot run on this machine — no printers) |
| **5 Reports & backup** | All reports + PDF/Excel export, auto/manual backup, validate, restore, USB/folder export | Report totals reconcile with raw transactions; Excel opened back with openpyxl; backup→mutate→restore returns original rows; corrupt/truncated/non-SQLite/newer-schema backup rejected; `.tmp` leftovers ignored; kill-mid-backup simulation; restart persistence | Open exported PDF/XLSX |
| **6 QA & deploy** | Full regression, GUI tests, error handling pass, PyInstaller spec, build script, installer notes, user manual, limitations, test report | Whole suite; `--selftest` flag of built exe; restart/persistence; migration test | Built exe launched on Windows; Telugu receipt on real printer; USB backup |

## Test commands (introduced in Phase 1)
```bash
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q        # all
.venv/bin/pytest tests/unit -q                         # fast logic only
```
CI (if GitHub is used, open question #1): same suite on `ubuntu-latest` + `windows-latest`, then PyInstaller build on Windows.

## Things I cannot verify from this machine (will be stated plainly, never implied)
- Real printing (no printers here), duplex/colour behaviour on real drivers.
- Windows `.exe` build and launch; Windows font fallback; antivirus behaviour.
- Telugu correctness of translated UI wording (needs a native reader).
GUI tests run headless (`offscreen`) on Linux — good for logic/wiring, not pixel-perfect on Windows.

## Open decisions needing your answer
Listed in REQUIREMENTS.md §6 (build location for the Windows exe is the one that matters most) and assumptions A1–A15 (reply "OK" or list changes).

## Phase 1 entry criteria
Your approval of the docs and answers (or "use your recommendation") to REQUIREMENTS §6 items 1 and 3.


## Outcome (end of Phase 6)

| Phase | Result |
|---|---|
| 0 Architecture | done; one deviation: Qt (not ReportLab) writes PDFs because ReportLab mangles Telugu |
| 1 Foundation | done |
| 2 Billing | done |
| 3 Accounts | done (+ migration 0002: opening cash for daily closing) |
| 4 Printing & operations | done; real printers untested |
| 5 Reports & backup | done |
| 6 QA & deployment | done as far as possible from Linux: tests, self-test, PyInstaller spec/CI/installer scripts, docs. The Windows .exe is built by the GitHub Actions workflow (or `packaging/build_windows.bat`) — not yet run. |

Details and numbers: `docs/TEST_REPORT.md`.
