# Moving PostgreSQL to converter-helper — the runbook

**Every command is labelled `[OLD]` or `[NEW]`. Check the shell prompt before
you paste: `datawarehouseworker-node1` is OLD, `converter-helper` is NEW.**

| | OLD | NEW |
|---|---|---|
| Address | 128.2.1.25 | 10.51.181.25 |
| Hostname | `datawarehouseworker-node1` | `converter-helper` |
| PostgreSQL | 12.1 | 12.1 |
| Data directory | `/data/db_data/pgsql/12/data/data` | identical path |
| Cluster on disk | 442 GB | 384 GB (to be discarded) |
| `/data` free | 107 GB | 63 GB |
| Volume group free | **0** | **0** |

Measured 24 Sep 2026, and the size is stale: **the cluster is 463 GB**, see
the corrections below. Everything moves: all five databases
(**now 463 GB — see the findings section immediately below**).

---

## What changed since this was written — read this first (6 Oct 2026)

Nine findings from a day of work on the live hosts. Four of them correct
something above, and two change the plan. The applied ones are marked **DONE**
and need no repeating.

### Corrections to the table above

* **The cluster is 463 GB, not 441 GB** — `datawarehouse` 463 GB,
  `virtual_accounts_activation` 1644 MB, `metabase` 72 MB, `postgres` 16 MB,
  `airflow_db` 12 MB. At 2–3 GB/day of growth and **108 GB free on the new
  host**, that is **36–49 days of headroom**, with **zero free extents in the
  volume group** so there is no LVM extend to fall back on. `accounts_history`
  alone is 257 GB of the 463: a retention policy there is the cheapest 100+ GB
  available and is independent of this migration.
* **Database sizes are byte-identical on both hosts.** That is the cleanest
  confirmation of the copy there is — better than any row count.
* **`psql -U postgres` as root always fails here** with *"Peer authentication
  failed"*: the unix socket maps the OS user to the DB user. Every command in
  this runbook must be `sudo -u postgres psql`, run from `/` (otherwise a
  cosmetic *"could not change directory"* warning appears).

### DONE 6 Oct — `max_connections` 100 → 300, both hosts

The stock 100 ran out under live traffic and threw **500s to real users** on
`/ceo/employees` from `https://ceo.hfcb.co.ke/`. The holders were attributed
with:

```bash
ss -tnp state established '( dport = :5432 )' | grep -o '"[^"]*",pid=[0-9]*' | sort | uniq -c | sort -rn
```

**8 gunicorn workers holding 2–5 connections each, plus `java` (Metabase) 3.**
Not a leak: Django closes a persistent connection at the *end of a request on
that thread*, so an idle thread sits on its connection for the life of the
worker — 9 workers × 4 threads is up to 36 slots held open by design. The tell
is `longest_idle ≈ oldest`, clustered one group per worker pid.

Raised to 300 on **the standby first** — a standby refuses to start when the
parameter is below the primary's. Relief with no restart and no session, for
when it is refusing even `postgres`:

```bash
ps -eo pid,etimes,args --sort=-etimes | awk '/postgres: / && / idle$/ {print $1}' | head -40 | xargs -r kill -TERM
```

`kill -TERM` is what `pg_terminate_backend()` does internally. **Never `kill -9`
a backend** — the postmaster reads an abnormal exit as possible shared-memory
corruption and restarts the whole cluster.

Note on reading `ps` here: PostgreSQL 12's process title is
`postgres: <user> <database> <host> <state>` — **user first**. So
`postgres: datawarehouse metabase 127.0.0.1 idle` is the `datawarehouse` role
connected to the `metabase` database, not a `metabase` user. There is no
`metabase` role.

### DONE 6 Oct — `wal_log_hints = on`, both hosts. This is the big one.

**The promote in Phase 3 was one-way and this runbook did not say so.**
`wal_log_hints` was `off` and `Data page checksum version` was `0`, and
`pg_rewind` requires one or the other. Without it the old host can never be
re-synced as a standby of the new one without re-copying 463 GB — and the old
host has ~107 GB free, so it physically cannot. The migration would have ended
with **the production database running with no replica at all.**

Now `on` on both hosts (one restart each). **It must stay on.** Verify before
the window:

```bash
sudo -u postgres psql -Atc "show wal_log_hints"
```

