# Base images are pinned by multi-arch index digest so amd64 and arm64 build natively (D-01).
FROM node:22-slim@sha256:e9f565d32859f0cbfb52125eafe8be39390f24dac302dc3cdf566e8ba3ab21ee AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build && sh nginx/check.sh

# Runs as the image's non-root nginx user (UID 101) and listens on 8080.
FROM nginxinc/nginx-unprivileged:1.28-alpine@sha256:7377697a821c131a924a7105fafbe7414db4e9fcc77a6f08f776f33f141ec3f8
LABEL com.incident-escape-room.managed="true"
COPY --from=build /src/dist /usr/share/nginx/html
# Our nginx.conf is the whole config; drop the stock site so nothing else can serve.
COPY --from=build /src/nginx/nginx.conf /etc/nginx/nginx.conf
RUN rm /etc/nginx/conf.d/default.conf
