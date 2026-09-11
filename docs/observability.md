# Audit Trail & Data Health

Two Administration screens, one backend app (`apps/observability`).

* **Audit Trail** — `/management/audit-trail` → `GET /observability/audit/*`
* **Data Health & Monitoring** — `/management/data-health` → `GET /observability/data-health/`
  and `GET /observability/performance/*`

Both are administrator-only (`IsAdministrator`: `is_staff` or superuser). They
expose who changed what across the whole bank and the shape of the warehouse
behind it, so they are not open to ordinary users.

## The audit trail was already being written

`django-simple-history` is installed, `HistoryRequestMiddleware` is in the
middleware stack, and **35 models across 9 apps** carry `HistoricalRecords()`.
Every create, update and delete on those models has been recorded with the
acting user since long before anyone asked for an audit screen. Nothing read
it — the old "audit" view showed frontend page-view pings from
`user_activity_events`, which is traffic, not a trail.

`apps/observability/audit.py` reads the real tables:

* `auditable_models()` discovers every model with a history manager, so a model
  that gains `HistoricalRecords()` tomorrow appears with no further work.
* `feed()` takes each model's recent rows and merge-sorts them — one small
  indexed query per model rather than a union across thirty-five tables.
* `changed_fields()` diffs an update against its predecessor, so the feed says
  *`our_customer`: "C" → "Corrected Ltd"*, not merely "something was edited".
  A create has nothing to diff against and a delete's change is the deletion
  itself, so only `~` rows are diffed.

A row with no user was not made through a signed-in request — a management
command, an ETL, a migration. The page says "system / job" rather than leaving
the column blank, which reads as a bug.

Three admin tables gained history in the same change, because they are now
editable from the UI and the edits matter: `DSRSalesCode` (whose name a sale is
credited to), `TeamLeaderBranch`, `DSRRoleTeamLeader`, plus `TradeProduct` (what
the desk charges).

## Data health: is the data actually there?

The warehouse mirrors are `managed = False` — the ETLs fill them, the app only
reads them. When an ETL stops, nothing complains: the page renders zeros and the
only signal is a user asking why a chart is empty. That is exactly how the loan
trend charts stayed empty for weeks (`docs`/`loan-trends-empty-etl`).

`health.table_health()` walks the unmanaged models and reports, per table:

| Verdict | Meaning |
|---|---|
| `missing` | `to_regclass` says the table is not there at all |
| `empty` | the table exists and holds nothing — an ETL that has stopped |
| `stale` | last refreshed ≥ 7 days ago |
| `warning` | last refreshed ≥ 2 days ago |
| `ok` | refreshed within 2 days |
| `unknown` | present and populated, but its freshness cannot be judged — no date column, or `MAX()` on it timed out — never reported as healthy |

`error` means the table could not be read **at all**. It does not mean the
freshness probe failed: four production tables are large with no index on their
date column, so `MAX()` times out while the row count succeeds. Those are
present and populated, and calling them broken would have emailed the team about
four healthy tables every day forever. They report `unknown`, with the reason
attached.

**One row per physical table.** Four warehouse tables are mapped by two models
each — `hf_customer`, `accounts` and `accounts_history` (portfolio and
gceo_dashboard), and `employee_table` (gceo_dashboard and staff_management).
Where a table is mapped twice, the mapping with a usable date column wins. Without
this the dashboard listed each twice, counted 36 tables where there are 32, and
one stale table read as two problems.

Row counts come from PostgreSQL's `reltuples` planner statistic, **not**
`COUNT(*)`: thirty-six sequential counts over warehouse-sized tables would make
the dashboard slower than the problem it reports. The estimate is labelled as
one in the UI. A zero estimate is confirmed with a `LIMIT 1` probe, because
`reltuples` is `-1` on a table that has never been analysed — "empty" is
measured, never guessed.

### It hangs unless you stop it

The first version had no timeouts and **hung** — no exception, no traceback,
nothing in the log. The worker ran until gunicorn killed it and the proxy
reported a 500, which sent three rounds of debugging after an exception that
never existed.

The cause is `MAX(date_column)`. On a warehouse table of tens of millions of
rows with no index on that column, PostgreSQL reads the whole table. Doing that
for thirty-six tables is a batch job, not a page load.

So:

* every probe runs under `SET LOCAL statement_timeout = 2500`, enforced by
  PostgreSQL. **`SET LOCAL` only works inside a transaction** — outside one it
  is ignored with a warning, which would leave the cap silently absent, so the
  probe is wrapped in `transaction.atomic` (which also reverts the setting, so
  no stray timeout leaks onto a pooled connection);
* freshness is raw SQL on that same capped cursor. Through the ORM it would
  open its own connection with no cap, which is exactly how this hung;
