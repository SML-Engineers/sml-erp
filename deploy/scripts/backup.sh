#!/usr/bin/env bash
# Nightly backup of SML ERP (P1-11, docs/backups.md). Run every night by the sml-erp-backup
# timer (set up by server-setup.sh), or by hand as the deploy user.
#
# 1. a dump of the database (pg_dump, while the ERP keeps running);
# 2. every stored file (scanned invoices...) mirrored into a plain folder;
# 3. the server's environment file (it holds the key to encrypted data in the database);
# 4. all three sent, encrypted, to the backup storage outside Hostinger (restic): only what
#    changed since the last night is sent; daily copies are kept 30 days, month-end ones a
#    year; the storage is checked once a week.
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/sml-erp/app}"
export ENV_FILE="${ENV_FILE:-/srv/sml-erp/.env.production}"
BACKUP_ENV="${BACKUP_ENV:-/srv/sml-erp/backup.env}"
WORK="${BACKUP_WORK:-/srv/sml-erp/backups}"
RESTIC_IMAGE="restic/restic:0.17.3"

[ -f "$BACKUP_ENV" ] || { echo "No $BACKUP_ENV: backups are not set up yet (docs/backups.md)."; exit 0; }
set -a; . "$BACKUP_ENV"; set +a
: "${RESTIC_REPOSITORY:?Set RESTIC_REPOSITORY in $BACKUP_ENV}"
: "${RESTIC_PASSWORD:?Set RESTIC_PASSWORD in $BACKUP_ENV}"
value() { grep "^$1=" "$ENV_FILE" | cut -d= -f2-; }
ENVIRONMENT="$(value APP_ENVIRONMENT)"
DB_USER="$(value POSTGRES_USER)"
DB_NAME="$(value POSTGRES_DB)"

ping_monitor() {
  [ -n "${HEALTHCHECK_URL:-}" ] && curl -fsS -m 10 --retry 3 "$HEALTHCHECK_URL$1" >/dev/null || true
}
trap 'echo "BACKUP FAILED"; ping_monitor /fail' ERR

cd "$APP_DIR"
compose() { docker compose -f deploy/docker-compose.prod.yml --env-file "$ENV_FILE" "$@"; }
restic() {
  local mounts=(-v "$WORK:/backup:ro" -v sml-erp-restic-cache:/root/.cache/restic)
  case "$RESTIC_REPOSITORY" in /*) mkdir -p "$RESTIC_REPOSITORY"; mounts+=(-v "$RESTIC_REPOSITORY:$RESTIC_REPOSITORY") ;; esac
  docker run --rm "${mounts[@]}" \
    -e RESTIC_REPOSITORY -e RESTIC_PASSWORD -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY \
    --hostname "sml-erp-$ENVIRONMENT" "$RESTIC_IMAGE" "$@"
}

ping_monitor /start
mkdir -p "$WORK/database" "$WORK/files" "$WORK/config"
chmod 700 "$WORK"

echo "== $(date '+%F %T') Database"
compose exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME" --format=custom > "$WORK/database/sml_erp.dump.partial"
mv "$WORK/database/sml_erp.dump.partial" "$WORK/database/sml_erp.dump"

echo "== $(date '+%F %T') Files"
compose run --rm --no-deps --user root -v "$WORK/files:/backup/files" backend \
  python manage.py export_files /backup/files

echo "== $(date '+%F %T') Environment file"
install -m 600 "$ENV_FILE" "$WORK/config/env.production"

echo "== $(date '+%F %T') Sending to $RESTIC_REPOSITORY"
restic cat config >/dev/null 2>&1 || restic init
restic backup --tag nightly /backup
restic forget --prune --keep-daily "${KEEP_DAILY:-30}" --keep-monthly "${KEEP_MONTHLY:-12}"
if [ "$(date +%u)" = "7" ] || [ "${CHECK:-}" = "1" ]; then
  echo "== $(date '+%F %T') Weekly check of the backup storage"
  restic check --read-data-subset=5%
fi

date '+%F %T' > "$WORK/last-success"
ping_monitor ""
echo "== $(date '+%F %T') Backup finished."
