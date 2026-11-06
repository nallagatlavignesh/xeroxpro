# REQUIREMENTS — XeroxPro

Source: the Master Development Prompt (kept as the authority). This file records the *interpretation*,
assumptions and open questions so they can be corrected before code exists.

## 1. Users and context
- One shop owner, non-technical, one Windows PC, one printer or more, currently on paper notebooks.
- Single-user, single-machine, offline. No login by default.
- Languages: English (default) and Telugu, switchable at runtime.

## 2. Functional scope (11 modules)
Dashboard · Billing/POS · PDF Printing Assistant · Job Orders · Customers & Udhar · Stationery Inventory ·
Expenses · Online Applications · Reports (PDF/Excel) · Settings · Backup & Restore.
Details per module are exactly as in the master prompt; this document does not restate them.

## 3. Non-negotiable rules (from the prompt, enforced by design)
- Money = integer paise. Never float.
- Bills, payments, ledger rows are never deleted. Cancellation/refund = new reversing records + reason + audit row.
- Historical rates preserved: each bill item stores its own `unit_rate`.
- No prices or shop name hardcoded; both live in the DB and are editable in Settings.
- Sales, collections, credit outstanding, expenses, estimated profit and cash movement are computed separately.
- No passwords/OTP/Aadhaar stored in application records.
- Core features need no internet.

## 4. Assumptions (please correct any that are wrong)
| # | Assumption | Why |
|---|---|---|
| A1 | **Authorization** = an optional 4–6 digit *owner PIN* set in Settings. If set, it is asked for rate override, bill cancellation/refund, negative-stock adjustment and restore. If unset, those actions only need a confirm dialog + reason. | Prompt says "authorized" but defines no users. Full user accounts are overkill for one owner. |
| A2 | A customer's later udhar payment is **applied to specific bills** (oldest-first by default, editable). One `payments` row per bill touched. | Keeps `bills.outstanding_amount` and the ledger consistent. |
| A3 | Job order advance/balance payments are recorded as `payments` rows linked to the **job** (`job_id`), so they appear in cash/UPI collections. A job is not a bill; it may optionally be converted to a bill at delivery. | Otherwise job money would be invisible to collections reports. |
| A4 | Online-application service charge is billed through a normal bill (service "Online Application Assistance"); the application record links to that bill and its payment status is derived, not stored twice. | Avoids two sources of truth for money. |
| A5 | Estimated profit = sales − cost of stationery sold (`unit_cost` captured on the bill item) − operating expenses (excluding "stock purchase"). Labelled **estimate**; paper/toner consumed per print is not costed per sheet. | Prompt forbids claiming accounting-grade profit. Prevents double counting stock purchases. |
| A6 | "Cash movement" report = cash payments in − cash expenses out (and cash refunds out), per day. Daily closing compares this with the counted cash. | Prompt: don't call sales−expenses "cash in hand". |
| A7 | Stock purchases are recorded only in Inventory (not also as Expenses). The "Stationery purchases" expense category exists but the UI warns when used for stock bought for resale. | Double-count rule. |
| A8 | Print "success" = **job accepted by the OS print spooler**. The OS cannot reliably tell us paper came out. UI wording: "Sent to printer", never "Printed". Spooler/queue errors are surfaced. | Prompt: do not claim success on submit. |
| A9 | Printer capabilities (colour, duplex, paper sizes) come from Qt `QPrinterInfo`. Where the driver reports nothing, the UI says "not detected" and lets the owner proceed manually. | Prompt: never assume capabilities. |
| A10 | Receipt/report PDFs are produced with Qt (`QPdfWriter`), not ReportLab — see ARCHITECTURE §5 (Telugu shaping evidence). ReportLab is dropped from dependencies. | Verified defect in ReportLab Telugu output. |
| A11 | India has no DST: timestamps stored UTC, displayed with fixed +05:30. No tz database dependency. | Simplicity. |
| A12 | Bill number format `YYYY-NNNNNN`-style sequence, never reused, generated inside the save transaction from a counter row. Prefix configurable in Settings. | "Unique and safe." |
| A13 | Single running instance enforced (lock file). | SQLite is single-writer; two copies would risk corruption of intent, not data. |
| A14 | Receipt = A4 only (no thermal roll) in v1. | Prompt. |
| A15 | GST/tax is **out of scope** (no tax fields). | Not requested. Can be added later. |

## 5. Out of scope for v1
Multi-user / roles, cloud sync, mobile app, thermal-printer receipts, GST invoicing, barcode scanners, SMS/WhatsApp sending,
custom printer drivers, automatic Telugu translation of business data.

## 6. Open questions for the owner (status at the end of development)

*Q1 (build location) was answered: GitHub Actions — workflow in `.github/workflows/build-windows.yml`. Q3 (owner PIN): implemented as optional. Q2, Q4, Q5, Q6 are still open: Windows/printer model, Telugu wording review, the owner's real services/units, logo.*

Original list: (need an answer before the stated phase)
1. **Windows build location (blocks Phase 6, and printer testing).** This dev machine is Linux; PyInstaller cannot cross-compile and Wine is not installed. Options: (a) GitHub Actions `windows-latest` builds the `.exe` (needs a GitHub repo), (b) a Windows PC/VM you can give me access to or run a build script on, (c) I deliver source + `build_windows.bat` and you run it on Windows. **Recommendation: (a) or (c).**
2. Is the shop PC Windows 10 or 11 (64-bit)? Which printers (brand/model, any colour/duplex)? Telugu receipt on the real printer can only be verified there.
3. Owner PIN (A1) — yes/no?
4. Telugu UI strings: I will draft them, but a native reader should review them. Who reviews?
5. Which service categories and units does the shop actually bill (per page, per copy, per sheet, per item, per spiral)? Initial list in DATABASE_DESIGN §seed uses zero-priced placeholders.
6. Must receipts show a logo? (v1: text only.)
