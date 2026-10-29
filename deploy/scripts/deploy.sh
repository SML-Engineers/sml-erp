#!/usr/bin/env bash
# Install or update SML ERP on this server from GitHub (P1-10). Run as the deploy user:
#   /srv/sml-erp/app/deploy/scripts/deploy.sh            # the latest main
#   /srv/sml-erp/app/deploy/scripts/deploy.sh v1.0.0     # a release tag
# It fetches the code, builds the images, applies database changes, restarts the services
# and checks that the ERP answers. Data (database, files, certificates) is kept in Docker
# volumes and is not touched by an update.
set -euo pipefail

# Run from a copy: checking out the new version changes this very file.
if [ -z "${SML_DEPLOY_COPY:-}" ]; then
  copy="$(mktemp)"
  cp "$0" "$copy"
  SML_DEPLOY_COPY=1 exec bash "$copy" "$@"
fi

REF="${1:-origin/main}"
APP_DIR="${APP_DIR:-/srv/sml-erp/app}"
export ENV_FILE="${ENV_FILE:-/srv/sml-erp/.env.production}"

[ -f "$ENV_FILE" ] || { echo "No $ENV_FILE: create it first with deploy/scripts/make-env.sh"; exit 1; }
cd "$APP_DIR"
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Files on this server were changed by hand; deploying would hide that. Stopping."
  git status --short
  exit 1
fi

echo "== Fetching $REF from GitHub"
git fetch --tags --prune origin
git checkout --quiet --detach "$REF"
export APP_VERSION
APP_VERSION="$(git describe --tags --always)"
echo "   version $APP_VERSION"

compose() { docker compose -f deploy/docker-compose.prod.yml --env-file "$ENV_FILE" "$@"; }

echo "== Building"
compose build --pull
echo "== Starting (database changes are applied first)"
compose up -d --remove-orphans

echo "== Checking that the ERP answers"
for _ in $(seq 1 60); do
  if curl -fsSk https://localhost/api/v1/health/ >/dev/null 2>&1; then
    curl -fsSk https://localhost/api/v1/health/; echo
    docker image prune -f >/dev/null
    echo "== Done: version $APP_VERSION is running."
    exit 0
  fi
  sleep 5
done
echo "The ERP did not answer within 5 minutes. Recent logs:"
compose ps
compose logs --tail=80 migrate backend web
exit 1
