#!/usr/bin/env bash
# Creates the server's environment file with new random secrets (P1-10). Run once per server:
#   deploy/scripts/make-env.sh production erp.smlengineers.lk it@smlengineers.lk
#   deploy/scripts/make-env.sh test erp-test.smlengineers.lk it@smlengineers.lk
# The file is written to /srv/sml-erp/.env.production (or $ENV_FILE), readable by the
# deploy user only. It is never committed. It is never overwritten: losing it would make
# encrypted data (two-factor secrets, mailbox password) unreadable, so keep a copy safe
# (docs/hosting.md, step 5).
set -euo pipefail

ENVIRONMENT="${1:?Usage: make-env.sh production|test <domain> <email for certificate notices>}"
DOMAIN="${2:?Give the domain, e.g. smlerp.com.lk or test.smlerp.com.lk}"
CERT_EMAIL="${3:?Give an email address for certificate notices}"
ENV_FILE="${ENV_FILE:-/srv/sml-erp/.env.production}"

case "$ENVIRONMENT" in production|test) ;; *) echo "Environment must be production or test"; exit 1;; esac
if [ -e "$ENV_FILE" ]; then
  echo "$ENV_FILE already exists; it is never overwritten. Edit it by hand if needed."
  exit 1
fi

random() { openssl rand -hex "$1"; }
fernet_key() { openssl rand -base64 32 | tr '+/' '-_'; }
issuer="SML ERP"
[ "$ENVIRONMENT" = "test" ] && issuer="SML ERP (test)"
db_password="$(random 24)"

umask 077
mkdir -p "$(dirname "$ENV_FILE")"
cat > "$ENV_FILE" <<ENV
# SML ERP $ENVIRONMENT server. Created $(date -u +%Y-%m-%dT%H:%MZ) by deploy/scripts/make-env.sh.
# SECRET: readable by the deploy user only. Keep a copy in a safe place (docs/hosting.md).
APP_ENVIRONMENT=$ENVIRONMENT
DOMAIN=$DOMAIN
LETSENCRYPT_EMAIL=$CERT_EMAIL

DJANGO_SECRET_KEY=$(random 50)
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=$DOMAIN,localhost
DJANGO_CSRF_TRUSTED_ORIGINS=https://$DOMAIN
FIELD_ENCRYPTION_KEY=$(fernet_key)
TOTP_ISSUER=$issuer
SESSION_IDLE_MINUTES=30
SESSION_ABSOLUTE_HOURS=12
USE_X_FORWARDED_FOR=true
LOG_LEVEL=INFO
GUNICORN_WORKERS=3

POSTGRES_DB=sml_erp
POSTGRES_USER=sml
POSTGRES_PASSWORD=$db_password
DATABASE_URL=postgres://sml:$db_password@db:5432/sml_erp

REDIS_URL=redis://redis:6379/0

S3_ENDPOINT_URL=http://storage:8333
S3_ACCESS_KEY=sml-$(random 8)
S3_SECRET_KEY=$(random 24)
S3_BUCKET=sml-erp

# Notification emails (approvals, reminders). Fill in the company mailbox's SMTP details
# (docs/hosting.md, step 8), then run deploy.sh again. Documents and reports are sent from
# the mailbox set in the ERP itself (Settings > Document email).
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=true
DEFAULT_FROM_EMAIL=SML ERP <no-reply@$DOMAIN>
APP_URL=https://$DOMAIN
ENV
echo "Created $ENV_FILE ($ENVIRONMENT, https://$DOMAIN)."
