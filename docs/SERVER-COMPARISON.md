# The two database hosts, measured

Measured **2 October 2026** with [`server-benchmark.sh`](server-benchmark.sh).
The old host has a complete run including storage; the new host's storage
figures are still outstanding (see [Still missing](#still-missing)).
Companion to
[`DB-MIGRATION-RUNBOOK.md`](DB-MIGRATION-RUNBOOK.md), which this informs: the
cutover moves a 441 GB cluster from the first machine to the second, and until
now nobody had measured either one.


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

The new host is the stronger machine, and now measurably so:

| Per-core test | OLD | NEW | |
|---|---|---|---|
| openssl AES-256-CBC, 8 kB blocks | 493,308 k/s | **943,240 k/s** | 1.91× |
| Integer loop (lower is better) | 2.96 s | **2.42 s** | 1.22× |

The integer loop is the more honest general-purpose figure; AES flatters newer
silicon because of instruction-set work. 22% faster per core *while running at
2.1 GHz against 3.3 GHz* implies roughly 1.9× the work per clock — consistent
with Granite Rapids against 2012 Sandy Bridge. With 16 real vCPU against 8
physical cores, total CPU throughput is comfortably more than double.

The old host's higher clock is the figure usually quoted and the least
meaningful of the two.

RAM is effectively equal.

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

**Confirmed on BOTH hosts** — the two configurations are byte-identical on
every setting measured. Production has been serving the whole warehouse on
128 MB of shared buffers. This is almost certainly a larger factor in the
slowness chased in `perf-slowness-fix` than the gunicorn worker count was, and
it is the cheapest improvement available on either machine.

Changing `shared_buffers` needs a restart; the rest take a reload. Do it on the
primary — the standby inherits nothing here, so it must be set on both, and on
a standby `shared_buffers` must be at least what the primary had.

### 2. The old host's swap is 100% full

15 GB of 15 GB consumed while 66 GB of RAM sits available. Something was paged
out under memory pressure and never came back; anything PostgreSQL left there
is read back at swap latency rather than memory latency. `vm.swappiness` is
correctly set to 10, so this was pressure, not policy.

It is also still happening. The `vmstat` sample taken during the run shows
`so` (pages swapped **out**) at 9, 76, 60, 0, 56 across five consecutive
seconds, with 310 MB of free memory and one process permanently in the blocked
queue. This is live memory pressure, not a historical scar.

The likely cause is visible in the same output: a **java process holding
8.5 GB RSS (10.3% of memory)** at 14.7% CPU — almost certainly Metabase, which
`DB-MIGRATION-RUNBOOK.md` already records as holding 11 database connections
with no named owner.

Confirm before acting:

```bash
ps -eo pid,comm,rss,%mem --sort=-rss | head
smem -s swap -r | head -15
# or, without installing smem:
for f in /proc/*/status; do
  awk '/^Name:|^VmSwap:/{printf "%s ", $2} END{print ""}' "$f"
done | sort -k2 -hr | head -15
```

### 3. The application tier is several milliseconds from its own database

The application runs on converter-helper; the database is still on the old host
(see `app-tier-move-to-converter-helper`), so every query pays a round trip.

Measured, in both directions and on separate runs:

| Path | Sample 1 | Sample 2 |
|---|---|---|
| converter-helper → 128.2.1.25 | 8.19 ms | **2.92 ms** |
| 128.2.1.25 → converter-helper | — | **7.04 ms** (mdev 5.5) |
| 128.2.1.25 → Trino lake | — | **1.02 ms** |
| converter-helper → Trino lake | 8.80 ms | **7.62 ms** |

**These are three-packet samples and they disagree with each other**, which is
itself the finding: the path between the two hosts is somewhere between 3 and
8 ms and is *variable* (mdev up to 5.5 ms). An earlier draft of this document
quoted the 8.19 ms figure as settled and extrapolated "400 ms per page" from
it. That was one noisy sample and overstated the case. The honest statement is
that the hop costs single-digit milliseconds, varies, and is well above what
two machines in one datacentre should show.

Worth measuring properly before anyone acts on it:

```bash
ping -c 100 -i 0.2 10.51.181.25 | tail -2
```

Note the asymmetry in the lake figures: the **old** host is 1 ms from Trino,
the new one 7.6 ms. That is the opposite of what the cutover needs, and it
affects the Trino tools in `apps/agent/trino_tools.py`, which run on the app
tier. Bulk ETL reads are not latency-sensitive; a per-request tool call is.

Completing the cutover co-locates the application with the database, which is
the latency-sensitive path. It moves the ETLs *away* from the database by the
same amount, but those are bulk jobs and far less sensitive.

---

## Storage, measured

The usual quick indicator — the `ROTA` flag — cannot be read on either machine.
The old host's `/data` is SAN multipath and the new host is a virtio guest;
both report `ROTA=1` on every device regardless of what is behind them, because
neither the guest nor the multipath layer can see the array. An earlier draft
of the benchmark script led on that figure, which was wrong for exactly these
two machines.

Measured instead, with `pg_test_fsync` and `dd conv=fdatasync`:

| OLD — datawarehouseworker-node1 | |
|---|---|
| **fdatasync** | **1,794 ops/sec — 557 µs/op** |
| fdatasync, two 8 kB writes | 1,957 ops/sec — 511 µs |
| open_datasync | 1,686 ops/sec — 593 µs |
| fsync | 892 ops/sec — 1,121 µs |
| Non-synced 8 kB write | 224,667 ops/sec — 4 µs |
| Sequential write (4 GB, fdatasync) | 577 MB/s |
| Sequential read (cached — inflated) | 4.3 GB/s |

**1,794 fdatasync ops/sec is a healthy figure** and comfortably above the
~1,000 threshold worth worrying about. At 557 µs it is not flash — flash would
be 5,000–30,000+ — but it is far faster than raw spinning disk, which sits at
5–10 ms. That profile is a SAN with a battery-backed write cache, which is
consistent with the multipath devices in the inventory.

The gap between 4 µs un-synced and 557 µs synced is the cost of durability, and
it is the reason `fdatasync` ops/sec rather than MB/s is the number that governs
write throughput.

---

## Still missing

**The new host's storage figures.** The run failed because `/data/tmp` did not
exist there, and an earlier version of the script `cd`'d into it without
checking — so sections 7 and 8 were skipped while the report still looked
complete. Fixed; the script now creates the directory or stops.

```bash
mkdir -p /data/tmp
sh docs/server-benchmark.sh --dir /data/tmp --size 4 | tee ~/bench-new-$(date +%F).txt
```

Until that runs, **whether converter-helper can carry the write load is
unknown**, and it is the one question this whole exercise exists to answer.

`pg_test_fsync` is already installed on both hosts — it ran on the old one, and
the script located it on the new one. **Do not run `yum install
postgresql12-contrib` again**: it resolves `postgresql12-server` as a
dependency and would upgrade the running database from 12.1 to 12.22. It failed
only because the PGDG RHEL 7 repository now returns HTTP 410, PostgreSQL 12
being end-of-life. That was luck, not safety.

`fio` is unavailable in the configured repositories, so random-IOPS figures are
missing for both hosts. `pg_test_fsync` covers the question that matters most.

## Open items

- [x] Confirm `postgresql.conf` on the old host — identical stock config
- [x] Run `pg_test_fsync` on the old host — 1,794 ops/sec, healthy
- [ ] **Run `pg_test_fsync` on the new host** (`mkdir -p /data/tmp` first) —
      the one outstanding number that decides the cutover
- [ ] Tune `postgresql.conf` on both — the table above
- [ ] Confirm the 8.5 GB java process is Metabase, and whether it explains the
      15 GB of swap on the old host
- [ ] Measure the inter-host hop properly (`ping -c 100 -i 0.2`)
- [ ] `/data` on the new host is 86% full with 464 GB of databases already
      present; establish what the other ~150 GB is before cutover
      (`du -xh --max-depth=2 /data | sort -hr | head -15`)
- [ ] Set `vm.swappiness=10` on the new host
- [ ] Set transparent huge pages to `never` on both
- [ ] RHEL 7.7 is past end of life on both machines

Three items from the runbook still gate the cutover date and are not technical
properties of either host: the ETL jobs, Metabase, and airflow, each of which
resolves the old host by IP.
