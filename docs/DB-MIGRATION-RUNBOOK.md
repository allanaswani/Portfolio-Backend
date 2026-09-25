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

Measured 24 Sep 2026. Everything moves: all five databases, 441 GB.

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

**[OLD]** Disk for WAL retention during the copy. A 441 GB base backup takes
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
clearing only the dumps leaves 189 GB free, and the backup needs 441 GB, so it
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
directory. The base backup needs 441 GB; below about 520 GB, stop and find more
space rather than proceeding.

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
end, so a single unreadable file fails the run at 99% and the 441 GB starts
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

**[NEW]** Confirm replay has caught up, then promote:

```bash
psql -h 127.0.0.1 -U postgres -Atc "SELECT pg_last_wal_replay_lsn();"
```
```bash
sudo -u postgres pg_ctl promote -D /data/db_data/pgsql/12/data/data
```
```bash
psql -h 127.0.0.1 -U postgres -Atc "SELECT pg_is_in_recovery();"
```

`f` means it is now a primary and accepting writes.

---

## Phase 4 — Verify before letting anyone in

**[NEW]** Sizes and row counts against what the old host held:

```bash
psql -h 127.0.0.1 -U postgres -c "SELECT datname, pg_size_pretty(pg_database_size(datname)) FROM pg_database WHERE NOT datistemplate ORDER BY pg_database_size(datname) DESC;"
```

Expect `datawarehouse` at 439 GB, `virtual_accounts_activation` 1644 MB,
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

## What is still unowned

Three things gate the cutover date and none belong to this repo:

1. **The ETLs** — 100+ jobs, data team.
2. **Metabase** — 11 connections held open since 9 July, no named owner.
3. **airflow** — `airflow_db` exists and something maintains it.

The copy is the easy half. Every one of these resolves the old host by IP, and
each one missed is an outage the morning after, with no obvious link back to
this migration.
