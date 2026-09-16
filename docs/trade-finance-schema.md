# Trade Finance — database schemas

Six tables behind the Trade Register and the weekly trade finance report. Five
are owned by this application; one, `trade_finance_data`, is the reporting table
the ETL reads — and the contract between them is where every problem so far has
come from.

Generated from the live Django models (`apps/trade_register/models.py`,
`apps/staff_management/models.py`) on 2026-09-16. Types are as PostgreSQL holds
them.

---

## How the tables relate

The desk keys a transaction into `trade_register_entry`. Saving it writes or
updates a linked row in `trade_finance_data`, which is the table the weekly
report reads. Four reference tables price the transaction and constrain what can
be chosen.

```
  product_category ──┬──> product ──┐
                     └──> tariff <──┘
                                    │
  currency ─ ─ ─ (code) ─ ─ ─ ─ ─ ─ ┤
                                    ▼
                         trade_register_entry ──┐ (parent_id: self, for
                                    │           └─ amendments etc.)
                                    │ 1:1 sync on save
                                    ▼
                           trade_finance_data
                                    │ SELECT ... WHERE year = ?
                                    ▼
                    trade_finance_report.py  (on the host, python3.6)
```

**The link is one-to-one and lives on the register.** `trade_register_entry.tf_id`
points at the `trade_finance_data` row it owns.

The sync writes with `.update()` / `.create()` rather than `.save()`,
deliberately: `.update()` fires no model signals, so the register → reporting
write cannot trigger the reverse sync and loop. On update it is non-destructive —
only fields the register actually holds a value for are written, so a blank in
the register never wipes something Trade Finance already had.

---

## The reporting contract

`trade_finance_data` predates the register. It is shaped for the report rather
than for the desk, and that shows: dates are text, the month is a two-character
number, and there is no foreign key to anything. Anyone writing to it has to
match those conventions exactly.

The weekly report reads:

```sql
SELECT originating_branch, rm_name, rm_code, guarantee_ref, product_type,
       customer_id, segment, our_customer AS our_applicant_customer,
       beneficiary, currency, amount_fcy, issue_date, expiry_date,
       commission_lcy AS commission, month, fx_rate, year,
       security_type, cash_cover_amount, cash_cover_percentage, other_security
FROM   trade_finance_data
WHERE  year IN ('2026');
```

It then builds a period label from two of those columns:

```python
pd.to_datetime(month.astype(str) + '-' + year, format='%m-%Y')
```

> **`month` must be a two-digit number, not a name.**
> The register wrote `SEPTEMBER` for two weeks; the first such row raised
> `ValueError: time data 'SEPTEMBER-2026' does not match format '%m-%Y'` and
> failed the **entire** report — not just that row. Because the script runs on
> the host, nothing in the application knew: the desk pressed Send Report and no
> report arrived. Fixed in the model and repaired in both tables by migration
> `trade_register.0010`. Values are now `'01'`–`'12'`.

---

## Reference numbers

Three product families, three patterns, reverse-engineered from the desk's
historical workbook. The prefix changed from `HFC/` to `HFCB/` in 2026.

| Family | Pattern | Notes |
|---|---|---|
| Guarantee | `HFCB/GTE/YYMMDD/NN` | Issue date, then a counter that resets each day (01, 02, …) |
| Export LC | `HFCB/ELC/YYMMDD/NN` | Same date-based scheme |
| Import LC | `HF#####` | Running number (max + 1). These are the bank's own LC numbers, so the tool *suggests* the next one and the desk may overwrite it with the real core-banking number |

Only an **issuance** draws a fresh number. The other five actions act on an
instrument that already exists and reuse the parent's reference with the action
as a suffix — `HFCB/GTE/260630/01 - AMENDMENT` — and are stored as child rows via
`parent_id`.

Every uniqueness check scans **both** the register and the legacy
`trade_finance_data`, so a generated number can never collide with a historical
one.

### The six actions

`ISSUANCE` · `AMENDMENT` · `CANCELLATION` · `ADVISING` · `BILL ACCEPTANCE` ·
`SETTLEMENT`

The action is what selects the charge: the tariff book prices *(category,
action)*, not the product alone. "LC Amendment Charges", "Cancellation
Commission" and "LC Advising Charges" are separate lines.

---

## `trade_register_entry` — transactional, this app owns it

One row per trade transaction the desk keys in. Amendments, cancellations and the
rest are child rows pointing at the issuance through `parent_id`.

