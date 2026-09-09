FROM node:24-alpine AS build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build
FROM caddy:2.11-alpine
COPY --from=build /frontend/build /srv
COPY deploy/Caddyfile /etc/caddy/Caddyfile
