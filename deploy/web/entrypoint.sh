#!/bin/sh
# Writes the Nginx site for $DOMAIN and starts Nginx. Until Let's Encrypt has issued the
# certificate (deploy/scripts/get-certificate.sh), a temporary self-signed one is used so
# that Nginx can start and answer the Let's Encrypt check on port 80.
set -eu
: "${DOMAIN:?Set DOMAIN in the environment file}"

LIVE="/etc/letsencrypt/live/$DOMAIN"
if [ -f "$LIVE/fullchain.pem" ] && [ -f "$LIVE/privkey.pem" ]; then
  CERT="$LIVE/fullchain.pem"
  KEY="$LIVE/privkey.pem"
else
  mkdir -p /etc/nginx/selfsigned
  if [ ! -f /etc/nginx/selfsigned/cert.pem ]; then
    openssl req -x509 -nodes -newkey rsa:2048 -days 30 -subj "/CN=$DOMAIN" \
      -keyout /etc/nginx/selfsigned/key.pem -out /etc/nginx/selfsigned/cert.pem 2>/dev/null
  fi
  CERT=/etc/nginx/selfsigned/cert.pem
  KEY=/etc/nginx/selfsigned/key.pem
  echo "No Let's Encrypt certificate for $DOMAIN yet: using a temporary self-signed one."
fi
export DOMAIN CERT KEY
envsubst '${DOMAIN} ${CERT} ${KEY}' < /etc/nginx/sml/site.conf.template > /etc/nginx/conf.d/site.conf
cp /etc/nginx/sml/security-headers.conf /etc/nginx/conf.d/security-headers.inc

# Renewed certificates are picked up by reloading Nginx twice a day.
(while :; do sleep 12h; nginx -s reload; done) &

exec nginx -g 'daemon off;'