Cost: somewhat more WAL volume, since hint-bit updates are now logged.

### The two hosts are in DIFFERENT TIMEZONES — unresolved

`systemctl status` on the old host reports **`+0545`** (Asia/Kathmandu); the new
host reports **`EAT`** (+0300). **Cron schedules against host local time**, so
the ~100 ETL jobs on the old host are running on a +0545 clock, and anything
rescheduled on the new host shifts by **2h45m**. This also explains the gap
between the old host's container access logs (`+0300`) and its own `date`.

Settle it before the window, on both hosts:

```bash
hostname; date; date -u; timedatectl status
systemctl is-active chronyd ntpd; chronyc tracking 2>/dev/null; ntpq -p 2>/dev/null
docker exec hf-backend date; date
```

`timedatectl` gives Time zone and **NTP synchronized** in one line. Django is
insulated from the container's timezone (`USE_TZ = True`,
`TIME_ZONE = "Africa/Nairobi"`, so it converts from UTC explicitly), but **cron
is not**, and neither are PostgreSQL's own log timestamps.

### `metabase` and `airflow_db` are read-WRITE tenants of this cluster

They are not read-only consumers of the warehouse — they live **inside** the
cluster being moved (72 MB and 12 MB), and both write constantly: Metabase its
sessions, saved questions and query logs, airflow every task instance and DAG
run.

Two consequences, and they close off the two obvious shortcuts:

1. **They cannot be pointed at the standby before the promote.** Their writes
   fail with *"cannot execute INSERT in a read-only transaction"*.
2. **The hosts cannot run in parallel.** After a promote, `metabase` and
   `airflow_db` would exist in two writable copies and each client's state
   would land wherever it happened to be routed — saved questions appearing and
   disappearing, airflow potentially running a DAG twice from two schedulers.
   Making the old host a standby of the new one does not help: a standby is
   read-only. True parallel writes would need multi-master (pglogical/BDR) and a
   conflict policy, which PostgreSQL 12 core does not have.

So one database has to be the one everybody writes to. That is what the
forwarder below is for — it is not a convenience, it is what prevents the split.

### The ETLs have no passwords — the forwarder needs `trust`, not `md5`

`select rolname, rolpassword is not null from pg_authid` shows `datawarehouse`,
`airflow_user` and `DWH` **do** have passwords, but `postgres` does not — and a
search of `/data/apps/datascience/` for `password`/`PGPASSWORD` found **nothing**.
Every client reaches PostgreSQL over `127.0.0.1` with `trust`, so an empty
password field has always worked and nobody would know.

**An `md5` entry would break all ~100 ETL jobs at once**, and it would look like
the migration broke the ETLs rather than the auth method.

### DONE 6 Oct — the new host had no `pg_hba` entry for the old host

Nothing on `128.2.1.25` could reach `10.51.181.25:5432` at all. The existing
`128.1.1.52/24` line looks close enough to be mistaken for it, but `128.1.1.x`
and `128.2.1.x` are different networks. Added and reloaded:

```bash
# [NEW]
cp /data/db_data/pgsql/12/data/data/pg_hba.conf /root/pg_hba.conf.before-forwarder
echo "host    all    all    128.2.1.25/32    trust" >> /data/db_data/pgsql/12/data/data/pg_hba.conf
sudo -u postgres psql -c "select pg_reload_conf()"
```

`listen_addresses` is already `*` and `5432/tcp` is already open in firewalld on
the new host, so that line was the only thing in the way.

Separately, and not part of this migration: that file `trust`s five whole `/24`
subnets, meaning anyone on any of them can connect as **any** role including
`postgres` with no password. That needs a ticket of its own.

### DONE 6 Oct — the forwarder, rehearsed and proven

**The idea:** after the promote, run a TCP forwarder on the old host's 5432
pointing at the new host. Every ETL, Metabase and airflow job keeps connecting
to `128.2.1.25:5432` with the config it has today and lands on the new database
without knowing. Nothing on the old host is edited, and **Metabase is never
restarted** — which matters, because that `java` process has no systemd unit and
`PPID 1`, nobody owns it, and nobody knows what starts it.

`systemd-socket-proxyd` ships with systemd, so this needs no package install on
a production database host.

**Rehearse it on 5433, bound to loopback, before the window.** Nothing uses
5433, so production cannot be affected, and it can be left running for days with
one low-stakes ETL pointed at it:

