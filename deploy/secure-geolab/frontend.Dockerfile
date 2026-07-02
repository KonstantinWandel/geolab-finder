FROM node:22-alpine AS build

WORKDIR /app

COPY frontend/package*.json /app/
RUN npm install

COPY frontend/index.html /app/index.html
COPY frontend/vite.config.js /app/vite.config.js
COPY frontend/src /app/src
COPY frontend/public /app/public

ARG VITE_API_URL=/api
ENV VITE_API_URL=${VITE_API_URL}

RUN npm run build

FROM caddy:2-alpine

COPY deploy/secure-geolab/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv

EXPOSE 8080
