# Trade Register — catalogue, tariff, amendments and expiry

What changed from the trade desk's test feedback of 2026-09-08.

## 1. The action list

Six actions, and only six, offered for a new transaction:

```
Issuance · Amendment · Cancellation · Advising · Bill Acceptance · Settlement
```

`ISSUANCE` creates an instrument and draws a fresh reference. The other five act
on one that already exists, must name it, and reuse its reference with the
action as a suffix (`HFCB/GTE/260630/01 - AMENDMENT`).

Served from `GET /trade_register/actions/` rather than hard-coded in the
frontend, so the form, the tariff and the API cannot drift apart. The response
also says which actions need a parent reference, so the form can require it.

**Historical rows keep their own value.** The register holds transactions
recorded before this list existed, carrying `EXT`, `CALL UP`, `PAYMENT`,
`RELEASE ON INDEMNITY`, `REDUCTION`, `RETIREMENT`. A register is a record of
what happened; rewriting a settled transaction so an old row fits a new dropdown
would falsify it. Those values are still displayed and still selectable on the
row that holds them — they are simply not offered for anything new. The one
exception is a blank action, which unambiguously meant "not an amendment" and is
migrated to `ISSUANCE`.

The column was **renamed** from `amendment_type`, not dropped and re-added: the
generated migration would have destroyed every historical value.

## 2. Branch list

`BranchListView` unioned the known branch names, uppercased, with whatever
spellings the data held — so `THIKA` and `THIKA BRANCH` were two entries and the
desk saw its branches twice. Every name now goes through `normalize_branch`, the
canonicaliser the rest of the application already uses, so one branch appears
once however it was typed. `HQ` and `HEAD OFFICE` likewise collapse.

## 3. Product categories and the product list

Four categories, each holding the products the desk supplied:

| Category | Products |
|---|---|
| `LETTERS OF GUARANTEE` | 11, each with the bank's own code (14116 = BID BOND GUARANTEE) |
| `LETTERS OF CREDIT` | 7 |
| `BILLS UNDER LETTER OF CREDIT` | 4 |
| `BILLS UNDER DOCUMENTARY COLLECTION` | 5 |

The desk supplied codes only for the guarantees. The other sixteen carry
placeholder codes prefixed `TR-` so it is obvious they are not bank product
codes — an invented code would be indexed, reported on, and eventually believed.
**Send the real codes and they are a one-line edit each.**

Choosing a category narrows the product dropdown:
`GET /trade_register/products/?category=<id or code>`.

Products the new list supersedes were **re-coded, not replaced**, so the
transactions already recorded against them follow onto the new list. Anything
the new list drops is marked inactive — it disappears from the dropdown while
its history stays readable. Nothing is deleted.

## 4. The tariff

`trade_register_tariff` holds the bank's published tariff, transcribed from the
tariff book. A charge is selected by **(product category, action)**, because that
is how the book is organised — "LC Issuance Charges", "LC Amendment Charges",
"Cancellation Commission" and "LC Advising Charges" are separate lines. A line
may also name a single product, which is how a product-specific price is
expressed.

Resolution, most specific first: product + action → product, any action →
category + action → category, any action. A rate typed directly on a **product**
still beats all of it — that is a deliberate override, and a book that silently
overruled it would leave somebody setting a rate, watching nothing happen, and
unable to see why.

Seeded from the book:

| Line | Charge |
|---|---|
| Guarantee issue/renewal | 0.75% per quarter; min 2,500 |
| **Bid bond issue** | **1% flat** (the desk's stated exception) |
| Guarantee general amendment | 2,000 flat |
| Guarantee cancellation | 500 flat |
| Guarantee claims processing | 3,500 flat |
| LC issuance | 0.75% per quarter; min 2,500 |
| LC acceptance | 0.75% per quarter; min 2,500 |
| LC payment | 0.3%; min 2,500 |
| LC amendment — general | 2,500 flat |
| LC amendment — extension/amount | 0.75% per quarter; min 2,500 |
| Release against indemnity | 0.1%; min 2,500 |
| Discrepancy | **US$** 100 |
| LC advising | 2,500 (3,500 for a non-customer — see the line's note) |
| LC confirmation | 0.5% per quarter; min 5,000 |
| Documents negotiation/processing | 0.5% flat; min 3,000 |
| Documents discounting | 0.25% per quarter; min 3,000 |
| Collections advising | 2,500 flat |
| Collections acceptance | 0.3% per quarter; min 2,500 |
| Availisation | 0.75% per quarter; min 2,500 |
| Collections payment | 0.3% flat; min 2,500 |
| Holding | 2,500 per month |
| Noting and protesting | as charged by the Notary Public — not calculated |
| Documents handling (outward) | 0.5%; min 3,000 |

**Both halves are amendable** — `commission_rate` for a percentage and
`fixed_amount` for a flat fee, plus `minimum_commission` and `excise_rate` —
through `PATCH /trade_register/tariffs/<id>/` (admin only). Every change is in
the audit trail.

Charges quoted in dollars carry `charge_currency`, so US$100 is not silently
read as shillings. Charges the book states in words carry `manual_note` and
calculate nothing, so the line exists and says why rather than being left out.
A line can hold both a note and a number — LC advising is 2,500 with a note
about non-customers — and the number still applies.

## 5. Amendments to an issued instrument

An amendment is **its own row**, linked to the instrument it amends. The
original is never touched, so the register keeps saying what was actually
issued.

* `amount_delta` — the increase (+) or reduction (−) this amendment applies.
* `new_expiry_date` — where it moves the expiry.
* `parent` — resolved from the typed reference. Amending an amendment resolves
  to the **original**, so a chain never forms that nothing can total.

The instrument's live position is computed:

* `current_amount` = issued amount + every amendment's delta.
* `effective_expiry_date` = the latest expiry any amendment moved it to.

`effective_expiry_date` is what the diary and the expiry job read. Reading the
original's date would show an extended guarantee as expired and send the desk
chasing an instrument that is still perfectly live.

The register shows the live amount with the issued figure beneath it whenever
they differ, because both are wanted.

## 6. Expiry filing

```cron
0 1 * * * docker exec hf-backend python manage.py archive_expired_trade_items
```

Sets `is_archived` on instruments whose **effective** expiry has passed. The
active register and the diary exclude them; the Expired tab is exactly them.

**Nothing is deleted** — an expired guarantee is still a record of what the bank
issued, and is still needed for reporting and audit.

The job also **un-archives**: an amendment that extends an archived instrument
puts it straight back on the active register. A job that could only archive
would bury a revived instrument where nobody looks.

`--grace-days N` keeps an instrument on the desk for N days past expiry;
`--dry-run` reports without changing anything.

## 7. Trade Finance in the Trade Register

A **Trade Finance** tab on `/trade-register`: the same register with the
commission columns to the front. **Send Report and Upload are deliberately
disabled** — they belong to Administration → Trade Finance — and are shown
greyed rather than hidden so the desk can see they exist and have not gone
missing.

## 8. Date ranges and export

`?date_from=&date_to=&date_field=` on `entries/`, where `date_field` is
`issue_date` (default), `reporting_date`, `expiry_date` or `created_at` — a
report of what was *captured* in a period wants a different date from one of
what *expires* in it.

The same filters go to the export, so what downloads is exactly the period on
screen. Also filterable by `category`, `product`, `branch`, `action` and
`archived`.

## Deploy

```bash
docker exec hf-backend python manage.py migrate trade_register
( crontab -l 2>/dev/null; \
  echo "0 1 * * * docker exec hf-backend python manage.py archive_expired_trade_items" ) | crontab -
```
