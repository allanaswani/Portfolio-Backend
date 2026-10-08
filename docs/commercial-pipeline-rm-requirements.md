# Commercial Pipeline — the Commercial RM's additions, and the scoping fix

Source: `Additional System requirements.xlsx`, from the walkthrough with the
Commercial RM, plus the instruction that each RM should see only their own
lines.

Everything below is implemented. This file exists for the two things a reader
cannot get from the code: what the sheet actually said, and what has to happen
on the host before RMs see anything.

---

## 1. The scoping leak — read this first

**Every Commercial RM could see every other RM's deals.** Not through a missing
check, through the wrong one.

`apps/commercial_pipeline/views.py` had `portfolio_mgt` in `TEAM_GROUPS`, the
set of groups whose members are shown the whole segment instead of their own
book. `portfolio_mgt` reads like "portfolio management". It is not:

* `lib/roleNavConfig.tsx` maps `Permissions.PORTFOLIO_MGT` → `/rm-portfolio`,
  and the **"My Pipeline"** link lives in that nav block;
* `apps/staff_management/targets_views.py` names the same string `RM_GROUP`,
  with a comment explaining it is the RM Portfolio group.

So the one group guaranteed to be held by anybody who could reach the page was
the group that widened them to the whole segment. Customer names, amounts,
stages and comments for every RM in Commercial, on a page titled *My Commercial
Pipeline*.

The tests written at the time did not catch it because they built their RMs
with `user("rm_one", sales_code="CM001")` — no group at all.

`is_staff` was removed from the same check. `migrate_legacy_auth` copies that
flag verbatim out of the old system, so it records where an account came from,
not what it is entitled to read.

### Three doors, not one

| Door | Was | Now |
|---|---|---|
| `GET /commercial_book/entries/` and friends | whole segment for any `portfolio_mgt` member | own `sales_code` only |
| The RM page | relied entirely on the backend's role check | also sends `?scope=mine`, which overrides role |
| `get_commercial_pipeline` (AI assistant) | `PipelineEntry.objects.all()`, **no user at all** | the same `visible_to()` the API uses; refuses with no user |

The assistant one mattered as much as the page. It read every RM's customers,
amounts and stages for anybody who asked it, so closing the screen alone would
have left the chat box open.

`?scope=mine` is the second lock and is deliberately redundant: a page called
*My Pipeline* asks for one person's lines, so a group added to `TEAM_GROUPS`
in future cannot silently turn it into a team view.

### Writing, not just reading

An RM could also post a line carrying a colleague's `sales_code`, or PATCH
their own line onto somebody else. Both are now pinned to their own code; only
a team lead may name an owner, which is what the TL page is for.

---

## 2. What the sheet asked for

### The two renames

| Was | Now |
|---|---|
| Deposits | **Deposits Pipeline** |
| Liabilities | **Insurance Pipeline** |

The stored `kind` values (`deposit`, `liability`) did **not** change. Renaming
them would mean a data migration, a changed API contract and a changed workbook
sheet name, for a value nobody ever types or reads.

### VIC / non-VIC

New field `insurance_type` on the Insurance Pipeline, from the sheet verbatim:

* `VIC` — all Britam products
* `NON_VIC` — all other insurance covers

Required on a new line. **Blank on every row that predates it**, and on
anything the workbook importer loads from the old Liabilities sheet, which has
no such column. Those rows stay editable and the RM sets it when they next open
one — the alternative is a required field that makes existing rows unsaveable.

### Deposit types

`CASA` and `FD` keep their place; `CASH_MARGIN` and `ESCROW` join them from the
sheet's Deposits block. The column was `varchar(8)`, and `CASH_MARGIN` is
eleven characters, so it was widened to 16.

### The stages

The sheet lists each application stage against the unit responsible at that
point. Added as four broad stages with their units beneath:

| Broad stage | Units |
|---|---|
| RM Only | Relationship Manager (RM) |
| Credit Analysis | Credit Analyst · Credit Origination Manager |
| Credit Evaluation | PRE · CCM · DCR · BMD · MLC · Board |
| Approved *(existing, widened)* | Branch / RM · Valuation Adoption · Instructions to Lawyers · Joint Registration · Bank Attorneys Execution · PRE |
| Disbursement | Confirmation of Securities · Disbursement Officer · PRE · Insurance Confirmation · Trade Middle Officer · CPC |

**PRE appears at three points**, because the sheet lists it at three points.
It is one value, and the broad stage is what says which one is meant — the
reason both columns exist. A workbook cell reading only "PRE" is therefore
reported rather than placed: guessing would put the row in the wrong bucket of
the Team Leader's totals.

**The two "Remove-" rows.** `Charge dispatch to customer` and the broad stage
`Disbursed` are retired: not offered on the form, and refused on a new line or
a change. They are **not deleted** from the choices — a row already carrying
one still has to render as words rather than a slug, and still has to be
saveable. `RETIRED_STAGES` is that distinction. Migration 0002 moves live
`disbursed` rows onto `disbursement`, which is the same point under the name
the desk now uses.

`Discussion` and `Application` were left selectable. The sheet does not say to
remove them, and only names two removals. If they should go too, add them to
`RETIRED_BROAD_STAGES` — one line, and the existing rows keep working.

### The minimum comment

From the sheet:

> The system should enforce a minimum word requirement for comments at each
> workflow stage … to enable management and other users to understand the
> position clearly without requiring additional clarification.

`PipelineEntry.MIN_COMMENT_WORDS = 8` — **the sheet gives no number; eight is
one short sentence and it is one constant to change.** The form counts words
as you type, so the rule is visible before the save rather than only as an
error afterwards.

Checked on a new line, and on any save that **changes** the comment or moves
the stage. Not on a save that leaves both alone: every imported row would
otherwise be frozen until somebody wrote it a sentence, and an RM who cannot
correct an amount goes back to the spreadsheet.

The check is on the *change*, not on the field being present, because the form
posts every field it is holding — including the comment it loaded.

---

## 3. The next workbook

The tabs are likely to be renamed now that the app calls them something else,
so the importer accepts both. A renamed tab read as a missing one would drop a
whole pipeline out of the totals with nothing to show it had been there.

| Expected | Also accepted |
|---|---|
| Assets Pipeline | Assets, Asset Pipeline |
| Trade Pipeline | Trade |
| Deposits | Deposits Pipeline, Deposit Pipeline |
| Liabilities | Insurance Pipeline, Insurance, Liability |

It also reads a VIC column **by header, wherever it sits** — there is no
position to assume, since the old sheet has no such column. The header match
uses word boundaries: a plain substring test for "vic" also matches a column
headed *Service*.

---

## 4. On the host, after deploying

**No `migrate` was needed for the design-briefs change. This one does need
one.** Migration `commercial_pipeline.0002`:

* adds `insurance_type` to the table and its history table, through a guarded
  `adopt()` that checks `pg_attribute` first — the same idiom
  `staff_management.0022` uses, because `staff_management.0019` died on this
  host with *relation already exists*;
* widens `deposit_product` to `varchar(16)` (a catalogue change on Postgres 12,
  no table rewrite);
* moves `disbursed` rows to `disbursement`.

Eight of its ten operations are choices, which Postgres does not store at all.

### Then the part that is easy to miss

RMs were seeing everybody's rows, so nobody noticed whether their own rows were
matched to them. **Now that each RM sees only rows carrying their
`sales_code`, an RM whose imported rows still carry only a name will see an
empty pipeline.**

```bash
python manage.py match_pipeline_rms            # dry run, writes nothing
python manage.py match_pipeline_rms --apply
```

The dry run prints what it would assign, who is ambiguous, and which names have
no profile with a sales code. Rows it cannot match stay visible to the Team
Leader and to no individual RM — which is correct, and is now visible rather
than hidden behind "everybody sees everything".