```bash
# [OLD]
cat > /etc/systemd/system/pgproxy-rehearsal.socket <<'EOF'
[Unit]
Description=Rehearsal: local 5433 to the new host's PostgreSQL

[Socket]
ListenStream=127.0.0.1:5433

[Install]
WantedBy=sockets.target
EOF

cat > /etc/systemd/system/pgproxy-rehearsal.service <<'EOF'
[Unit]
Description=Rehearsal: forward to 10.51.181.25:5432
Requires=pgproxy-rehearsal.socket
After=pgproxy-rehearsal.socket

[Service]
ExecStart=/usr/lib/systemd/systemd-socket-proxyd 10.51.181.25:5432
PrivateTmp=yes
EOF

systemctl daemon-reload
systemctl start pgproxy-rehearsal.socket
cd / && sudo -u postgres psql -h 127.0.0.1 -p 5433 -d datawarehouse -Atc "select current_setting('data_directory'), pg_is_in_recovery(), inet_server_addr()"
```

Expected, and what it returned on 6 Oct:
`/data/db_data/pgsql/12/data/data|t|10.51.181.25`

The **`t`** is the proof: a server *in recovery*, which the old host is not. That
one line confirms routing, firewalld, the new `pg_hba` entry and passwordless
`trust` end to end. Deliberately not `enable`d — a rehearsal must not survive a
reboot.

**OPEN — the proxy's connection ceiling.** This systemd's
`systemd-socket-proxyd` has no `--connections-max` flag (only `-h` and
`--version`), so the limit is the compiled-in **256**. That is below the 300
slots now configured, and it cannot be tuned. Before the window, measure the
real peak on the old host and decide whether to accept 256 or use `haproxy`
for the production forwarder:

```bash
sudo -u postgres psql -Atc "select count(*) from pg_stat_activity where backend_type='client backend'"
```

### What the rollback actually is

Phase 3 says the promote is the point of no return. With the forwarder it is
softer than that, and `pg_rewind` is not needed for the rollback itself:

* The old PostgreSQL **must** stop at cutover, because the forwarder needs port
  5432 — and that is the point, not a side effect. It is what stops `metabase`
  and `airflow_db` existing in two writable copies.
* The old cluster is then **frozen and byte-intact**. Rollback is: stop the
  forwarder, start the old PostgreSQL, revert the env files. You lose only what
  was written after the promote.
* `wal_log_hints` buys the *other* direction: re-synchronising the old host as a
  standby of the new one with `pg_rewind` in minutes rather than a 463 GB copy,
  so you have a replica again and a failback that takes seconds.

**Delete nothing on the old host for at least two weeks** still stands.

---

## The method, and why not the obvious one

The obvious approach is `pg_dump` into `pg_restore`. We measured it: 11 MB/s,
which is roughly eleven hours of transfer for the warehouse before index
rebuilds, and it cannot be resumed if it breaks at hour nine.

**Use streaming replication instead.** `pg_basebackup` copies the whole cluster
over the PostgreSQL protocol while production stays fully up, then the new host
follows the old one as a standby and stays current by itself. Cutover becomes a
*promotion* — stop the writers, let replay finish, promote. The outage is
minutes, not a day, and if anything goes wrong before the promote you have
changed nothing on the old host.

It also solves a problem SSH does not: the data directory is `postgres`-owned
and `0700`, so `rsync` as `admlin01` cannot read it, and root login is refused
from the old host. `pg_basebackup` connects on 5432 and sidesteps that entirely.

---

## Phase 0 — Prerequisites (read-only, do today)

**[OLD]** Replication must be possible at all:

```bash
psql -h 127.0.0.1 -U postgres -c "SHOW wal_level;" -c "SHOW max_wal_senders;" -c "SHOW hba_file;"
```

`wal_level` must be `replica` or `logical`, and `max_wal_senders` at least 3.
Both are PostgreSQL 12 defaults. If `wal_level` is `minimal`, it needs a change
and a **restart** of the old server — that is an outage in itself, so find out
now rather than on the night.

**[OLD]** Disk for WAL retention during the copy. A 463 GB base backup takes
hours, and the old host must keep every WAL segment generated in that time:

```bash
df -Ph /data; du -sh /data/db_data/pgsql/12/data/data/pg_wal
```