| Column | Type | Notes |
|---|---|---|
| `id` | bigserial **PK** | |
| `tf_id` | bigint **UNIQUE FK** | One-to-one link to `trade_finance_data`. Null until the first sync |
| `originating_branch` | varchar(255) | Branch that wrote the business |
| `rm_name` | varchar(255) | Relationship manager, resolved from the HR roster |
| `rm_code` | varchar(255) | Their sales/service code |
| `guarantee_ref` | varchar(255) *idx* | The generated reference |
| `product_id` | bigint **FK** | → `trade_register_product`. Drives pricing and the reference family |
| `product_type` | varchar(255) | Denormalised product name, copied on save so history survives a rename |
| `action` | varchar(32) | One of the six actions. Selects the tariff line |
| `parent_ref` | varchar(255) | Parent's reference as typed, kept even when the parent row cannot be resolved |
| `parent_id` | bigint **FK** | Self-reference to the issuance this acts on |
| `amount_delta` | numeric(25,2) | Change to the facility amount on an amendment. Sums onto the parent |
| `new_expiry_date` | date | Extended expiry on an amendment |
| `customer_id` | bigint | Core banking customer number |
| `segment` | varchar(255) | Business segment |
| `our_customer` | varchar(255) | The applicant |
| `beneficiary` | varchar(255) | Who the instrument is in favour of |
| `currency` | varchar(3) | ISO code, validated against `trade_register_currency` |
| `amount_fcy` | numeric(25,2) | Face amount in the instrument's own currency |
| `fx_rate` | numeric(10,6) | Rate to KES at issue |
| `commission` | numeric(20,6) | Priced from the tariff unless overridden |
| `commission_override` | boolean | True when the desk set the figure by hand; stops repricing on save |
| `excise_duty` | numeric(20,2) | Follows the commission, override or not |
| `tariff_code` | varchar(30) *idx* | Which tariff line priced it — the audit of the charge |
| `reporting_date` | date | Week the transaction is reported in |
| `issue_date` | date | A real date here. Sets `month` and `year` |
| `is_open_ended` | boolean | True for a facility with no maturity; forces `expiry_date` null |
| `expiry_date` | date | Null when open-ended |
| `security_type` | varchar(255) | Cash cover, lien, none, etc. |
| `cash_cover_amount` | numeric(20,4) | |
| `cash_cover_percentage` | numeric(10,6) | |
| `other_security` | varchar(255) | |
| `is_archived` | boolean *idx* | Set by the daily expiry job. Archived rows leave the live register |
| `archived_on` | date | |
| `month` | varchar(32) | **Two-digit number** from `issue_date`: `'09'` |
| `year` | varchar(8) *idx* | `'2026'`. The report filters on this |
| `created_by_id` | integer **FK** | → `auth_user` |
| `created_at`, `updated_at` | timestamptz | |

Full change history is kept in `trade_register_historicaltraderegisterentry`
(django-simple-history): every column above plus the acting user and the type of
change. The same pattern exists for product, category and tariff.

---

## `trade_finance_data` — read by the ETL

The reporting table. Predates the register and is shaped for the report — text
dates, no foreign keys, everything flattened.

| Column | Type | Notes |
|---|---|---|
| `id` | bigserial **PK** | |
| `originating_branch` | varchar(255) | |
| `rm_name` | varchar(255) | |
| `rm_code` | varchar(255) | Nullable |
| `guarantee_ref` | varchar(255) | **Not unique** — amendments repeat the parent's reference with a suffix |
| `product_type` | varchar(255) | Free text. No link to the product table |
| `customer_id` | bigint | |
| `segment` | varchar(255) | |
| `our_customer` | varchar(255) | Aliased to `our_applicant_customer` in the report |
| `beneficiary` | varchar(255) | |
| `currency` | varchar(3) | |
| `amount_fcy` | numeric(25,2) | |
| `issue_date` | varchar(255) | **Text, not a date.** The register writes ISO `YYYY-MM-DD` |
| `expiry_date` | varchar(255) | **Text.** Empty string for an open-ended facility — not null |
| `commission_lcy` | numeric(20,6) | Aliased to `commission` in the report |
| `month` | varchar(255) | **`'01'`–`'12'`.** Parsed as `%m`. A name here fails the whole report |
| `fx_rate` | numeric(10,6) | |
| `year` | varchar(255) *idx* | The report's only filter |
| `security_type` | varchar(255) | Nullable |
| `cash_cover_amount` | numeric(20,4) | Nullable |
| `cash_cover_percentage` | numeric(10,6) | Nullable |
| `other_security` | varchar(255) | Nullable |
| `updated_at` | timestamptz | |

