# Customer 360 — deployment and updates

**23 Sep 2026: Customer 360 moved from `128.2.1.25` to `10.51.181.25`
(`converter-helper`).** It now sits on the same host as the portfolio app.
The note in `docs/MIGRATION.md` that Customer 360 does not move is superseded
by this file.

## Where everything runs now

All on `10.51.181.25` (`converter-helper`):

| Service | Container | Port | Source directory |
|---|---|---|---|
| Portfolio backend | `hf-backend` | 9000 | — |
| Portfolio frontend | `portfolio-frontend` | 5400 | `/data/apps/hf/portfolio-management-frontend` |
| C360 backend | `c360-backend` | 9001 | `/data/apps/customer360/c360_Backennd` |
| C360 frontend | `c360-frontend` | 5401 | `/data/apps/customer360/c360_Frontend` |

Still on `128.2.1.25` (`datawarehouseworker-node1`): **both PostgreSQL
databases** and the ETL scripts. Nothing else of ours.

Env files: `/etc/hf/c360.env`, `/etc/hf/c360-frontend.env`,
`/etc/hf/portfolio-frontend.env`.

C360 app database (SQLite): `/data/apps/customer360/appdb/db.sqlite3`,
bind-mounted into the container at `/app/appdb`.

## Updating Customer 360 after a code change

### Backend — rebuild the image

```bash
cd /data/apps/customer360/c360_Backennd
```
```bash
git pull
```
```bash
docker build -t c360-backend:latest .
```
```bash
docker rm -f c360-backend
```
```bash
docker run -d --name c360-backend --restart unless-stopped --network=host --env-file /etc/hf/c360.env -v /data/apps/customer360/appdb:/app/appdb c360-backend:latest gunicorn config.wsgi:application --bind 0.0.0.0:9001 --workers 3 --timeout 120 --access-logfile -
```
```bash
curl -s -o /dev/null -w 'c360 api: %{http_code}\n' http://127.0.0.1:9001/api/meta/
```

If the change includes Django migrations, back up the SQLite file first — the
entrypoint never migrates:

```bash
cp /data/apps/customer360/appdb/db.sqlite3 /data/apps/customer360/appdb/db.sqlite3.bak-$(date +%F)
```
```bash
docker exec c360-backend python manage.py migrate
```

### Frontend — recreate the container

Bind-mounted, so there is no image to rebuild, but it only builds at container
start. `git pull` **first**, then recreate.

```bash
cd /data/apps/customer360/c360_Frontend
```
```bash
git pull
```
```bash
docker rm -f c360-frontend
```
```bash
docker run -d --name c360-frontend --restart unless-stopped -p 5401:3000 -v "$(pwd)":/app -w /app --add-host=host.docker.internal:host-gateway --env-file /etc/hf/c360-frontend.env node:22 sh -c "npm i && npm run build && npm start"
```
```bash
docker logs c360-frontend -f --tail 40
```

Wait for `Ready in …`, then:

```bash
curl -s -o /dev/null -w 'c360 ui: %{http_code}\n' http://127.0.0.1:5401/customer-360
```

Pushing to git alone changes nothing live. There is no auto-deploy.

## Portfolio frontend

Same pattern — bind-mounted, `git pull` then recreate:

```bash
cd /data/apps/hf/portfolio-management-frontend
```
```bash
git pull
```
```bash
docker rm -f portfolio-frontend
```
```bash
docker run -d --name portfolio-frontend --restart unless-stopped -p 5400:3000 -v "$(pwd)":/app -w /app --env-file /etc/hf/portfolio-frontend.env node:22 sh -c "npm i && npm run build && npm start"
```

## Env file contents

`/etc/hf/c360-frontend.env`:

```
NEXT_PUBLIC_BASE_PATH=/customer-360
NEXT_PUBLIC_API_BASE=/customer-360/api
C360_BACKEND_ORIGIN=http://host.docker.internal:9001
```

`/etc/hf/portfolio-frontend.env`:

```
NODE_OPTIONS=--max-old-space-size=4096
BACKEND_ORIGIN=http://10.51.181.25:9000
NEXT_PUBLIC_BACKEND_ORIGIN=http://10.51.181.25:9000
CUSTOMER360_API_ORIGIN=http://10.51.181.25:9001
CUSTOMER360_APP_ORIGIN=http://10.51.181.25:5401
```

The two `CUSTOMER360_*` keys are read by `next.config.mjs` lines 23–24 and
default to `128.2.1.25` when unset. Omit them and the portfolio silently serves
Customer 360 from the old host — every page loads and every number looks real.
They are build-time, so changing them needs a full recreate, not a restart.

`/etc/hf/c360.env` — the keys that changed during the move:

```
PG_HOST=128.2.1.25
DJANGO_ALLOWED_HOSTS=ceo.hfcb.co.ke,10.51.181.25,128.2.1.25,localhost,127.0.0.1,172.17.0.1,host.docker.internal
C360_CORS_ORIGINS=https://ceo.hfcb.co.ke,http://10.51.181.25:5401,http://10.51.181.25:5400
C360_CSRF_TRUSTED_ORIGINS=https://ceo.hfcb.co.ke,http://10.51.181.25:5401,http://10.51.181.25:5400
```

`PG_HOST` is now a network hop, not loopback — both databases stayed behind.
`host.docker.internal` in `DJANGO_ALLOWED_HOSTS` is required: the C360 frontend
proxies to `http://host.docker.internal:9001`, so that is the `Host` header
Django receives. Remove it and every proxied request returns 400.

## Things that cost time during the move

**Moving files between the two hosts: pull, do not push.** `scp` from the old
host as `root` is refused — the new host runs `PermitRootLogin
prohibit-password`, and adding an SSH key did not help either (SELinux left
`authorized_keys` unlabelled, and `restorecon` still did not get through). The
direction that works is from the **new** host, as a named user, matching
`docs/MIGRATION.md:277`:

```bash
scp admlin01@128.2.1.25:'/tmp/c360xfer/*' /tmp/
```

A Python `http.server` on the old host is not an alternative — firewalld drops
the port and the pull fails with `No route to host`.

**`/etc/hf/c360.env` cannot be sourced by bash.** One line is
`DEFAULT_FROM_EMAIL=HFCB Customer 360 <Reports...>` — unquoted spaces and `<`,
which bash parses as a redirect. `set -a; . /etc/hf/c360.env` dies part-way and
leaves the later variables unset, which is what made a Postgres connectivity
test silently connect as user `root`. Docker's `--env-file` does not shell-parse
and reads the file correctly. To read one value in a shell, grep it:

```bash
grep -m1 '^PG_USER=' /etc/hf/c360.env | cut -d= -f2-
```

**Long `docker run` lines split when pasted into the terminal**, producing
errors that look like application faults. `Error: No application module
specified` from gunicorn was a pasted line break between `gunicorn` and
`config.wsgi:application`, not a config problem. Keep the command on one line,
put env vars in an `--env-file`, and avoid `sh -c` where the port can be
hardcoded.

**`docker restart` does not pick up env file changes.** The environment is
fixed when the container is created. Any `/etc/hf/*.env` edit needs
`docker rm -f` plus `docker run`.

## Why C360 must stay on the same host as the portfolio

The portfolio is the identity provider and hands its JWT to C360. While the two
were split across hosts the handoff broke: `localStorage` is per-origin, and a
cookie set on one IP is never sent to another, so the token could not travel
even though both backends sign with the same key. Same host on different ports
works because cookies ignore port numbers — which is why this was fine before
the app tier moved, and fine again now.

If C360 ever needs to live on a different host from the portfolio, the token has
to be passed explicitly, or both must sit behind one hostname
(`ceo.hfcb.co.ke`). See [[customer-360-sso]] for the claim contract itself.

## Rollback

The old containers were stopped, not removed:

```bash
ssh 128.2.1.25 'docker start c360-backend c360-frontend'
```

Then on `10.51.181.25`, recreate `portfolio-frontend` with the two
`CUSTOMER360_*` lines removed from `/etc/hf/portfolio-frontend.env`.

Anything written in C360 after the cutover lives in the new host's SQLite file
and will not be present in the old one.