107 GB free is comfortable for this, but the slot in Phase 2 is what guarantees
nothing is discarded.

---

## Phase 1 — Reclaim space on the new host

Nothing here touches the old host. Order matters: the dumps first, so there is
headroom before the larger deletion.

**[NEW]** The 2021 dumps — 126 GB, dated 27 Oct 2021:

```bash
ls -lht /data/dumps
```

Confirm with the data team that nothing treats these as the DR copy of record,
then:

```bash
rm -f /data/dumps/datawarehouse_db_backup.bak /data/dumps/datawarehouse_db_backup.bak.zip
```

**[NEW]** Stop the local PostgreSQL and discard its data directory. This
destroys the 382 GB copy and the local `metabase`, `airflow_db` and
`virtual_accounts_activation` — all of which arrive again from the old host:

```bash
systemctl stop postgresql-12
```
```bash
mv /data/db_data/pgsql/12/data/data /data/db_data/pgsql/12/data/data.old
```

`mv` rather than `rm` makes the deletion instant and reversible for a moment.
But it must be deleted **before** the base backup starts, not during it:
clearing only the dumps leaves 189 GB free, and the backup needs 463 GB, so it
would fill the disk partway through.

```bash
rm -rf /data/db_data/pgsql/12/data/data.old
```

Nothing is lost by deleting it early. The old host is untouched and serving
production throughout, so a failed backup just means starting again.

**[NEW]** Confirm the arithmetic before going further:

```bash
df -Ph /data
```

Expect roughly 573 GB free — 189 GB after the dumps, plus 384 GB from the data
directory. The base backup needs **463 GB**, not the 441 GB quoted when this
was written, so the margin is ~110 GB rather than ~130 GB. **Below 540 GB free,
stop and find more space rather than proceeding** - the copy also has to hold
the WAL that accumulates while it runs, and the cluster grows 2-3 GB/day, so a
figure measured weeks before the window is already low.

---

## Phase 2 — Copy the cluster, with production still running

**[OLD]** Create a replication slot. This is what stops the old host from
discarding WAL the new host has not received yet:

```bash
psql -h 127.0.0.1 -U postgres -c "SELECT pg_create_physical_replication_slot('converter_helper');"
```

**[OLD]** Allow replication from the new host. Use the file `SHOW hba_file`
reported in Phase 0 — **not** the one under `/var/lib/pgsql`, which is a stale
package default that nothing reads:

```bash
HBA=$(psql -h 127.0.0.1 -U postgres -Atc "SHOW hba_file;"); mkdir -p /root/pgconf-backups; cp "$HBA" /root/pgconf-backups/pg_hba.conf.bak-$(date +%F); echo "host replication datawarehouse 10.51.181.25/32 md5" >> "$HBA"; psql -h 127.0.0.1 -U postgres -c "SELECT pg_reload_conf();"
```

A reload, not a restart — no outage.

**[OLD] Clear any file the `postgres` OS user cannot read — do this BEFORE
starting the copy.** `pg_basebackup` sweeps the whole data directory at the very
end, so a single unreadable file fails the run at 99% and the 463 GB starts
again. It cannot resume.

```bash
find /data/db_data/pgsql/12/data/data ! -user postgres -ls
```

This bit us on 24 Sep: a pre-existing `postgresql.conf.bak`, plus the
`pg_hba.conf.bak-*` this runbook told you to make in the step above. Config
backups do not belong inside the data directory:

```bash
mkdir -p /root/pgconf-backups && mv /data/db_data/pgsql/12/data/data/*.bak /data/db_data/pgsql/12/data/data/*.bak-* /root/pgconf-backups/ 2>/dev/null
```

Re-run the `find` and only continue when it returns nothing.

**[NEW]** Take the base backup. Run it under `tmux` or `screen`: it will run for
hours and a dropped SSH session would kill it.

```bash
sudo -u postgres pg_basebackup -h 128.2.1.25 -U postgres -D /data/db_data/pgsql/12/data/data -S converter_helper -X stream -c fast -P -R
```

- `-S converter_helper` uses the slot, so no WAL is lost.
- `-X stream` fetches WAL alongside the data, so the backup is consistent.
- `-R` writes `standby.signal` and `primary_conninfo`, making this a standby.
- `-P` prints progress, which is also your throughput measurement.

