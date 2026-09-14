# Service Desk

`apps/service_desk` + `/service-desk` on the frontend. Owned by **Strategy &
Business Performance**.

Built because staff were reporting that their queries were not being handled.
That is a complaint about accountability rather than volume, so the module is
shaped around three questions:

* **Where is my query?** One owner, one status, visible to the person who raised
  it without them having to ask anybody.
* **How long did each step take?** Every transition is timestamped and timed.
* **Who said it was handled?** The desk resolves; only the requester confirms.

## The rules that matter

### Time is working time

A query raised 16:55 Friday and answered 08:10 Monday took **fifteen minutes**
of anyone's working life and 63 hours on a wall clock. Report the wall clock and
every Monday morning reads as a breach, the team stops believing the figure, and
the figure stops being used.

So durations are measured on the desk's calendar — 08:00–17:00, Monday to
Friday, minus public holidays (`apps/service_desk/worktime.py`). Both clocks are
**stored** on every event, never derived: recomputing later would compute against
today's calendar rather than the one in force at the time.

Fixed-date Kenyan holidays for 2026–27 are seeded. **Eid and any gazetted day
are keyed in** from the desk settings — guessing a lunar date would put a wrong
day in version control and shift every SLA that crosses it.

### The desk does not get the last word

`resolved` is not `closed`. The handler marks it resolved with a note saying what
was done; the requester confirms or reopens. Auto-close after 3 working days of
silence is recorded as **not confirmed** — filing silence as satisfaction would
reproduce the exact failure being reported. A handler cannot confirm their own
work.

### Alerts and figures stay honest

* **Assignment is not a response**, and neither is an internal note. Otherwise
  the desk meets its SLA by moving things into a queue and talking to itself.
  Only a handler message the requester can see stops the response clock.
* **The resolution clock pauses** while waiting on the requester. The desk is not
  accountable for somebody else's silence.
* **The SLA is frozen onto the ticket** at creation. Repricing a category cannot
  retrospectively breach, or un-breach, tickets raised under the old promise.
* **Attainment is `null`, not 0%,** when nothing has been judged yet.
* **A breach escalates once.** One re-mailed every fifteen minutes is one
  everybody filters.

### No allocation step

The desk asked not to have a reassignment ceremony. A handler who replies to,
starts, or resolves an unowned ticket **owns it from that moment**. Acting on a
colleague's ticket does not take it from them. A manager can still hand one over
when somebody is away.

## Who can do what

Authorisation is Django group membership by name, as elsewhere in this codebase.

| | Requester | Handler (`service_desk_agent`) | Manager (`service_desk_manager`) |
|---|---|---|---|
| Raise, comment, cancel own | ✅ | ✅ | ✅ |
| Confirm / reopen own | ✅ | — | — |
| See the whole queue | — | ✅ | ✅ |
| Take, work, resolve | — | ✅ | ✅ |
| Internal notes | — | ✅ | ✅ |
| Assign to someone else | — | — | ✅ |
| Categories, SLAs, holidays, settings | — | — | ✅ |
| Reports | — | ✅ | ✅ |

**Superusers are managers**, and so is the existing `business_performance` role.
The Strategy team who run this desk are already platform superusers, so the desk
works for them on day one with no role assignment — and the queue emails reach
them, which it would not if handlers were defined by group alone.

Everyone else is a requester, including people with no group at all.

## Lifecycle

```
new ─▶ assigned ─▶ in_progress ─▶ resolved ─▶ closed
        (auto on   ▲        │                    ▲
         first      │        ▼                    │
         action)    └── on_hold (clock paused)    │
                                                  │
       cancelled ◀── (withdrawn)     reopened ────┘
```

Each transition writes a `TicketEvent` with `seconds_since_previous` and
`working_seconds_since_previous`. That is the record that answers "it has been
three weeks" with "it sat unassigned for nine working days, then was answered in
two hours".

## Endpoints

Base `service_desk/`. Every state change is its own endpoint — there is
deliberately **no PATCH that can set a status**, because each transition records
a step and tells somebody.

| Endpoint | What |
|---|---|
| `tickets/` | the queue (scoped to the caller), and POST to raise one |
| `tickets/<ref>/` | one ticket, with events, comments, permissions, timing |
| `tickets/<ref>/comment/` | reply; `is_internal` for a handler-only note |
| `tickets/<ref>/status/` | assigned / in_progress / on_hold only |
| `tickets/<ref>/assign/` | no username = take it; a username needs a manager |
| `tickets/<ref>/resolve/` | requires a note |
| `tickets/<ref>/confirm/` | requester only |
| `tickets/<ref>/reopen/` | within the reopen window |
| `tickets/<ref>/cancel/` | requester or manager |
| `categories/`, `holidays/`, `settings/` | read by anyone, written by a manager |
| `handlers/` | the assign dropdown, with each person's open count |
| `my-desk/` | the counts behind the tiles and badges |
| `reports/` | everything the dashboard draws — `?days=` |

Tickets are addressed by **reference** (`SD-9F3A1C2B`), because that is what
appears in the emails people paste back at you. A ticket the caller may not see
returns **404, not 403** — 403 confirms the reference exists, which is enough to
go fishing for other people's queries.

## Email

| Event | Who hears |
|---|---|
| Raised | requester (with the target) + the whole queue |
| Reply from the desk | requester |
| Reply from the requester | the owner, or the queue if nobody owns it |
| Assigned to you | that handler (not if they took it themselves) |
| Resolved | requester — confirm or reopen |
| Closed | requester, unless they closed it |
| Reopened | the owner, or the queue |
| Due soon | the owner, or the queue |
| Breached | managers only |

Nobody is copied on their own action. Mail is sent from
`transaction.on_commit`, so a resolution a later error rolled back cannot
announce itself; and every send is wrapped, because Office365 being slow must
never roll back a resolution the handler would then do twice.

## Host cron

```cron
# Auto-close, warn before a target passes, escalate a breach once.
*/15 * * * * docker exec hf-backend python manage.py service_desk_maintenance

# The weekly report to the desk managers, good week or bad.
0 8 * * 1 docker exec hf-backend python manage.py send_service_desk_report --days 7
```

Both are idempotent: running them twice, or after an outage against a backlog,
does not double-send. The "already warned" marker is a timeline event rather
than a flag column, so it is part of the ticket's history.

`--dry-run` on either shows what it would do without doing it.

## Deploy

`manage.py migrate service_desk` creates the tables and seeds the two groups,
six categories, the settings row and the holiday calendar — so the desk is
usable the moment it is deployed, with no data entry first.

## Tuning it

The seeded SLA targets are a **starting guess**, not a promise Strategy made.
They are editable per category from the API today (`categories/<id>/`), in
working minutes:

| Category | Reply | Resolve |
|---|---|---|
| System or dashboard problem | 1h | 9h (1 working day) |
| A figure looks wrong | 2h | 9h |
| Access or permissions | 2h | 9h |
| Report or data request | 4h | 18h (2 days) |
| Clarification or explanation | 4h | 18h |
| Scorecard query | 4h | 27h (3 days) |
| Targets and performance | 4h | 27h |
| Something else | 4h | 27h |

**The desk is not only about this application.** Most of what Strategy are asked
concerns the reports and scorecards they publish, and much of it is somebody
wanting a number explained rather than fixed. A category list that does not
describe the query somebody actually has sends them back to email, which is the
behaviour this desk replaces — so `clarification` and `scorecard` exist, and
`other` is described as "use this rather than not raising it at all".

Priority multiplies the target rather than replacing it: urgent ×0.25, high
×0.5, low ×2. One number to reason about instead of a matrix.
