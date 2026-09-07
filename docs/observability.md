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

`health.table_health()` walks all 36 unmanaged models and reports, per table:

| Verdict | Meaning |
|---|---|
| `missing` | `to_regclass` says the table is not there at all |
| `empty` | the table exists and holds nothing — an ETL that has stopped |
| `stale` | last refreshed ≥ 7 days ago |
| `warning` | last refreshed ≥ 2 days ago |
| `ok` | refreshed within 2 days |
| `unknown` | no date column to judge freshness by — never reported as healthy |

Row counts come from PostgreSQL's `reltuples` planner statistic, **not**
`COUNT(*)`: thirty-six sequential counts over warehouse-sized tables would make
the dashboard slower than the problem it reports. The estimate is labelled as
one in the UI. A zero estimate is confirmed with a `LIMIT 1` probe, because
`reltuples` is `-1` on a table that has never been analysed — "empty" is
measured, never guessed.

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

## Deploy

`manage.py migrate observability` creates the two tables. The middleware is
fail-soft: a missing table or a dead connection drops metrics rather than
taking a request down, so the app is safe if the migration has not run yet.
