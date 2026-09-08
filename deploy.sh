#!/usr/bin/env bash
# Deploy. Run on the host:  ./deploy.sh
#
# There used to be a wall of commands pasted after every change — pull, build,
# stop, remove, run, migrate, and the same again for the frontend — which is a
# lot of places to mistype something and no way to tell which step failed. This
# is that sequence, once, with the settings that are easy to get wrong (the
# container names, --network=host, the env file, the etl_requests mount) fixed
# where they cannot drift.
#
#   ./deploy.sh              backend and frontend
#   ./deploy.sh backend      backend only
#   ./deploy.sh frontend     frontend only
#   ./deploy.sh --no-pull    rebuild what is already checked out
#
# set -e so it stops at the first failure instead of carrying on and leaving a
# half-deployed pair of containers.
set -euo pipefail

BACKEND_DIR="${BACKEND_DIR:-/data/apps/hf_group_backend}"
FRONTEND_DIR="${FRONTEND_DIR:-/data/apps/portfolio-management-frontend}"
ENV_FILE="${ENV_FILE:-/etc/hf/prod.env}"
ETL_REQUESTS="${ETL_REQUESTS:-/data/apps/datascience/etl_requests}"
BACKEND_IMAGE="hf-backend:latest"
BACKEND_NAME="hf-backend"
FRONTEND_NAME="portfolio-frontend"
FRONTEND_PORT="${FRONTEND_PORT:-5400}"

TARGET="both"
PULL=1
for arg in "$@"; do
  case "$arg" in
    backend|frontend|both) TARGET="$arg" ;;
    --no-pull) PULL=0 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

deploy_backend() {
  say "Backend: $BACKEND_DIR"
  cd "$BACKEND_DIR"
  [ "$PULL" -eq 1 ] && git pull --ff-only

  say "Building $BACKEND_IMAGE"
  docker build -t "$BACKEND_IMAGE" .

  # Replace the container only AFTER the build succeeds, so a broken build
  # leaves the running one alone rather than taking the site down.
  say "Restarting $BACKEND_NAME"
  docker rm -f "$BACKEND_NAME" >/dev/null 2>&1 || true
  docker run -d --name "$BACKEND_NAME" --restart unless-stopped \
    --network=host \
    --env-file "$ENV_FILE" \
    -v "$ETL_REQUESTS:/app/etl_requests" \
    "$BACKEND_IMAGE"

  say "Migrating"
  docker exec "$BACKEND_NAME" python manage.py migrate --noinput

  say "Backend up"
  docker ps --filter "name=$BACKEND_NAME" --format '  {{.Names}}  {{.Status}}'
}

deploy_frontend() {
  say "Frontend: $FRONTEND_DIR"
  cd "$FRONTEND_DIR"
  [ "$PULL" -eq 1 ] && git pull --ff-only

  # A bind-mounted node:22 container, not a baked image — see docs/DEPLOY.md.
  say "Restarting $FRONTEND_NAME (installs and builds inside the container)"
  docker rm -f "$FRONTEND_NAME" >/dev/null 2>&1 || true
  docker run -d --name "$FRONTEND_NAME" --restart unless-stopped \
    -p "$FRONTEND_PORT:$FRONTEND_PORT" \
    -v "$FRONTEND_DIR:/app" -w /app \
    node:22 sh -c "npm ci && npm run build && npm run start -- -p $FRONTEND_PORT"

  say "Frontend starting — the build runs inside the container, so give it a minute"
  echo "  follow it with:  docker logs -f $FRONTEND_NAME"
}

case "$TARGET" in
  backend)  deploy_backend ;;
  frontend) deploy_frontend ;;
  both)     deploy_backend; deploy_frontend ;;
esac

say "Done"
