# XeroxPro — User Manual (for the shop owner)

XeroxPro replaces the notebook: it makes bills and receipts, keeps udhar (credit), stock, expenses and jobs, prints
PDFs, shows daily totals and keeps backups. It works **without internet**. You can switch between **English and
Telugu** at any time with the *Language* box at the top right.

> The Telugu words in the program are a first draft. If any word looks wrong, tell the person who set up the program;
> it can be changed in one file.

---

## 1. First-time setup (do once)

Open **Settings**.

1. **Shop & receipt** tab — type your *shop name*, *address*, *phone* and a *receipt footer* (for example "Thank you,
   visit again"). Press **Save**. The shop name appears at the top of every receipt.
2. **Services & Rates** tab — the program does **not** know your prices. For each service select it and press
   **Set rate**. Type the price per unit, for example `2` or `2.50`.
   - Services are things like Xerox, B&W Printing, Colour Printing, Lamination, Spiral Binding, Scanning.
   - Use **Edit service** to change a name or unit (page, copy, sheet, item, set, job) and **Add service** for new ones.
   - If you change a rate later, **only new bills use it**. Old bills keep the price they were made with.
3. **Printers** tab — choose which printer prints *receipts* and which prints *documents*. "Not detected" means Windows
   did not say whether the printer can do colour or double-sided; it may still work.
4. **Owner PIN** (optional, in the *Shop & receipt* tab) — a 4–6 digit number asked when you cancel a bill, change a
   price on a bill, restore a backup, or make stock go below zero. Useful if staff use the computer.
5. **Backup & Restore** — look at the *Backup folder*. Best is a folder on another drive. See section 10.

## 2. Every day

1. Start XeroxPro. (It makes the day's automatic backup by itself.)
2. Make bills in **New Bill** as customers come.
3. At closing time, on the **Dashboard** press **Close the day (cash count)** and count the cash in the drawer.
4. Close the program normally (it makes another backup).

## 3. Making a bill (New Bill)

1. Choose the **Service / item** (the rate appears). Type the **Quantity** and **Copies**.
   *Example: 25 pages × 2 copies × ₹2 = ₹100 — quantity 25, copies 2.*
2. Press **Add to bill**. Repeat for more lines. Select a line and press **Remove selected** to take it out.
3. **Discount** — type an amount (₹) or choose % and type the percentage.
4. **Payment** — type how much the customer paid in **Cash**, **UPI** or **Other** (you can split). **Full payment**
   fills the whole amount using your default method.
5. **If the customer did not pay everything** the rest is *udhar*. Choose the **Customer** (or press **New customer**).
   A bill with money due always needs a customer. Walk-in customers must pay in full.
6. Press **Save bill**, or **Save and view receipt** to see/print it straight away.

The same screen has a **Bill History** tab: search by bill number, customer name or phone, filter by date or status,
open any bill, **Print** or **Save as PDF** the receipt again, in English or Telugu.

**Changing a price on one bill:** tick **Change rate**, type the new price (the PIN is asked if you set one). This is
written in a log.

**Cancelling a bill:** open it in Bill History → **Cancel this bill** → type the reason. The bill is **not deleted**;
it is marked cancelled, all money taken is refunded in the same way it was paid, stationery goes back to stock and the
customer's udhar is corrected.

## 4. PDF Printing

1. **Open PDF**. You see a preview, the number of pages and the paper size.
2. **Pages to print** — leave empty for all, or type `1-3, 5` for pages 1, 2, 3 and 5.
3. Choose **Copies**, **Black & white / Colour**, **Single-sided / Double-sided**, the **Printer** and **Paper**.
4. The screen shows **pages**, **paper sheets** (double-sided uses half) and the **estimated cost**.
   If the customer wants a different number of pages billed, change **Pages to bill**.
5. **Print** sends it to the printer. The program says *"Sent to the printer queue"* — **look at the printer**; the
   computer cannot know whether paper really came out.
6. **Add to bill** puts the printing on the New Bill screen with the right pages, copies and price.

If the printer says it cannot do colour or double-sided, the program stops you. If a printer is unplugged or has an
error you get a clear message.

## 5. Customers & Udhar

- Search customers; the list shows who owes money. Tick **Only customers who owe money** for the outstanding list.
- Click a customer to see the **Ledger** (every bill and payment with the balance after each), **Bills** and **Payments**.
- **Receive udhar payment** — type the amount and method. It clears the **oldest bills first** (the screen shows which).
  To pay one particular bill, select it in the *Bills* tab and press **Pay selected bill**.
- A payment can never be more than what is owed.

## 6. Expenses

**Expenses → Add expense**: category, amount, how you paid, date. Use **Edit expense** to correct a mistake. A wrong
entry is **cancelled** (with a reason), never deleted. Totals by category are shown at the bottom.
*Stock you buy to resell* is recorded in **Inventory**, not here, otherwise it would be counted twice.

## 7. Job Orders

For work taken in advance (wedding cards, bulk binding…): **New job** — customer, work, total charge, advance paid,
delivery date. Use **Collect payment** for the balance and **Change status** (Received → Pending → In progress →
Completed → Delivered). A job cannot be marked *Delivered* until the balance is paid. Overdue jobs are red.
**Status history** shows every change.

## 8. Inventory (stationery)

**New product** (name, buying price, selling price, minimum stock). **Add stock (purchase)** when you buy more.
Selling a product on a bill reduces the stock automatically; cancelling the bill puts it back.
**Customer return** adds goods that come back. **Adjust stock** corrects the count after you check the shelf (a reason
is required). Low stock is shown in orange with the word LOW, and on the Dashboard.
Selling more than you have in stock is blocked.

## 9. Online Applications

Record each form you help with: customer, type, your charge, reference number, status. **Bill this charge** sends the
amount to New Bill. **Never write passwords, OTPs or Aadhaar numbers anywhere** — the program refuses obvious ones.

## 10. Reports

Choose the report, then the period (Day, Week, Month or Custom dates). **Save as PDF**, **Save as Excel** or **Print**.

| Report | What it tells you |
|---|---|
| Sales | per-day bills, sales, cash/UPI/other received, refunds, expenses, cash movement |
| Service-wise sales | what sold most |
| Cash / UPI / Other collection | every payment received and refunded |
| Customer outstanding | who owes how much, and since when |
| Expenses | by category |
| Inventory | stock and its value |
| Job status | jobs received and where each stands |

### Understanding the numbers (they are different on purpose)

- **Sales** = what you *billed*, even if the customer will pay later.
- **Money received** = cash/UPI that really came in (including old udhar paid back, minus refunds).
- **Udhar outstanding** = what customers still owe.
- **Cash movement** = how much the cash drawer changed (cash in − cash refunds − cash expenses).
  *It is not "sales minus expenses".*
- **Estimated profit** = sales − cost of stationery sold − expenses. It is an **estimate**: paper and toner used per
  page are not counted. Job orders are not counted in sales.

## 11. Backup and Restore

- Backups are automatic (every day, and when you close the program). Press **Back up now** any time.
- **Copy to USB / another folder** — do this regularly. A backup on the same computer does not help if the computer fails.
- **Restore** puts the data back as it was at the backup's time. Everything entered after that is replaced, but a
  **safety copy of your current data is saved first**, so you can undo a wrong restore.
- Full guide: `docs/BACKUP_RESTORE.md`.

## 12. If something goes wrong

| Problem | What to do |
|---|---|
| "Something went wrong…" window | Note what you were doing and call for help. Details are saved in `%LOCALAPPDATA%\XeroxPro\logs`. |
| "The data file is busy" | Close any second copy of XeroxPro and try again. |
| "The disk is full" | Free space on the computer, then continue. |
| Printer not found / error | Check power, cable, paper; press the ⟳ button next to the printer list. |
| A number looks wrong | Open the report for that day; each figure is explained under the table. |
| Wrong data after a mistake | Restore a backup (section 11). |

## 13. What XeroxPro does not do

No GST/tax invoices, no SMS/WhatsApp, no thermal-roll receipts, no several-pages-per-sheet printing, no merging two
computers' data. It is for **one shop computer**.
