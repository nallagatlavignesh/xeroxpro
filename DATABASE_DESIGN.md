# DATABASE_DESIGN — XeroxPro

SQLite 3 · SQLAlchemy 2.x · file `xeroxpro.db`.
PRAGMAs on every connection: `foreign_keys=ON`, `journal_mode=WAL`, `synchronous=NORMAL` (FULL for the backup connection), `busy_timeout=5000`.

## 1. Conventions
- **Money**: `INTEGER` paise. Columns keep the prompt's names (`rate`, `amount`, `grand_total`, …) but hold paise. ₹2.00 → `200`.
- **Quantity**: `INTEGER` thousandths in the column (exact, SUM-able), exposed as `Decimal` through a SQLAlchemy `TypeDecorator`. 2.5 → `2500`. No floats anywhere.
- **Timestamps**: UTC `TEXT` ISO-8601 (`YYYY-MM-DDTHH:MM:SS`). `*_date` business dates: `TEXT YYYY-MM-DD` in IST.
- All tables: `id INTEGER PRIMARY KEY`. Enumerations stored as TEXT with `CHECK (col IN (...))`.
- No financial row is ever deleted. `ON DELETE RESTRICT` on all financial FKs.

## 2. Tables

Columns marked **+** are additions to the prompt's field list, with the reason.

### shop_settings (single row, `CHECK (id = 1)`)
id, shop_name, address, phone, email NULL, receipt_footer, preferred_language (`en`|`te`), currency (`INR`),
**+** default_payment_method, **+** bill_prefix, **+** receipt_show_phone, **+** backup_dir, **+** owner_pin_hash NULL (salted PBKDF2, A1), created_at, updated_at.

### services
id, service_name, category, billing_unit (`page`|`copy`|`sheet`|`item`|`set`|`job`|…, configurable list), is_active, description, created_at, updated_at.
**+** `kind` (`service`|`stationery`|`custom`) so Billing can treat stationery as inventory-backed.

### service_rates (history, append-only)
id, service_id FK, rate (paise), effective_from (TEXT timestamp), created_at.
`UNIQUE(service_id, effective_from)`. Current rate = latest `effective_from <= now`. Changing a rate inserts a row; old bills are unaffected because **bill_items store their own unit_rate**.

### customers
id, customer_name, phone, address NULL, notes, created_at, updated_at. **+** `is_active`. Index on `phone`, `customer_name`. Walk-in = `bills.customer_id IS NULL`.

### bills
id, bill_number UNIQUE, customer_id FK NULL, bill_date, subtotal, discount, grand_total, total_paid, outstanding_amount, status, notes, created_at.
- status: `unpaid`|`partial`|`paid`|`cancelled`|`refunded`.
- **+** idempotency_key UNIQUE (duplicate-submit protection) **+** cancelled_at NULL, cancel_reason NULL **+** created_at already present.
- CHECKs: `subtotal >= 0`, `0 <= discount <= subtotal`, `grand_total = subtotal - discount`, `outstanding_amount = grand_total - total_paid` (for non-cancelled bills), `total_paid >= 0`.
- **Credit sales require a customer** (`outstanding_amount > 0` ⇒ `customer_id NOT NULL`) — enforced in the use case and by trigger/CHECK.
- Indexes: `bill_date`, `customer_id`, `status`.
- `total_paid`/`outstanding_amount` are denormalized caches maintained only by use cases; a test recomputes them from `payments` to prove consistency.

### bill_items
id, bill_id FK, service_id FK NULL, product_id FK NULL, description, quantity, unit, unit_rate, amount, service_details (JSON text: pages, copies, colour, duplex, page-range…),
**+** unit_cost NULL (purchase price captured at sale for stationery → profit estimate, A5).
CHECK `quantity > 0`, `unit_rate >= 0`, `amount = round(quantity*unit_rate)`, `NOT (service_id IS NULL AND product_id IS NULL AND description = '')`.
Free-form lines (no service) are allowed with description.

### payments
id, bill_id FK NULL, amount, payment_method (`cash`|`upi`|`other`), payment_date, reference_number NULL, notes,
**+** job_id FK NULL (job advance/balance, A3), **+** kind (`payment`|`refund`; refunds stored as positive amount with kind=refund), **+** idempotency_key UNIQUE, **+** created_at.
CHECK exactly one of `bill_id`, `job_id` is NOT NULL; `amount > 0`.
Overpayment (`amount > outstanding`) rejected in the use case.

