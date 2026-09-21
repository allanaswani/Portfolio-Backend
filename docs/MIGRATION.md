# Moving the platform off `datawarehouseworker-node1`

From **128.2.1.25** (`datawarehouseworker-node1`) to **10.51.181.25**
(`converter-helper`).

This is a runbook, not a script. Read Phase 0 and Phase 1 before running
anything: the size and the risk of this change depend on one decision that has
not been made yet, and the two answers lead to very different work.

---

## What is actually on the old host

Established from the repo and `/etc/hf/prod.env`, not assumed:

| Piece | What it is | Moves easily? |
|---|---|---|
| `hf-backend` | Docker container, Django on **:9000**, `--network=host` | Yes |
| `portfolio-frontend` | Docker container, bind-mounted Next.js on **:5400** | Yes |
| **`hf_group_app`** | Application PostgreSQL DB, `DB_HOST=127.0.0.1` — **on this host** | Needs a dump/restore |
| **`datawarehouse`** | Warehouse PostgreSQL DB, `DW_HOST=128.2.1.25` — **also this host** | **See Phase 1** |
| 9 cron jobs | `docker exec hf-backend …` + the ETL watcher | Yes, re-install |
| `/data/apps/datascience/` | ETL scripts, **owned by the data team**, host `python3.6` | **Not ours to move** |
| Apache | Reverse proxy in front (it served the 503s) | Config must be ported |

Two facts matter more than the rest:

1. **Both databases live on the old host.** `DB_HOST=127.0.0.1` and
   `DW_HOST=128.2.1.25` are the same machine.
2. **The warehouse is fed by ETLs this repo does not own.** They run on the
   host as `python3.6` out of `/data/apps/datascience/etls/`, and the app only
   drops request files into a shared directory for them. Those scripts, their
   schedule and their own sources are the data team's.

---

## Phase 0 — Inventory. Read-only, run on the OLD host

Nothing below writes anything. Run it and keep the output; several later
decisions depend on the numbers.

```bash
# ── what is running ──────────────────────────────────────────────────────────
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
docker images | head

# ── database sizes: the single most important number in this migration ───────
set -a; . /etc/hf/prod.env; set +a
export PGPASSWORD="$DW_PASSWORD"
psql -h "${DW_HOST:-127.0.0.1}" -p "${DW_PORT:-5432}" -U "$DW_USER" -d postgres -c \
  "SELECT datname, pg_size_pretty(pg_database_size(datname)) AS size
   FROM pg_database WHERE datistemplate = false ORDER BY pg_database_size(datname) DESC;"

psql -h "${DW_HOST:-127.0.0.1}" -p "${DW_PORT:-5432}" -U "$DW_USER" -d "$DW_NAME" -c \
  "SELECT count(*) AS tables FROM information_schema.tables WHERE table_schema='public';"

# ── versions, so the new host matches ────────────────────────────────────────
psql -h "${DW_HOST:-127.0.0.1}" -U "$DW_USER" -d postgres -c 'SELECT version();'
docker --version; cat /etc/redhat-release; python3 --version

# ── everything scheduled ─────────────────────────────────────────────────────
crontab -l > ~/crontab-old-host.txt; cat ~/crontab-old-host.txt

# ── the proxy in front ───────────────────────────────────────────────────────
grep -rn "5400\|9000\|ProxyPass" /etc/httpd/conf/httpd.conf /etc/httpd/conf.d/ 2>/dev/null | head -20

# ── disk, so the new host is sized for it ────────────────────────────────────
df -h
du -sh /var/lib/pgsql /data/apps/datascience 2>/dev/null
```

---

## Phase 1 — Decide this before anything else

**Does the warehouse database move too, or stay where it is?**

The two answers are different projects.

### Option A — move the app tier only *(recommended first step)*

The two containers move. `hf_group_app` moves with them. `datawarehouse` stays
on 128.2.1.25 and the new host reaches it over the network.

* Low risk, reversible in minutes, no data-team involvement.
* The ETLs keep running exactly where they are, writing to the database they
  already write to.
* Needs: `pg_hba.conf` on the old host to accept the new host, and
  `DW_HOST=128.2.1.25` left as it is.
* Cost: every warehouse query crosses the network. On the same VLAN that is
  usually fine; the dashboards are already slow enough that it is worth
  measuring rather than assuming.

