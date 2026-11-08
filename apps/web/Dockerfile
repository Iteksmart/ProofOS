# ---- build stage ----
FROM node:22-alpine AS build
WORKDIR /app

# Workspace manifests first (cache-friendly, enables @proofos/ui resolution)
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
COPY apps/agent/package.json apps/agent/package.json
COPY services/proof/package.json services/proof/package.json
COPY packages/ui/package.json packages/ui/package.json
COPY packages/mcp/package.json packages/mcp/package.json

RUN npm install

COPY apps/web apps/web
COPY packages/ui packages/ui

ARG VITE_API_URL=
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build --workspace @proofos/web

# ---- serve stage ----
FROM nginx:1.27-alpine
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/apps/web/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1