### customer_ledger
id, customer_id FK, transaction_type (`bill`|`payment`|`bill_reversal`|`refund`|`adjustment`), reference_type (`bill`|`payment`), reference_id, debit, credit, transaction_date, description.
`UNIQUE(reference_type, reference_id, transaction_type)` → retries cannot duplicate. Balance = Σdebit − Σcredit (never stored).
Only rows for customers with a customer_id; walk-in bills create none (they must be fully paid).

### products
id, product_name, category, purchase_price, selling_price, stock_quantity, minimum_stock, unit, is_active. **+** created_at, updated_at.
Prompt: stock may not go negative "without an explicit authorized adjustment workflow". Design: **no DB CHECK**; the use case rejects any sale/adjustment that would make stock < 0 unless the caller passes `allow_negative=True`, which the UI only does after the owner PIN/confirm + reason, and which writes an `audit_log` row. Reconciliation test: `stock_quantity = Σ inventory_transactions.quantity`.

### inventory_transactions (append-only)
id, product_id FK, transaction_type (`purchase`|`sale`|`return`|`adjustment`|`sale_reversal`), quantity (signed: + in, − out), unit_cost, reference_id NULL (bill_id / null), transaction_date, notes.
`product.stock_quantity = Σquantity` — reconciled by test.

### expenses
id, category, description, amount, payment_method, expense_date, notes. **+** is_voided, void_reason (edit allowed; voiding rather than deleting; edits write `audit_log`), created_at, updated_at.

### job_orders
id, job_number UNIQUE, customer_id FK, job_description, service_type, total_amount, advance_amount, balance_amount, expected_delivery, job_status, created_at, updated_at. **+** notes.
`advance_amount` = Σ payments of the job (cache). status ∈ `received|pending|in_progress|completed|delivered|cancelled`.
Customer phone is read from `customers` (not duplicated).

### job_status_history (append-only)
id, job_id FK, previous_status NULL, new_status, changed_at, notes.

### application_records
id, customer_id FK, application_type, service_charge, payment_status, reference_number, application_status, application_date, notes,
**+** bill_id FK NULL (A4). `payment_status` is a display value derived from the bill; **never** stores passwords, OTPs, Aadhaar — free-text `notes` field shows a warning label.

### printer_settings
id, printer_name, printer_type (`receipt_a4`|`documents`|`other`), is_default, paper_size, created_at, updated_at. UNIQUE(printer_name, printer_type).

### app_metadata
id, key UNIQUE, value. Keys: `schema_version`, `app_version`, `last_backup_at`, `bill_counter:<year>`, `job_counter`.
(Counters are read+incremented inside the saving transaction → no gaps from races, no reuse.)

### Additional tables (not in the prompt, needed by its requirements)
- **audit_log**: id, at, action, entity_type, entity_id, reason, details (JSON). Append-only.
- **daily_closings**: id, closing_date UNIQUE, expected_cash, counted_cash, difference, notes, created_at (Phase 3 "daily closing").
- **backup_history**: id, file_path, created_at, size_bytes, kind (`auto`|`manual`|`export`|`pre_restore`), status (`ok`|`failed`), message.
- **lookup_values**: kind, value, sort_order — editable lists in Settings (billing units, expense categories, application types, service categories).

## 3. Relationships

```
customers 1──* bills 1──* bill_items *──0..1 services 1──* service_rates
   │             │  └──* payments *──0..1 job_orders *──1 customers
   │             └──0..1 application_records
   └──* customer_ledger          bill_items *──0..1 products 1──* inventory_transactions
job_orders 1──* job_status_history        expenses (standalone)
```

## 4. Derived figures (all computed from the above, never stored)
| Figure | Formula |
|---|---|
| Sales (day) | Σ `bills.grand_total` where bill_date = day, status ∉ cancelled/refunded |
| Collections (day) by method | Σ payments(kind=payment) − Σ payments(kind=refund) by `payment_date`, method |
| Outstanding credit | Σ ledger(debit − credit) over customers |
| Expenses (day) | Σ expenses not voided |
| Cash movement | cash payments − cash refunds − cash expenses |
| Estimated profit | Sales − Σ(bill_item.unit_cost × qty) − operating expenses (excl. stock purchase) |

