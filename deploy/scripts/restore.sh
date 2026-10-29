#!/usr/bin/env bash
# Restores SML ERP from a backup (P1-11, docs/backups.md, "Restoring"). Run as the deploy user.
#   deploy/scripts/restore.sh                 # list the backups
#   deploy/scripts/restore.sh latest          # restore the newest one
#   deploy/scripts/restore.sh 4f2a9c1e        # restore a chosen one (its ID from the list)
# REPLACES the current database and files with those of the backup. The ERP is stopped while
# it runs. Practise on the test server (monthly restore test, spec 2).
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/sml-erp/app}"
export ENV_FILE="${ENV_FILE:-/srv/sml-erp/.env.production}"
BACKUP_ENV="${BACKUP_ENV:-/srv/sml-erp/backup.env}"
WORK="${BACKUP_WORK:-/srv/sml-erp/backups}"
RESTIC_IMAGE="restic/restic:0.17.3"
SNAPSHOT="${1:-}"

set -a; . "$BACKUP_ENV"; set +a
cd "$APP_DIR"
compose() { docker compose -f deploy/docker-compose.prod.yml --env-file "$ENV_FILE" "$@"; }
restic() {
  local mounts=(-v "$WORK/restore:/restore" -v sml-erp-restic-cache:/root/.cache/restic)
  case "$RESTIC_REPOSITORY" in /*) mounts+=(-v "$RESTIC_REPOSITORY:$RESTIC_REPOSITORY") ;; esac
  docker run --rm "${mounts[@]}" \
    -e RESTIC_REPOSITORY -e RESTIC_PASSWORD -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY \
    "$RESTIC_IMAGE" "$@"
}

if [ -z "$SNAPSHOT" ]; then
  mkdir -p "$WORK/restore"
  restic snapshots
  echo "Run again with: restore.sh latest   (or the ID of the backup to restore)"
  exit 0
fi

if [ "${RESTORE_CONFIRMED:-}" != "yes" ]; then
  read -r -p "This REPLACES all data on this server with backup $SNAPSHOT. Type RESTORE to go on: " answer
  [ "$answer" = "RESTORE" ] || { echo "Nothing changed."; exit 1; }
fi

as_root() { docker run --rm --entrypoint sh -v "$WORK:/w" "$RESTIC_IMAGE" -c "$1"; }

echo "== Fetching backup $SNAPSHOT"
mkdir -p "$WORK"
as_root "rm -rf /w/restore && mkdir -p /w/restore"
restic restore "$SNAPSHOT" --target /restore
as_root "chown -R $(id -u):$(id -g) /w/restore"  # restored by root inside the container
FROM="$WORK/restore/backup"
[ -s "$FROM/database/sml_erp.dump" ] || { echo "The backup has no database dump."; exit 1; }

value() { grep "^$1=" "$2" | cut -d= -f2-; }
if [ "$(value FIELD_ENCRYPTION_KEY "$ENV_FILE")" != "$(value FIELD_ENCRYPTION_KEY "$FROM/config/env.production")" ]; then
  echo "NOTE: this server's FIELD_ENCRYPTION_KEY differs from the backup's. Encrypted values"
  echo "(two-factor secrets, mailbox password) need the backup's key: copy that line from"
  echo "$FROM/config/env.production into $ENV_FILE, then run deploy.sh."
fi
DB_USER="$(value POSTGRES_USER "$ENV_FILE")"
DB_NAME="$(value POSTGRES_DB "$ENV_FILE")"

echo "== Stopping the ERP"
compose stop web backend worker scheduler
compose up -d db storage

echo "== Database"
compose exec -T db dropdb -U "$DB_USER" --if-exists --force "$DB_NAME"
compose exec -T db createdb -U "$DB_USER" "$DB_NAME"
compose exec -T db pg_restore -U "$DB_USER" -d "$DB_NAME" --no-owner --exit-on-error < "$FROM/database/sml_erp.dump"

echo "== Files"
compose run --rm --no-deps --user root -v "$FROM/files:/restore/files:ro" backend \
  sh -c "python manage.py ensure_storage_bucket && python manage.py import_files /restore/files"

echo "== Starting the ERP"
compose up -d
for _ in $(seq 1 60); do
  if curl -fsSk https://localhost/api/v1/health/ >/dev/null 2>&1; then
    echo "== Restored backup $SNAPSHOT. Check it in the ERP, then delete $WORK/restore."
    exit 0
  fi
  sleep 5
done
echo "The ERP did not answer after the restore; see: docker compose ... logs backend"
exit 1
