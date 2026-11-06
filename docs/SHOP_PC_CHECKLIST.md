# Checks to do once on the real shop computer and printers

These cannot be tested on the development machine (no Windows, no printers there). Tick each box and write what you
saw. **Until these are done the printing and Windows parts are "untested on real hardware".**

Computer: ______________  Windows version: ________  Date: __________  Done by: __________

## A. Installation
- [ ] Installed / unzipped without errors. (SmartScreen / antivirus message: ________________)
- [ ] `XeroxPro.exe --selftest C:\Temp\selftest.txt` ends with `SELFTEST PASSED` (attach the file).
- [ ] The program opens in under ~10 seconds and fits the screen (resolution: ________; 1366×768 is the minimum).
- [ ] Switch language English ↔ Telugu: every menu and button changes, no empty boxes (▯) or broken letters.
- [ ] Close and open again: shop name, rates and bills are still there.

## B. Receipts (use the receipt printer)
- [ ] *Settings → Printers*: the printer list matches Windows *Printers & scanners*.
- [ ] Make a bill, **Save and view receipt → Print** on A4. English receipt: margins OK, nothing cut off.
- [ ] Telugu receipt (change *Receipt language* in the preview): conjunct letters correct (e.g. "ధన్యవాదాలు", "శ్రీ"),
      ₹ sign visible.
- [ ] A long bill (about 40 lines) continues on page 2 with the table heading repeated.
- [ ] **Save as PDF** opens correctly in a PDF viewer.

## C. PDF printing (repeat for every printer that will be used)

Printer name: __________________________

- [ ] *PDF Printing → ⟳*: printer listed. Capabilities line (colour / double-sided / paper) matches the real printer:
      colour ____  double-sided ____  paper sizes ____ (if "not detected", note it)
- [ ] 5-page PDF, all pages, 1 copy, B&W, single-sided → 5 pages come out.
- [ ] Pages `2-4`, 2 copies → pages 2,3,4 printed twice, **in order per copy**.
- [ ] Double-sided (if supported) → both sides used; sheet count equals the screen's "Paper sheets".
- [ ] Colour (if supported) → printed in colour; B&W → greyscale.
- [ ] Switch the printer off / unplug → the program shows a clear message and does **not** say it was sent.
- [ ] Pause the Windows queue, print, then cancel in the queue → the program only ever said "Sent to the printer queue".
- [ ] A3 / Letter PDF (if you print them) → correct paper chosen.

## D. Backup and restore
- [ ] *Back up now* → file appears in the folder.
- [ ] *Copy to USB* with a real USB stick → file on the stick; take the stick to another PC and *Restore from a file*
      there (or on this PC after changing something) → data returns to the backup state.
- [ ] Next morning: a new automatic backup (`…-auto.db`) exists without doing anything.
- [ ] Unplug the USB stick and try *Copy to USB* → a clear error, nothing breaks.

## E. Everyday use
- [ ] A real day's bills entered next to the notebook; the Dashboard "Sales" equals the notebook total.
- [ ] *Close the day*: counted cash vs expected makes sense.
- [ ] Reports → Sales (Month) → *Save as PDF* and *Save as Excel* open fine; numbers equal the Dashboard.

Problems found: ______________________________________________________________
