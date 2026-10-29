#!/usr/bin/env bash
# Creates the backup settings file /srv/sml-erp/backup.env (P1-11, docs/backups.md, step 2).
#   deploy/scripts/make-backup-env.sh s3:https://<endpoint>/<bucket>/<folder>
# The backup password is generated here. WRITE IT INTO YOUR PASSWORD MANAGER: without it the
# backups cannot be opened by anyone, including you. Fill in the storage key afterwards.
set -euo pipefail
REPOSITORY="${1:?Usage: make-backup-env.sh <where the backups go, e.g. s3:https://s3.eu-central-003.backblazeb2.com/sml-erp-backups/production>}"
BACKUP_ENV="${BACKUP_ENV:-/srv/sml-erp/backup.env}"
if [ -e "$BACKUP_ENV" ]; then
  echo "$BACKUP_ENV already exists; it is never overwritten."
  exit 1
fi
umask 077
mkdir -p "$(dirname "$BACKUP_ENV")"
cat > "$BACKUP_ENV" <<ENV
# SML ERP backups (deploy/scripts/backup.sh). SECRET: readable by the deploy user only.
RESTIC_REPOSITORY=$REPOSITORY
# The backup password. Keep a copy in your password manager: without it no backup can be read.
RESTIC_PASSWORD=$(openssl rand -hex 32)
# The storage provider's key for the bucket (Backblaze B2: an application key; Cloudflare R2:
# an API token's access key). Fill both in.
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
# Daily backups kept, and month-end ones kept on top of them.
KEEP_DAILY=30
KEEP_MONTHLY=12
# Optional: a monitoring address (e.g. https://hc-ping.com/<id> from healthchecks.io) that is
# called after each backup, so you are told by email if a night's backup did not happen.
HEALTHCHECK_URL=
ENV
echo "Created $BACKUP_ENV. Now:"
echo "  1. copy the RESTIC_PASSWORD line into your password manager;"
echo "  2. fill in AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY (nano $BACKUP_ENV);"
echo "  3. run deploy/scripts/backup.sh once to check it works."