Note: collections on a day include money for bills dated earlier (udhar recovery) and job advances. Reports must show them separately from "sales".

## 5. Seed data
Only on first run: shop_settings row (`shop_name='XeroxPro'` placeholder), the eight service **categories** from the prompt as services with **no rate rows** (so the UI prompts "set price"), lookup lists (units, expense categories, application types), payment methods. Marked in UI as "set your rate". Dev-only sample data lives in `tools/sample_data.py` and is never loaded in production.

## 5b. Rules fixed in Phase 2 (supersede earlier text)
- `*_date` columns (`bill_date`, `payment_date`, `transaction_date`, `expense_date`) are **IST business dates** (`YYYY-MM-DD`); `created_at` and other timestamps are UTC.
- **Ledger**: every bill with a customer writes a `bill` debit for `grand_total` (even if paid in full) and a `payment` credit per payment. Walk-in bills write no ledger rows.
- **Cancellation** (`cancel_bill`): status becomes `cancelled` (nothing paid) or `refunded`; each original payment gets a `kind='refund'` payment row in the same method; ledger gets `refund` debits and a `bill_reversal` credit of `grand_total`; stationery lines get `sale_reversal` stock rows; `total_paid` and `outstanding_amount` are set to 0; an `audit_log` row records the reason. Always a full refund.
- **Rates**: a bill line's price must equal the service's rate (or product `selling_price`) at bill time; any other price needs `rate_override` (owner PIN if set) and writes a `rate_override` audit row. A service with no rate cannot be billed without an override.
- Bill numbers: `<prefix><IST year>-<6-digit counter>`, counter per year in `app_metadata` (`bill_counter:<year>`).

## 5c. Rules fixed in Phase 3
- `daily_closings.opening_cash` added by migration **0002** (table rebuilt so stored DDL equals the models). Expected drawer cash = opening cash + cash received - cash refunds - cash expenses; opening defaults to the previous closing's counted cash. Re-closing a day updates the row and writes a `closing_corrected` audit row.
- Customer payments (`record_customer_payment`): applied oldest bill first (or to one chosen bill); one `payments` row + one ledger credit per bill touched; idempotency key `<key>:<bill_id>` makes a repeat a no-op. Overpayment is refused (no advance balances).
- Sales = grand_total of live bills by `bill_date`; money received = payments by `payment_date` minus refunds; credit outstanding = ledger balance; cash movement = cash in - cash refunds - cash expenses. Estimated profit excludes a 'Stationery purchases' expense because stock cost is already counted at sale.

## 6. Bill-save algorithm (SaveBill)
1. Validate lines (qty > 0, rate ≥ 0, stock available).
2. `BEGIN IMMEDIATE`.
3. If a bill exists with this `idempotency_key` → return it (no changes).
4. Allocate `bill_number` from counter.
5. Insert bill, items (rate/unit_cost copied), inventory `sale` transactions + product stock updates.
6. Insert payments (each with own idempotency key), update `total_paid`, `outstanding`, `status`.
7. If outstanding > 0 → ledger debit for the bill amount; each payment → ledger credit.
8. Commit. Any exception → rollback, nothing persisted.

## 7. Indexes
bills(bill_date), bills(customer_id), bills(status), payments(payment_date, payment_method), payments(bill_id), payments(job_id), customer_ledger(customer_id, transaction_date), inventory_transactions(product_id), expenses(expense_date), job_orders(job_status, expected_delivery), service_rates(service_id, effective_from).

## 8. Migrations / schema versioning
- `app_metadata.schema_version` (integer).
- `database/migrations/NNNN_name.py`, each with `upgrade(connection)` using plain SQL/`op` helpers. Runner applies pending migrations in order, each in its own transaction, **after copying the DB to a `pre-migration-vN.db` backup**.
- 0001 = baseline DDL above. A test asserts: SQLAlchemy models ⇔ migrated schema produce identical table/column sets (prevents drift), and that migrating a v1 DB with data to a (synthetic test) v2 keeps data.
- A DB with a **newer** schema than the app refuses to open (prevents old exe damaging newer data).
