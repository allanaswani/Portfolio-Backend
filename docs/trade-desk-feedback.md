# Trade desk feedback — what changed

Five things the desk raised about the Trade Register / Trade Finance form.

## 1. The RM list — not searchable, incomplete, and out of date

`RMLookupView` read `staff_employee_data` (filtered to `is_active`) unioned with
DSR seller codes, and shipped the whole list to the browser for a native
`<select>` the desk had to scroll.

Three problems in one: a native select cannot be searched; `staff_employee_data`
is a partial list nothing keeps in step with HR, so RMs were missing; and its
`is_active` flag lags, so people who had been promoted or had left were still
offered.

It now reads **`employee_table`** — the roster the employee-master upload
maintains — excluding anyone with `staff_exit_date` set or `exit = 1` (either
marker alone can carry the exit, depending on which sheet HR recorded it on).
Each option shows the person's current job title and department.

Searching moved to the server (`?search=&limit=`, default 50). Sales codes are
looked up from `dsr_sales_codes` and `staff_employee_data` by PF number, and
only for the rows being returned.

`?include_exited=1` brings leavers back, marked, for backdating a transaction to
someone who has since gone. An RM already recorded on an existing entry stays
visible on that entry regardless — a record must not lose its RM because the
person left.

The frontend uses `components/ui/SearchSelect.tsx`: type to search, arrows to
move, Enter to pick.

## 2. Product ID should fill in the name — and the calculation

`TradeProduct` had `code`, `name` and `ref_family`. There was **no rate anywhere
in the database**, so nothing could be calculated; commission was typed on every
transaction with nothing to check it against.

Products now carry their own pricing:

| Field | Meaning |
|---|---|
| `commission_basis` | `flat` (% of amount), `per_quarter` (% per quarter or part), `per_annum` (% pro-rated over the tenor), `none` |
| `commission_rate` | percent — `0.5` means 0.5% |
| `minimum_commission` | a floor in local currency, applied after the rate |

`TradeProduct.quote()` returns the figure **and how it got there**, so the desk
sees the working rather than a bare number. It declines to guess: an open-ended
instrument has no tenor, and a per-period rate without an expiry date is not
knowable, so `calculable` comes back `false` with the reason instead of
defaulting to one period.

Every product ships on `none`, which is exactly how they behaved before — no
existing record is repriced by this change until somebody sets a rate.

Rates live in the database on purpose: changing one is an edit
(`PATCH /trade_register/products/<id>/`, admin only), not a code change and a
deploy. Changes are kept in the audit trail.

Typing the code in the form's ID box selects the product; the name and the
commission follow. `GET /trade_register/product-lookup/?code=…` does the same
for any caller, and with `&amount_fcy=&fx_rate=&issue_date=&expiry_date=` it
also returns the quote.

## 3. Editing wrong data, and disagreeing with the rate

Entries were already editable (`PATCH /trade_register/entries/<id>/`, and the
Administration Trade Finance page has its own edit). What was missing was what
happens to the commission when the rate is wrong or was negotiated.

`TradeRegisterEntry.commission_override` settles it. While it is set, the
calculation leaves the number alone, so re-saving a record never quietly undoes
a deliberate correction. Clear it and the product's price comes back. The form
shows the calculated figure and its reasoning beside the field either way, so an
override is a visible, deliberate act rather than a silent divergence.

## 4. Missing currencies

The form offered ten currencies compiled into the frontend bundle. That is why
currencies went missing: adding one meant a deploy.

`trade_register_currency` is seeded with 44 — the local unit, the majors, the
Gulf and Asian trade currencies, and the East African neighbours (`UGX`, `TZS`,
`RWF`, `BIF`, `SSP`, `ETB`, `SOS`, …). The form reads the table, so adding one
is now a row. A currency on an existing record that has since been deactivated
is still shown on that record.

## 5. Missing fields

**Still open — the desk has not said which fields.** The form currently carries:
originating branch, RM name and code, reference, product, amendment type and
parent reference, customer id, segment, customer, beneficiary, currency, amount
(FCY), FX rate, commission, reporting date, issue date, open-ended flag, expiry
date, security type, cash cover amount and percentage, other security, month and
year.

Adding a field is a model field, a migration, a serializer entry and a form
input; it is not blocked on anything except knowing which fields.

---

# Seller codes

`DSRSalesCodeListView` was list-only: a code allocated against the wrong person
was permanent. `dsr-sales-codes/<pk>/` now supports read, correct and withdraw
(writes admin-only), under the rule that has always governed these codes:

* a code another DSR holds is refused, and so is a PF that already has one;
* a withdrawn code is retired, never reissued — `next_sales_code()` is always
  `max + 1`, so deleting frees the person, not the number;
* every change is kept in the audit trail (`DSRSalesCode` gained history).

## The blank Team Leader column

A DSR's leader can be known three ways, and the column consulted only one of
them — the branch map — so every DSR whose leader is set by **role** (BANCA DSR
→ David Wambugu; SME DSR → Eva Kabiwa / Luke Njagi) read as unmapped although
the mapping existed and the allocator was already using it.

The order is now: the value stored on the allocation → the leader who owns the
DSR's branch → the leader(s) mapped to the DSR's role. `team_leader_source` says
which one answered, so a derived value is not mistaken for one somebody typed.
Where a role has more than one leader both names are shown — "one of these two"
is the honest answer, and a blank cell would read as "not mapped".

Separately, the branch map was keyed on the raw stored branch name while the
lookup used the canonical one, so a mapping stored as `THIKA` never answered for
a DSR whose branch read `Thika Branch`. Both sides are now canonicalised.

`team_leader_branches` has **no seed** — it is populated entirely by the CSV
upload on `/management/team-leaders`. The seller-codes page now counts and lists
the DSRs that resolve to no leader, so the gap is visible instead of looking like
a broken column.
