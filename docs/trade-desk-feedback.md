# Trade desk feedback — what changed

Nine things the desk raised about the Trade Register / Trade Finance form.

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

## 5. The tariff book

`trade_register_tariff` is the bank's tariff book: a line carries
`commission_basis`, `commission_rate`, `minimum_commission` and `excise_rate`,
and products map to it. Repricing one line reprices every product on it, which
is the point of the mapping — the alternative is the same rate edited product
by product until the copies drift apart.

**A rate set on the product wins over its tariff.** A tariff is the general
charge for a family; a rate typed against one product is a deliberate exception.
If the mapping overruled it, somebody would set a rate, watch nothing happen and
have no way to see why. So the tariff answers only where the product does not —
which also means mapping a product to a tariff never reprices it.

Migration 0007 seeds three lines (`TRF-GTE`, `TRF-ILC`, `TRF-ELC`) and maps every
product to one. **They are seeded unpriced**, on the basis that calculates
nothing: seeding an invented rate would put wrong money on real transactions.
The structure is there; the desk supplies the numbers.

Each entry records the `tariff_code` it was charged under at save time, so a
record still says what it was charged under after the tariff is reprised.

Maintained at `GET/POST /trade_register/tariffs/`, `PATCH .../<id>/` (admin), and
in Django admin. Every change is in the audit trail.

## 6. Excise duty

`excise_duty` on each entry = `excise_rate` % of the commission, worked out on
save and shown as its own column beside `total_charge` (commission + duty).

It is computed from the commission **on the record** — including an overridden
one. The duty is owed on the fee actually charged, not on the fee the tariff
would have produced.

> **The rate needs confirming.** It defaults to 20%, Kenya's excise duty on fees
> charged by financial institutions, applied to the commission alone. Nobody has
> confirmed either the rate or the base for this desk. It is a field on the
> tariff line, so correcting it is one edit in Administration — not a deploy.

## 7. Customer id fills in the name and segment

`GET /trade_register/customer-lookup/?customer_id=` reads `hf_customer` and
returns the name (`latin_surname`) and segment. The desk was typing the id, then
typing the name and picking the segment again by hand — three chances to
disagree with the core system about one customer.

`hf_customer` has two segment columns that often disagree: `banking_segment` and
`segment`. The register has always carried the banking segment, so that is what
is filled in, and the other is **shown beside it** rather than silently
discarded, so the desk can correct it.

In the form the lookup is debounced and only ever fills blanks or replaces what
a previous lookup put there — typing an id never overwrites a name somebody
edited on purpose, and never rewrites an existing record.

## 8. Diary of expired items

`GET /trade_register/diary/?window=&include_live=1`, and a **Diary** tab on the
Trade Register page with a count of what has expired.

An expired guarantee is not a dead row — it is something somebody has to
release, renew or call up, and nothing surfaced them. The register is regrouped
by expiry into shelves: Expired, then within 7 / 30 / 90 days, then live,
open-ended, and **undated**.

Undated is its own shelf on purpose. An instrument that is neither open-ended
nor dated is a gap in the register; filing it under "live" would hide exactly
the records most likely to be wrong.

Thresholds live on the model (`TradeRegisterEntry.diary_status`), so the API,
the page and any report say the same thing about a record.

## 9. Missing fields

**Still open — the desk has not said which fields.** The form currently carries:
originating branch, RM name and code, reference, product and tariff, amendment
type and parent reference, customer id, segment, customer, beneficiary,
currency, amount (FCY), FX rate, commission, excise duty, reporting date, issue
date, open-ended flag, expiry date, security type, cash cover amount and
percentage, other security, month and year.

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