---

## Reference data

Seeded by migration and editable by the desk. Between them they decide what can
be chosen, what it is called, and what it costs.

### `trade_register_product`

What is being issued. Carries its own default pricing, and the reference family
that decides the number format.

| Column | Type | Notes |
|---|---|---|
| `id` | bigserial **PK** | |
| `code` | varchar(40) **UNIQUE** | Desk's product code |
| `name` | varchar(255) **UNIQUE** | |
| `category_id` | bigint **FK** | → `product_category`. Drives the category → product cascade in the form |
| `ref_family` | varchar(16) | `guarantee` · `import_lc` · `export_lc`. Decides the reference pattern |
| `tariff_id` | bigint **FK** | Default tariff line |
| `commission_basis` | varchar(16) | `flat` · `per_quarter` · `per_annum` · `none` |
| `commission_rate` | numeric(9,6) | Fraction, not a percentage |
| `minimum_commission` | numeric(20,2) | Floor applied after the rate |
| `is_active` | boolean | Deactivate rather than delete — entries point here |
| `sort_order` | integer | Order in the dropdown |

### `trade_register_product_category`

The grouping the tariff book is organised by — the charge is a function of
category and action.

| Column | Type | Notes |
|---|---|---|
| `id` | bigserial **PK** | |
| `code` | varchar(30) **UNIQUE** | |
| `name` | varchar(120) **UNIQUE** | |
| `description` | text | |
| `is_active` | boolean | |
| `sort_order` | integer | |

### `trade_register_tariff`

The bank tariff book, line by line. Indexed on `(category, action, is_active)`,
because that triple is how a charge is looked up.

| Column | Type | Notes |
|---|---|---|
| `id` | bigserial **PK** | |
| `code` | varchar(40) **UNIQUE** | Written onto every entry it prices |
| `name` | varchar(255) | The tariff book's own wording |
| `description` | text | |
| `category_id` | bigint **FK** | |
| `action` | varchar(32) | Which of the six this line prices |
| `product_id` | bigint **FK** | Set when a line applies to one product only |
| `commission_basis` | varchar(16) | Adds `per_month` and `per_instance` to the product's list |
| `commission_rate` | numeric(9,6) | |
| `fixed_amount` | numeric(20,2) | For a flat charge instead of a rate |
| `minimum_commission` | numeric(20,2) | |
| `charge_currency` | varchar(3) | Some lines are charged in USD regardless of the instrument |
| `excise_rate` | numeric(9,6) | Excise duty on the commission |
| `manual_note` | varchar(255) | Set where the book says "by arrangement" — the tool shows the note instead of computing a figure |
| `is_active` | boolean | |
| `sort_order` | integer | |

### `trade_register_currency`

The currencies the desk may pick. A table rather than a hard-coded list, because
the desk kept needing ones that were not there.

| Column | Type | Notes |
|---|---|---|
| `id` | bigserial **PK** | |
| `code` | varchar(3) **UNIQUE** | ISO 4217 |
| `name` | varchar(100) | |
| `is_active` | boolean | |
| `sort_order` | integer | KES first |

---

## Traps

Things that have already caused an incident, or would. Worth reading before
writing to any of these tables.

- **`month` is `'09'`, never `'SEPTEMBER'`.** One bad value fails the entire
  weekly report, on the host, silently.
- **`issue_date` and `expiry_date` in `trade_finance_data` are text.** The
  register writes ISO; an open-ended facility gets an empty string, not null. Do
  not assume you can compare or sort them as dates.
- **`guarantee_ref` is not unique.** An amendment reuses its parent's reference
  with the action appended. Counting distinct references is not counting
  instruments.
- **Amendments are child rows, not edits.** The live position of a facility is
  the issuance plus the sum of its children's `amount_delta`, with expiry taken
  from the latest `new_expiry_date`. Reading the issuance alone understates it.
- **Aggregating makes the queryset unordered.** Adding those sums puts a
  `GROUP BY` on the query, Django then reports it as unordered, and paging
  becomes unstable — which is how the register's export quietly came up short.
  Order explicitly.
- **Deactivate reference rows; do not delete them.** Entries hold the product and
  tariff by id, and the charge audit depends on the tariff line still existing.
- **The report is triggered from the app but runs on the host.** A failure never
  reaches the application — the desk presses Send Report and nothing arrives.
  Check the host's watcher log when a report is missing.