**The ETL report buttons stop working under Option A** unless
`/data/apps/datascience/etl_requests` is shared. The app writes a request file
and a watcher on the OLD host picks it up — if the app moves and the directory
does not, the buttons queue into a directory nobody is watching, silently. Either
NFS-mount that path onto the new host, or keep the watcher and the app on the
same machine.

### Option B — move the databases as well

Everything lands on converter-helper.

* The ETLs must be repointed or moved, and they are **not this repo's** — that
  is a conversation with the data team before a single byte is copied.
* Needs a maintenance window sized by the `pg_database_size` output from Phase
  0. A warehouse of any size is hours, not minutes.
* `DW_HOST` changes, and anything else in the bank pointing at 128.2.1.25 has
  to be found first. Assume something does.

**Recommendation:** do A, run on it for a week, then decide about B with real
numbers. Doing both at once means that when something breaks you will not know
which half broke it.

---

## Phase 2 — Prepare the new host

```bash
# Docker. The old host runs Docker, NOT podman - podman was tried there and did
# not work (docs/DEPLOY.md). Match it.
sudo yum install -y docker && sudo systemctl enable --now docker
docker --version

# Repos, in the same layout as the old host
sudo mkdir -p /opt/hfcb && cd /opt/hfcb
git clone <backend-remote>  Portfolio-Backend
git clone <frontend-remote> portfolio-management-frontend-react

# Secrets. COPY the file, do not retype it - SECRET_KEY changing logs every
# user out and invalidates every issued token.
sudo mkdir -p /etc/hf
sudo scp admlin01@128.2.1.25:/etc/hf/prod.env /etc/hf/prod.env
sudo chmod 600 /etc/hf/prod.env
```

Then edit `/etc/hf/prod.env` for the new address — three keys, and they are not
interchangeable:

| Key | Value | Note |
|---|---|---|
| `ALLOWED_HOSTS` | `10.51.181.25` | **Host only, no port.** Django strips the port. |
| `CORS_ALLOWED_ORIGINS` | `http://10.51.181.25:5400` | Scheme + host + **port**, no trailing slash. |
| `CSRF_TRUSTED_ORIGINS` | `http://10.51.181.25:5400` | Same value as the CORS origin. |

Get one of those wrong and login fails in a way that does not look like a
config problem: the POST shows as red-X / "0 B transferred" in devtools, only
the `OPTIONS` preflight reaches gunicorn, and the screen says "Invalid
credentials".

Under Option A, leave `DW_HOST=128.2.1.25` alone and open the path:

```bash
# on the OLD host, as postgres
echo "host  datawarehouse  <dw_user>  10.51.181.25/32  md5" >> /var/lib/pgsql/data/pg_hba.conf
systemctl reload postgresql
# and from the NEW host, prove it before going further
psql -h 128.2.1.25 -U <dw_user> -d datawarehouse -c 'SELECT 1;'
```

---

## Phase 3 — The application database

`hf_group_app` holds users, service desk tickets, trade register entries,
targets, history — everything this repo owns. It moves with a dump.

```bash
# OLD host
set -a; . /etc/hf/prod.env; set +a
PGPASSWORD="$DB_PASSWORD" pg_dump -h 127.0.0.1 -U "$DB_USER" -Fc "$DB_NAME" \
  > ~/hf_group_app-$(date +%F).dump
ls -lh ~/hf_group_app-*.dump

# NEW host
scp admlin01@128.2.1.25:~/hf_group_app-*.dump .
sudo -u postgres createdb hf_group_app
PGPASSWORD="$DB_PASSWORD" pg_restore -h 127.0.0.1 -U "$DB_USER" -d hf_group_app \
  --no-owner --no-privileges hf_group_app-*.dump

# prove it arrived
psql -h 127.0.0.1 -U "$DB_USER" -d hf_group_app -c \
  "SELECT count(*) FROM auth_user;
   SELECT count(*) FROM service_desk_ticket;
   SELECT count(*) FROM trade_register_traderegisterentry;"
```

Compare those three counts with the same query on the old host **before**
cutting over. They must match exactly.

---

## Phase 4 — Bring the app up on the new host