### While the backup runs, watch the slot — daily, without fail

The slot is what guarantees no WAL is lost. It is also the one way this process
can damage the **old** host: while the slot exists and nothing is consuming it,
WAL accumulates there and is never recycled.

**[OLD]**

```bash
psql -h 127.0.0.1 -U postgres -c "SELECT slot_name, active, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained FROM pg_replication_slots;" ; df -Ph /data
```

- `active = t` — healthy, something is consuming it.
- `active = f` with `retained` growing — **the backup died and nobody noticed.**
  Either start the standby immediately, or drop the slot.

This happened on 25-27 Sep 2026: the backup finished on the Friday evening, the
standby was not started, and by Sunday the slot held 43 GB and the old host had
gone from 107 GB free to 77 GB - roughly 15 GB a day, about five days from
filling the disk and taking the warehouse down. Starting the standby drains it.

If the backup has failed and will not be restarted the same day, drop the slot
rather than leave it:

```bash
psql -h 127.0.0.1 -U postgres -c "SELECT pg_drop_replication_slot('converter_helper');"
```

A dropped slot costs a fresh base backup. A full disk costs production.

**[NEW]** When it finishes, start it. It will connect to the old host and catch
up on everything written during the copy:

```bash
systemctl start postgresql-12
```
```bash
psql -h 127.0.0.1 -U postgres -Atc "SELECT pg_is_in_recovery();"
```

`t` means it is a standby and following. **[OLD]** Watch it catch up:

```bash
psql -h 127.0.0.1 -U postgres -x -c "SELECT client_addr, state, sent_lsn, replay_lsn, replay_lag FROM pg_stat_replication;"
```

Wait until `state` is `streaming` and `replay_lag` is under a second. From this
point the new host stays current on its own, and you can cut over whenever you
like. **There is no time pressure after this step** — that is the whole reason
for choosing this method.

---

## Phase 3 — Cutover

Do this in a quiet window. Everything before it was reversible by deleting the
standby; from here the old host stops serving.

> **Read the 6 Oct findings section first.** Three things changed here: the
> promote needed `wal_log_hints = on` to be reversible at all (now done); the
> forwarder below takes the place of repointing the ETLs, Metabase and airflow
> on the night; and `metabase`/`airflow_db` being read-write tenants of this
> cluster is why the old PostgreSQL *must* stop rather than run alongside.

**[OLD]** Stop every writer. All 76 connections, not just the app:

```bash
crontab -l > ~/crontab-before-cutover-$(date +%F).txt
```
```bash
crontab -r
```
```bash
docker stop hf-backend portfolio-frontend c360-backend c360-frontend
```

Metabase and airflow hold connections too and are not in cron — stop them by
whatever manages them, and confirm nothing is left:

```bash
psql -h 127.0.0.1 -U postgres -c "SELECT COALESCE(host(client_addr)::text,'local') AS client, datname, usename, count(*) FROM pg_stat_activity WHERE backend_type='client backend' GROUP BY 1,2,3;"
```

**[NEW]** Also stop the app tier here, so nothing writes mid-promotion:

```bash
docker stop hf-backend portfolio-frontend c360-backend c360-frontend
```

**[OLD]** Now stop PostgreSQL. This is the moment the bank's warehouse goes
offline:

```bash
systemctl stop postgresql-12
```

**[OLD]** Record where the primary stopped. This is the number the whole
migration is verified against:

```bash
sudo -u postgres /usr/pgsql-12/bin/pg_controldata /data/db_data/pgsql/12/data/data | grep -E "Latest checkpoint location|Latest checkpoint.s REDO location"
```

**[NEW]** Replay must have reached that point before you promote. With physical
replication the standby is byte-identical by construction, so this comparison -
not row counting - is what proves the move:

```bash
psql -h 127.0.0.1 -U postgres -Atc "SELECT pg_last_wal_replay_lsn();"
```

If the standby's LSN is behind the primary's shutdown location, **wait**. It is
still applying. Promoting early silently loses whatever had not been replayed,
and nothing afterwards will tell you that it happened.
```bash
sudo -u postgres pg_ctl promote -D /data/db_data/pgsql/12/data/data
```
```bash
psql -h 127.0.0.1 -U postgres -Atc "SELECT pg_is_in_recovery();"
```

`f` means it is now a primary and accepting writes.

