# Web assets built with Vite, served by nginx with /api proxied to the api
# service. See deploy/compose/docker-compose.yml.

FROM node:22-slim AS build
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY apps/web .
RUN npm run build

FROM nginx:1.27-alpine
# Rendered by the image entrypoint with envsubst; only exported environment
# variables are substituted, so nginx runtime variables stay intact. The
# default matches Compose; the Helm chart overrides it with the api service
# name.
ENV API_UPSTREAM=api:8000
COPY deploy/docker/nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /web/dist /usr/share/nginx/html
