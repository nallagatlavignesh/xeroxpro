# Known limitations

## Printing
- Printing is *submitted to the Windows print queue*. The computer cannot know whether paper came out; the app says
  "Sent to the printer queue", never "Printed".
- Colour, double-sided and paper sizes are what the printer driver reports. Where the driver reports nothing the screen
  says "not detected" and the job is allowed; the printer may still ignore the request.
- Pages are drawn as pictures (300 dpi at most) and fitted to the printable area. Very large PDFs take a while and
  the screen waits until they are sent. Several pages per sheet ("N-up"), booklet printing and tray selection are not supported.
- Real printer behaviour has only been tested against fake printers and a PDF file "printer" on the Linux dev machine.
  The checklist in TEST_REPORT.md must be run on the shop PC.

## Money
- Job orders are not bills: their advance/balance payments appear in money received, cash movement and the
  daily closing, but the job total is **not** counted as dashboard "sales" (no job->bill conversion yet).
- Cancelling a bill or job always refunds everything collected, by the original payment methods.
- Customer payments cannot exceed what is owed (no advance balance / customer credit).
- Sales for a past day change if one of its bills is cancelled later.
- No GST/tax fields.

## Security
- The owner PIN is optional and protects rate changes, bill cancellation and negative-stock adjustments.
  It is a convenience lock for a shared shop PC, not protection against someone with access to the Windows account.
- Notes are screened for Aadhaar-like numbers and "password/OTP: ..." text; this is a safety net, not a guarantee.

## Language
- Telugu wording is a draft and needs review by a native reader.
- Service and product names, customer names and notes are shown exactly as typed (never auto-translated).

## Reports and backup
- Reports show one row per day for sales-type reports; the estimated profit is an estimate (paper, toner and machine wear
  are not costed per page) and job orders are not in "sales".
- Excel and PDF exports are generated on this computer; the Excel file keeps Telugu text but the font used for display
  is chosen by Excel.
- The report "Print" button sends the PDF layout to the print queue like any other print (see Printing).
- Backups protect against mistakes and a damaged database, not against losing the whole computer unless a copy
  is also kept on a USB stick or another drive.
- Restoring replaces all data; it cannot merge a backup into current data.
- The automatic backup runs when the program starts, hourly while it is open, and when it closes. If the PC is only
  ever switched off at the power button, the last full-day backup is the morning one.

## Packaging and platform
- The Windows program has **not been built or run on Windows yet**: this was developed on Linux and PyInstaller cannot
  cross-compile. A Linux build of the same spec was produced and passed `--selftest` (bundled fonts, migrations,
  Telugu PDF, backup/restore, all screens), but Windows-specific behaviour (fonts, printing API, file locking,
  antivirus) is covered only by the GitHub Actions run and `docs/SHOP_PC_CHECKLIST.md`.
- The program is not code-signed: Windows SmartScreen shows a warning on first run ("More info -> Run anyway").
- Only one shop computer is supported; two computers cannot share or merge data.
- The database is in the user's profile folder; a different Windows user sees different data (use one login for the shop).
- Test coverage of screens is by automated widget tests (headless) and screenshots, not by pixel comparison.