---

## Phase 4 — Verify before letting anyone in

**Take the baseline BEFORE Phase 3 stops the primary.** There is nothing to
compare against afterwards - the old server is off, and starting it again to
take counts risks it accepting a write.

**[OLD]**, as the last thing before stopping it:

```bash
sh docs/db-verify.sh > ~/verify-old-before-cutover.txt
```

**[NEW]**, after the promote:

```bash
sh docs/db-verify.sh > ~/verify-new-after-promote.txt
```

Then compare. Pull the old file across and diff:

```bash
scp admlin01@128.2.1.25:~/verify-old-before-cutover.txt . && diff verify-old-before-cutover.txt ~/verify-new-after-promote.txt
```

### Dry-run it first — before the window (added 2026-10-05)

Run the [NEW] snapshot and the diff **while the primary is still live**. It
costs nothing, proves the comparison works, and tells you what the real diff
should look like. On 2026-10-05 that dry run produced the `role` line plus nine
row counts, **every one of them HIGHER on the standby**:
`observability_heartbeat` +9, `observability_request_metric` +326,
`user_activity_events` +11, `token_blacklist_*` +3, `weighted_sales_branch_trade_data_dump` +6,
two feedback tables +1.

That pattern is the **healthy** one and must be read correctly:

- Every differing table is **append-only and continuously written** — heartbeats,
  request metrics, JWT tokens, activity events, an ETL dump. The baseline was a
  point-in-time snapshot of a *live* primary; the standby then kept replaying.
  The differences are the clock moving, not data diverging.
- **Not one table was LOWER on the standby.** That is the thing to check. A
  standby behind on even one count means replay is lagging or lossy. All-higher
  means it is faithfully following.

**At the real cutover the primary is already STOPPED when you snapshot the
standby, so the counts must match EXACTLY.** The acceptance criterion is
therefore stricter than the dry run: *only* the `role` line may differ. Any row
count difference at that point — in either direction — means stop and
investigate, do not let anyone in.

Two differences are expected and fine: the `role` line (`primary` vs
`standby`), and any line marked ESTIMATE, since those are planner statistics
rather than counts. **Everything else must be identical** - database sizes,
roles, table/index/sequence/view/function counts, and every exact row count.

The quick spot-check, if you want one before the full diff:

```bash
psql -h 127.0.0.1 -U postgres -c "SELECT datname, pg_size_pretty(pg_database_size(datname)) FROM pg_database WHERE NOT datistemplate ORDER BY pg_database_size(datname) DESC;"
```

Expect `datawarehouse` at **463 GB** (it was 439 GB when this was written on 27 Sep 2026 and grows ~2-3 GB/day — re-read your own baseline file rather than trusting this figure), `virtual_accounts_activation` 1644 MB,
`metabase` 72 MB, `airflow_db` 12 MB.

```bash
psql -h 127.0.0.1 -U postgres -d datawarehouse -c "SELECT (SELECT count(*) FROM daily_balance_movement) AS dbm, (SELECT count(*) FROM hf_customer) AS customers, (SELECT count(*) FROM accounts) AS accounts, (SELECT count(*) FROM auth_user) AS users;"
```

`daily_balance_movement` was 297,297 rows on 24 Sep. Every count must match the
old host's, which is why you record them **before** Phase 3.

---

## Phase 5 — Repoint everything

**[NEW]** The app first, since you control it:

```bash
sed -i 's/^DW_HOST=128.2.1.25/DW_HOST=127.0.0.1/; s/^DB_HOST=128.2.1.25/DB_HOST=127.0.0.1/' /etc/hf/prod.env
```
```bash
sed -i 's/^PG_HOST=128.2.1.25/PG_HOST=127.0.0.1/' /etc/hf/c360.env
```
```bash
docker rm -f hf-backend c360-backend
```

Then recreate both from `docs/DEPLOY.md` Appendix E and
`docs/CUSTOMER360-DEPLOY.md` — an env-file change needs a new container, a
restart will not pick it up.

**The ETLs are the long pole.** Over a hundred cron jobs on the old host resolve
`128.2.1.25` by IP, and they belong to the data team. Find every occurrence:

```bash
grep -rln '128\.2\.1\.25' /data/apps/datascience/ /data/apps/school_fees/ 2>/dev/null
```

