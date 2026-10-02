# The two database hosts, measured

Measured **2 October 2026** with [`server-benchmark.sh`](server-benchmark.sh),
inventory pass only (`--no-write`). Companion to
[`DB-MIGRATION-RUNBOOK.md`](DB-MIGRATION-RUNBOOK.md), which this informs: the
cutover moves a 441 GB cluster from the first machine to the second, and until
now nobody had measured either one.

Storage performance is **not** in this document. It has not been measured yet,
and the reason is explained under [What is not yet known](#what-is-not-yet-known).

---

## Side by side

| | OLD — `datawarehouseworker-node1`<br>128.2.1.25 | NEW — `converter-helper`<br>10.51.181.25 |
|---|---|---|
| Type | Bare metal, HP ProLiant BL460c Gen8 | KVM guest on Red Hat OpenShift Virtualization |
| CPU | Xeon E5-2643 @ 3.3 GHz *(Sandy Bridge, 2012)* | Xeon Granite Rapids @ 2.1 GHz *(2024)* |
| Cores | 2 sockets × 4 cores × 2 threads = **8 physical** | 4 sockets × 4 cores × 1 thread = **16 vCPU** |
| L3 cache | 10 MB | 16 MB |
| NUMA nodes | 2 | 1 |
| RAM | 78.5 GB (66.6 GB available) | 77.0 GB (73.4 GB available) |
| Swap | **15 GB of 15 GB used — exhausted** | 16 GB, unused |
| `vm.swappiness` | 10 — correct | **30** — should be 1–10 |
| Transparent huge pages | **always** — should be `never` | **always** — should be `never` |
| `/data` | SAN multipath, 700 GB, 107 GB free | virtio LVM, 722 GB, 108 GB free (**86% used**) |
| OS | RHEL 7.7, kernel 3.10 | RHEL 7.7, kernel 3.10 |
| Load average | 3.29 / 5.26 / 4.98 (working) | 0.00 (idle, replaying WAL) |
| Uptime | 27 weeks | 4 days |

Databases on the cluster: **464 GB**.

### On the hardware

The new host is the stronger machine. Granite Rapids against 2012-era Sandy
Bridge is roughly two to three times the work per clock cycle, and 16 real vCPU
against 8 physical cores. The old host's higher clock — 3.3 GHz against 2.1 GHz
— is the figure usually quoted and the least meaningful of the two.

RAM is effectively equal. Storage cannot yet be compared.

---

## Three findings that matter more than the hardware

### 1. PostgreSQL is running on a stock configuration

| Setting | Current | Should be, on a 76 GB host |
|---|---|---|
| `shared_buffers` | **128 MB** | ~16 GB |
| `effective_cache_size` | 4 GB | ~48 GB |
| `work_mem` | 4 MB | 32–64 MB |
| `maintenance_work_mem` | 64 MB | 2 GB |
| `max_wal_size` | 1 GB | 16–32 GB |
| `random_page_cost` | 4.0 | 1.1 if flash-backed |
| `effective_io_concurrency` | 1 | 200 if flash-backed |

128 MB of shared buffers against a 464 GB warehouse. This is the default
`postgresql.conf` as shipped, never tuned.

**This is confirmed on the new host and inferred on the old one.**
`pg_basebackup` copies `postgresql.conf` from the primary, so the standby's
settings are very likely the primary's. If that holds, production has served
the whole warehouse on 128 MB of shared buffers, which would be a far larger
factor in the slowness chased in `perf-slowness-fix` than the gunicorn worker
count was. One command settles it, on the old host:

```bash
sudo -u postgres psql -X -c "SELECT name, setting, unit FROM pg_settings
WHERE name IN ('shared_buffers','effective_cache_size','work_mem','max_wal_size');"
```

### 2. The old host's swap is 100% full

15 GB of 15 GB consumed while 66 GB of RAM sits available. Something was paged
out under memory pressure and never came back; anything PostgreSQL left there
is read back at swap latency rather than memory latency. `vm.swappiness` is
correctly set to 10, so this was pressure, not policy.

Find what is holding it:

```bash
smem -s swap -r | head -15
# or, without installing smem:
for f in /proc/*/status; do
  awk '/^Name:|^VmSwap:/{printf "%s ", $2} END{print ""}' "$f"
done | sort -k2 -hr | head -15
```

### 3. The application tier is 8 ms from its own database

`converter-helper → 128.2.1.25` averages **8.19 ms** (3.2–11 ms, mdev 3.5 ms).
The application runs on converter-helper; the database is still on the old host
(see `app-tier-move-to-converter-helper`). Every query pays that round trip — a
page issuing fifty queries spends 400 ms on network latency alone before any
work is done. For two machines in the same datacentre this is very high.

Completing the cutover removes it entirely. No amount of tuning on either side
will.

---

## What is not yet known

**Storage performance, on either machine.** The usual quick indicator — the
`ROTA` flag, spinning against flash — cannot be read here. The old host's
`/data` is SAN multipath and the new host is a virtio guest; both report
`ROTA=1` on every device regardless of what is actually behind them, because
neither the guest nor the multipath layer can see the array. An earlier draft
of the benchmark script led on this figure, which was wrong for exactly these
two machines.

On virtualised or SAN storage the only honest answer is to measure:

```bash
yum install -y fio postgresql12-contrib
sh docs/server-benchmark.sh --dir /data/tmp --size 4 | tee ~/bench-$(hostname)-$(date +%F).txt
```

The figure that decides the cutover is **`fdatasync` operations per second**.
Every `COMMIT` waits for one fsync, so that number is the ceiling on write
transactions per second no matter how many cores or how much RAM the machine
has. Run it out of hours on the old host, and watch replication lag afterwards
on the new one.

---

## Open items

- [ ] Confirm `postgresql.conf` on the old host — the settings above
- [ ] Run `fio` and `pg_test_fsync` on both hosts
- [ ] Identify what is holding 15 GB in swap on the old host
- [ ] `/data` on the new host is 86% full with 464 GB of databases already
      present; establish what the other ~150 GB is before cutover
      (`du -xh --max-depth=2 /data | sort -hr | head -15`)
- [ ] Set `vm.swappiness=10` on the new host
- [ ] Set transparent huge pages to `never` on both
- [ ] RHEL 7.7 is past end of life on both machines

Three items from the runbook still gate the cutover date and are not technical
properties of either host: the ETL jobs, Metabase, and airflow, each of which
resolves the old host by IP.