```bash
cd /opt/hfcb/Portfolio-Backend && git pull
docker build -t hf-backend:latest .

# migrate first, so new code never queries a missing column
docker run --rm --network=host --env-file /etc/hf/prod.env \
  hf-backend:latest python manage.py migrate

docker run -d --name hf-backend --restart unless-stopped \
  --network=host \
  --env-file /etc/hf/prod.env \
  -v /data/apps/datascience/etl_requests:/app/etl_requests \
  hf-backend:latest
docker logs -f hf-backend

cd /opt/hfcb/portfolio-management-frontend-react && git pull
docker run -d --name portfolio-frontend --restart unless-stopped \
  -e NODE_OPTIONS="--max-old-space-size=4096" \
  -v $(pwd):/app -w /app -p 5400:3000 \
  node:22 sh -c "npm install && npm run build && npm run start"
docker logs portfolio-frontend -f --tail 30
```

Then the schedule. Install it from the file, never by pasting — a cron line
here is long enough that a terminal will wrap it, and a newline inside one
turns the whole crontab into "bad minute, errors in crontab file". That has
already cost this deployment its entire crontab once.

```bash
crontab -l > /tmp/cron.bak 2>/dev/null
grep -v 'hf-backend python manage.py' /tmp/cron.bak > /tmp/cron.new
cat /opt/hfcb/Portfolio-Backend/docs/crontab.txt >> /tmp/cron.new
crontab /tmp/cron.new
crontab -l | wc -l          # sanity: this should have GROWN, not shrunk
```

`docs/crontab.txt` does not carry `precompute_slides` or
`run_insights_pipeline` — add them, per `docs/DEPLOY.md`:

```
*/5 * * * *  docker exec hf-backend python manage.py precompute_slides
0  */6 * * * docker exec hf-backend python manage.py run_insights_pipeline
```

---

## Phase 5 — Verify before switching anybody over

Run these against the NEW host while the old one is still serving:

```bash
curl -sf http://10.51.181.25:9000/api/docs/ >/dev/null && echo "backend ok"
curl -sf http://10.51.181.25:5400/         >/dev/null && echo "frontend ok"

docker exec hf-backend python manage.py check --deploy
docker exec hf-backend python manage.py check_warehouse_columns   # warehouse reachable?
docker exec hf-backend python manage.py staff_audit | head -12    # real data?
docker exec hf-backend python manage.py rm_figures --all | head
```

Then by hand, because these are the things a curl cannot tell you:

- log in — proves ALLOWED_HOSTS / CORS / CSRF and the OTP email path
- open the CEO board and step a few slides — proves the warehouse connection
- raise and close a service desk ticket — proves the app DB **and** outbound mail
- press one ETL report button — proves the `etl_requests` mount actually
  reaches a watcher. **This is the one most likely to be silently broken.**

---

## Cutover and rollback

The old host keeps everything. Nothing is deleted on 128.2.1.25 during this
migration — not the containers, not the databases, not the cron jobs. It is
stopped, and stopping is reversible.

```bash
# OLD host - stop serving, keep everything
docker stop hf-backend portfolio-frontend
crontab -l > ~/crontab-final.txt
crontab -r        # or comment the hf-backend lines out

# rollback, if the new host disappoints
docker start hf-backend portfolio-frontend
crontab ~/crontab-final.txt
```

Point Apache (or whatever fronts these) at the new host only after Phase 5
passes. Until then both can run, and only one is in the DNS.

**Do not delete anything on the old host for at least two weeks.** The app DB
dump is a point in time; anything written to the old host after the dump and
before the cutover is lost unless you dump again at the moment you switch. Plan
the cutover for a quiet hour and re-dump immediately before it.

---

## The things most likely to bite

1. **The ETL request mount.** The buttons return 202 whether or not anybody is
   listening. If the watcher stays on the old host and the app moves, reports
   silently stop being emailed and nothing on screen says so.
2. **`SECRET_KEY`.** Copy the file. A new key logs everyone out and invalidates
   every issued token.
3. **`ALLOWED_HOSTS` with a port in it.** Django strips the port; the check
   then fails and the error does not mention the port.
4. **The crontab.** Install from the file. See above.
5. **Anything else pointing at 128.2.1.25.** Under Option B the warehouse
   address changes, and this platform is unlikely to be its only reader.
6. **Prod schema drift.** Some prod tables lack `id` sequences and some
   `0001_initial` migrations are shadowed by legacy `django_migrations` rows —
   a restore onto a fresh database can behave differently from the original.
   `check_warehouse_columns` and `staff_audit` are the fastest way to see it.
