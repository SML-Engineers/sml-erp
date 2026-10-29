# Production web server: the built React app and the HTTPS front door (Nginx). Built from
# the repository root: docker compose -f deploy/docker-compose.prod.yml build web
FROM node:22-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine
RUN apk add --no-cache openssl \
    && rm -f /etc/nginx/conf.d/default.conf \
    && mkdir -p /var/www/certbot /etc/nginx/sml
COPY --from=build /app/dist /usr/share/nginx/html
COPY deploy/web/site.conf.template deploy/web/security-headers.conf /etc/nginx/sml/
COPY deploy/web/entrypoint.sh /sml-entrypoint.sh
RUN chmod +x /sml-entrypoint.sh
EXPOSE 80 443
ENTRYPOINT ["/sml-entrypoint.sh"]
