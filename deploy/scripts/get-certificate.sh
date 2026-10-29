#!/usr/bin/env bash
# Gets the Let's Encrypt HTTPS certificate for the first time (P1-10). Run once as the deploy
# user, after the domain points to this server (docs/hosting.md, step 7) and the ERP is
# running. Renewal is automatic (the certbot service).
set -euo pipefail
APP_DIR="${APP_DIR:-/srv/sml-erp/app}"
export ENV_FILE="${ENV_FILE:-/srv/sml-erp/.env.production}"
DOMAIN="$(grep '^DOMAIN=' "$ENV_FILE" | cut -d= -f2-)"
EMAIL="$(grep '^LETSENCRYPT_EMAIL=' "$ENV_FILE" | cut -d= -f2-)"
cd "$APP_DIR"
compose() { docker compose -f deploy/docker-compose.prod.yml --env-file "$ENV_FILE" "$@"; }

echo "== Asking Let's Encrypt for a certificate for $DOMAIN"
compose run --rm --entrypoint certbot certbot certonly --webroot -w /var/www/certbot \
  -d "$DOMAIN" --email "$EMAIL" --agree-tos --no-eff-email --non-interactive
echo "== Restarting the web server with the new certificate"
compose up -d --force-recreate web
echo "== Done: open https://$DOMAIN"