Metabase and airflow need the same treatment and are not in that directory.

---

## Rollback

**Before the promote** — nothing has changed on the old host. Delete the standby
and walk away:

```bash
psql -h 127.0.0.1 -U postgres -c "SELECT pg_drop_replication_slot('converter_helper');"
```

**After the promote**, both servers believe they are primaries. The old host's
data is intact and unchanged since Phase 3, so rollback is: stop the new host,
start the old one, restore its crontab, revert the env files. Anything written
to the new host after the promote is lost — which is why Phase 4 happens before
anyone is let back in.

**Do not delete anything on the old host for at least two weeks.**

---

## Ownership and the ETL review (corrected 7 Oct 2026)

**The data team owns the ETLs, Metabase and airflow — that is this team.** An
earlier version of this section listed them as "unowned" and treated them as
external blockers on the cutover date. They are not. What follows is what the
review of `datawarehouse-etls-master` actually found.

### The ETLs are a one-file change, and the forwarder makes it zero

Every production script resolves PostgreSQL through a single dict,
`app.postgres` in `app_settings.py`, and that dict is:

```python
postgres = {'host': '127.0.0.1', ...}
```

**No ETL names `128.2.1.25` anywhere.** They name loopback on the host they run
on, which is why they rely on `trust` over `127.0.0.1` and carry no passwords.

Two consequences, both good:

- The forwarder keeps every one of them working with **no file edited at all**.
  Loopback on the old host continues to reach the database; the scripts cannot
  tell the difference.
- If the scripts are ever moved to the new host instead, it is **one line in one
  file**, not a sweep of 100+ scripts.

This supersedes the earlier claim that "every one of these resolves the old host
by IP". It was wrong, and it made the migration look far more dangerous than it
is.

**One live exception.** `backfilling_transactions_diary.py` declares its own
`postgres` and `postgres_local` dicts (lines 41-52) instead of importing
`app_settings`, and uses them at line 224. Its own docstring says it is
superseded by `transaction_diary_trino_daily.py` for daily loads, so it is
probably not on cron - confirm, then either delete it or make it import
`app_settings` like everything else. Every other hardcoded host in the repo is
inside a commented-out line.

Nothing in the shell wrappers bakes in a host either: they are all
`python3.6 /data/apps/datascience/etls/<name>.py`, with no `psql -h`.

### Hosts in `app_settings.py` that this migration does NOT touch

Sources, not targets, and none of them move: `profits` / `profits_dr` /
`profits_echo` (`10.20.18.11`), `merchant` (`10.50.61.84`), `aml`
(`128.2.5.60`), `aml_prod` (`128.2.5.39`), `crm_prod` (`10.70.10.11`),
`crm_uat`, `school_fees`, `imt`, `lendingcore`, `kocela` (Azure MySQL).

**Worth one check:** `live_postgres` and `data_warehouse_postgres` both point at
**`128.2.1.58`** - a different PostgreSQL host that has not come up anywhere in
this migration. Establish whether anything still reads or writes there before
the window, because if it does it is a second warehouse nobody has accounted
for.

### What actually remains, and it is ours

1. **The 2021 dumps** - 126 GB in `/data/dumps`, dated 27 Oct 2021. Phase 1
   deletes them. Since the data team owns this, it is our call to make, not a
   confirmation to wait for.
2. **Metabase** - owned, but the operational facts stand and are the real risk:
   **no systemd unit and `PPID 1`**, so nothing is known to restart it, and its
   72 MB app database is read-write inside this cluster. Give it a unit file
   *before* the window rather than discovering at cutover that it does not come
   back.
3. **airflow** - `airflow_db` is read-write inside the cluster and must be in
   the copy, which it is.
4. **The timezone split** - old host `+0545`, new host `+0300` (EAT). Cron runs
   against host local time, so every schedule moves 2h45m if a job is
   rescheduled on the new host. This is the one item that is a decision rather
   than a task, and it is ours to take.
5. **Disk on the new host** - 108 GB free, 2-3 GB/day, 36-49 days, zero free
   extents in the volume group. Phase 1 clears enough for the copy.
   `accounts_history` is 257 GB of the 463 and a retention policy there is the
   cheapest 100+ GB available, independent of this migration.

The copy is still the easy half. The difference is that the hard half is now
work we can schedule rather than four conversations we are waiting on.