* the scan as a whole has a 25-second budget, after which remaining tables are
  reported `skipped` — "not probed, the scan ran out of time" is a true
  statement, and better than a page that never loads;
* a probe that times out reports *"too slow to measure (no index on this
  column)"*, which names the fix;
* the result is cached for five minutes; `?refresh=1` (the Retry button)
  forces a fresh scan.

The endpoint also cannot return 500 at all: the scan, the summary and the JSON
serialisation run inside one guard, and anything that escapes comes back as
`200` with `scan_error` carrying the exception and its last frames. A screen
that reports failures must not fail opaquely.

Freshness picks the best date column by name (`updated_at`, `last_updated`,
`report_date`, `snapshot_date`, …) and reports which column answered.

## Performance and uptime

There is no Prometheus on the host and no metrics of any kind in the app, so
`middleware.RequestMetricsMiddleware` records one row per served request: the
normalised path (`/mortgages/leads/:id`), method, status, duration and username.

It buffers per worker process and flushes with a single `bulk_create` every 50
rows or 10 seconds. The obvious implementation — one INSERT per request —
doubles the database round-trips of the whole application, which has already
been through one round of "everything is slow" tuning.

`RequestMetric.username` is a plain column and **not** a foreign key. Rows are
flushed after the request, so the insert can land after the account it names is
gone; a constraint violation would throw away the whole batch.

Percentiles (`p50/p95/p99`) are computed by PostgreSQL with `percentile_cont`.
The point of a p95 is that it is taken over every request, not a sample fetched
into a web process.

### Uptime is measured, or it is not reported

Uptime comes from `AppHeartbeat` — one row per minute, written by a cron'd
management command. Uptime for a window is *minutes with a tick / minutes in the
window*.

**Request traffic is not a substitute.** A quiet night has no requests and no
downtime; inferring one from the other would report a made-up number. With no
heartbeats the API returns `measured: false` and the dashboard says uptime is
not being measured.

## Host cron entries

```cron
# Uptime heartbeat — without this, uptime is not measured.
* * * * * docker exec hf-backend python manage.py record_heartbeat

# Keep the metrics table bounded (30 days covers every window offered).
0 3 * * * docker exec hf-backend python manage.py prune_request_metrics

# Probe the other systems (Customer 360) from outside, every two minutes.
*/2 * * * * docker exec hf-backend python manage.py probe_services

# Decide whether anything changed enough to be worth an email.
# --sensitive-minutes MUST match this interval or edits are seen twice or missed.
*/10 * * * * docker exec hf-backend python manage.py run_alert_checks --sensitive-minutes 10

# One summary a day, including on the days when nothing broke.
0 7 * * * docker exec hf-backend python manage.py send_daily_digest
```

## Endpoints

| Endpoint | What |
|---|---|
| `audit/feed/` | merged change feed — `?days=&app=&model=&user=&action=+\|~\|-&search=&limit=&changes=0` |
| `audit/models/` | which models are audited and how much each changed |
| `audit/summary/` | totals, who is changing things, daily trend |
| `audit/record/` | one record's full timeline — `?app=&model=&id=` |
| `data-health/` | every warehouse table's existence, size, freshness |
| `performance/overview/` | latency percentiles, throughput, error rate, uptime |
| `performance/series/` | bucketed series for the graphs — `?hours=&buckets=` |
| `performance/endpoints/` | slowest endpoints by p95 + status-code spread |
| `performance/errors/` | recent failing requests |
| `performance/uptime/` | window uptime + per-day availability |
| `performance/active-users/` | who is on the system now |
| `services/` | the watched external systems - list, create |
| `services/status/` | reachability, average latency and last probe per service - `?hours=` |
| `services/<id>/` | edit or remove one |
| `services/<id>/token/` | POST issues a fresh ingest token, shown once |
| `alerts/recipients/` | who is emailed, and for which kinds |
| `alerts/state/` | what each watched condition currently is |
| `alerts/test/` | POST `{"kind": "..."}` - proves the mail path before an outage does |
| `ingest/` | where another system pushes its audit events and table health |

## Deploy

`manage.py migrate observability` creates the tables (0002 adds alerting
and the external feeds, 0003 registers Customer 360). The middleware is
fail-soft: a missing table or a dead connection drops metrics rather than
taking a request down, so the app is safe if the migration has not run yet.

---

# Alerting, and the systems that are not this one

Two screens that nobody has open are two screens that report nothing. Everything
below exists so that the first person to know is not a user.

## Customer 360

Customer 360 is a **separate resource server**. It trusts the JWT this backend
mints, but it is its own repo with its own database, on its own deployment. This
backend cannot read its tables and should not try — a direct database link
between two services is the coupling that makes both of them one service.

So it is watched two ways, and both are needed:

* **From outside (probe).** `probe_services` requests its health URL on a
  schedule and records the status code and how long it took. This is what
  catches the case that matters most — the service is gone — and it needs
  nothing from the Customer 360 repo, which is why it is the half that works
  today.
* **From inside (push).** Customer 360 posts its own audit events and table
  health to `observability/ingest/`. This is the half that cannot be seen from
  outside: who edited what over there, and whether its own feeds are loading.
  It needs a small change in that repo, so it is built and waiting rather than
  live.

Migration 0003 registers the service **with no health URL and no token** on
purpose. The URL is environment-specific and inventing one would probe nothing
and then report Customer 360 as down; the token is generated on demand so no
shared secret is committed. Until the URL is set the dashboard shows *not
probed*, which is honest, where green would be a lie.

### Turning the probe on

Administration → Data Health → Other Systems → edit Customer 360, set the health
URL (any cheap endpoint that returns 200 while the service is alive), save. The
next `probe_services` run fills in the row.

### Turning the push on

1. Administration → the service → **Issue ingest token**. It is displayed once.
2. Give it to the Customer 360 deployment as an environment variable.
3. That service POSTs, whenever it likes:

```http
POST /observability/ingest/
X-Observability-Token: <token>
Content-Type: application/json

{
  "events": [
    {"action": "~", "model_label": "c360.CustomerNote", "object_id": "812",
     "object_label": "Note on 0100123", "username": "jane.doe",
     "occurred_at": "2026-09-11T08:30:00Z", "external_id": "evt-88121",
     "changes": {"body": ["old", "new"]}}
  ],
  "tables": [
    {"table": "c360_customer_profile", "status": "ok", "row_count": 412331,
     "last_loaded": "2026-09-11T02:10:00Z"}
  ]
}
```

Both keys are optional; send either, or both. `action` is `+` created,
`~` updated, `-` deleted.

**It is idempotent.** Events carry an `external_id` and are deduplicated on
`(source, external_id)`; tables are upserted on `(source, table)`. A sender that
retries after a timeout, or replays a batch, does not double-count. A batch is
capped at 500 events and 500 tables so one client cannot post a day of history
in a single request.

Pushed rows then appear in the ordinary screens: events merge into the audit
feed carrying `source` and `external: true`, and table health appears alongside
the warehouse tables. A pushed table report that stops arriving goes to
`unknown` after three hours rather than staying green forever — silence from a
monitoring feed is not health.

## Alerts are sent on change, not on state

The whole design is one rule: **an alert fires when a condition changes, not
while it persists.** `alerts.transition(key, state)` records a key's state and
returns `True` only if it differs from what was recorded before. Every check
goes through it. A service that has been down for six hours produced one email,
not one every ten minutes, and the recovery produces exactly one more.

A key's first sighting is only news if it is *bad*. Otherwise adding a new
watched table would email everybody an all-clear about something they had not
been worrying about.

What is watched:

| Condition | Threshold | Why that threshold |
|---|---|---|
| Service down | 3 consecutive failed probes | One failed probe is a blip. Alerting on it is how alerts become noise people filter away. |
| Service slow | last probe over that service's `slow_ms` | Up but unusable is still an incident, and it is reported as *slow*, not *down*. |
| Error rate | over 5% **and** at least 50 requests in the hour | Two failures out of three requests at 3 a.m. is not a 66% outage. |
| Data health | any table `missing` / `empty` / `stale` / `error` | One key per table, so a second table breaking is its own email. |
| Sensitive change | any deletion anywhere, plus edits to the models below | See the next section. |

### What counts as a sensitive change

Emailing every edit would produce a mailbox nobody reads, and then the one that
mattered is in it. Only two things are mailed:

* **Any deletion, on any audited model.** Deletions are the changes that cannot
  be noticed later by looking at the data.
* **Edits to the models that decide money or access**: sales codes, trade
  tariffs and products, team-leader mappings, user profiles — and the alert
  recipients and monitored services themselves. Whoever can quietly remove a
  recipient can silence the alerting, so that removal is itself an alert.

Everything else is in the audit trail, which is where an ordinary edit belongs.

## Recipients

Administration keeps the list — `alerts/recipients/`, one row per address, with
a tick per kind: downtime, data health, sensitive changes, daily digest. Someone
subscribed to nothing is rejected at validation rather than saved as a row that
silently never receives anything.

Sending never raises. If SMTP is down the failure is logged and the check
returns 0 — a monitoring system that can crash the job it monitors from is worse
than no monitoring. Which is also why `alerts/test/` exists: find out that SMTP
is misconfigured now, not during the outage.

## The daily digest

Sent whether or not anything is wrong: requests served, median and p95, error
rate, uptime (or an explicit *not measured*), each external service's
reachability, warehouse tables needing attention, and the day's changes by user.
The "nothing is on fire" message is the one that proves the alerting still
works.
