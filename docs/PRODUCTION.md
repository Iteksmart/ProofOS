# Production runbook

ProofOS is designed to run multi-tenant in production. This doc is the checklist
for a hardened deployment. The API **fails closed** at startup if a required
production secret is missing or weak.

## 1. Secrets (fail-closed)

Create a `.env` with these values (all REQUIRED in production):

```ini
ENV=production

# Random >=32 chars, not a placeholder
JWT_SECRET=<openssl rand -hex 32>

# 64 hex chars (32 bytes) — the Ed25519 proof-signing key seed.
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
PROOF_SIGNING_SEED_HEX=<64 hex chars>

# Shared secret agents present as X-Agent-Token / Authorization: Bearer
AGENT_TOKEN=<openssl rand -hex 24>

# Disable unauthenticated first-run bootstrap after you have an admin
ALLOW_BOOTSTRAP=false

DATABASE_URL=postgresql+psycopg://proofos:<64-hex-character-password>@postgres:5432/proofos
POSTGRES_USER=proofos
POSTGRES_PASSWORD=<64-hex-character-password>
POSTGRES_DB=proofos
REDIS_URL=redis://redis:6379/0
CORS_ORIGINS=https://proofos.example.com
WEB_URL=https://proofos.example.com
# Leave empty for the same-origin web/API proxy in the production Compose stack.
VITE_API_URL=
# If Google SSO is enabled, register this exact URL in Google Cloud.
GOOGLE_REDIRECT_URI=https://proofos.example.com/v1/sso/google/callback
# Pin to a reviewed MeshCentral release tag or image digest before production.
MESHCENTRAL_IMAGE=<reviewed-image-tag-or-digest>
```

On startup the API runs `Settings.validate_production()` and refuses to serve if
`JWT_SECRET` is weak, `PROOF_SIGNING_SEED_HEX` is unset/short, or `AGENT_TOKEN`
is short or a placeholder. Production also rejects SQLite, weak PostgreSQL
passwords, wildcard or non-HTTPS browser origins, non-HTTPS `WEB_URL`, unsupported
JWT algorithms, incomplete Google OAuth credentials, and non-HTTPS Google callbacks.
The API docs and OpenAPI schemas for both API services are disabled in production.
This is intentional — no silent weak-secret deployment.
The standalone proof service also validates the signing seed and JWT secret and
requires a valid control-plane JWT on every proof data endpoint. Both services must
share the same JWT settings.
Use `infra/docker-compose.production.yml` with the base Compose file. It forces
production mode, requires the core secrets, and keeps bootstrap disabled by
default. The API will fail closed if the supplied secrets or URLs are weak.

## 2. First-run bootstrap

For the one-time first workspace only, temporarily set `PROOFOS_ALLOW_BOOTSTRAP=true`
in the shell running Compose. The production overlay otherwise forces bootstrap off:

```powershell
$env:PROOFOS_ALLOW_BOOTSTRAP = "true"
docker compose -f infra/docker-compose.yml -f infra/docker-compose.production.yml up -d --build
Remove-Item Env:PROOFOS_ALLOW_BOOTSTRAP
curl.exe -X POST https://proofos.example.com/v1/auth/bootstrap `
  -H "Content-Type: application/json" -d '{"name":"Your Org"}'
```

This creates a brand-new org plus `admin-<id>@proofos.dev` and returns a **random one-time
`initial_password`**. Existing workspace names are rejected and never return an admin token.
Sign in with the bootstrap token, set a private password in **Admin → My sign-in password**,
save the credentials securely, and keep `PROOFOS_ALLOW_BOOTSTRAP` unset before restarting. Subsequent
orgs/users are created through the authenticated `POST /v1/auth/orgs` and
`POST /v1/auth/users` (admin/manager).

## 3. Deploy

```powershell
docker compose -f infra/docker-compose.yml -f infra/docker-compose.production.yml config --quiet
docker compose -f infra/docker-compose.yml -f infra/docker-compose.production.yml up -d --build
# api :8000 · proof :8113 · web :5173 (nginx) · postgres :5432 · redis :6379
```

- The production overlay fails at configuration time if required secrets or the
  MeshCentral image pin are missing; the API/proof startup checks reject weak values.
- `postgres`/`redis` have healthchecks and live on a data-only network; the browser
  network contains only the web proxy and API. Core services restart automatically.
- The API, proof service, database, Redis, and MeshCentral ports bind to loopback
  by default. Put a TLS terminator on the host or explicitly bind only to a
  protected private interface.
- The API applies Alembic migrations before it serves traffic. The standalone
  proof service uses the ledger table managed by the API migrations and will fail
  startup if it is missing.
- The web image is a multi-stage build. Nginx serves static assets and proxies
  `/v1/*`, `/v1/ws/*`, and `/health` to the API. Keep `VITE_API_URL` empty so
  browser requests and WebSockets stay same-origin; this avoids baking a
  developer's `localhost` address into a public build.
- Configure the outer TLS proxy to route the full host to web port 5173, permit
  WebSocket upgrades, replace any client-supplied `X-Forwarded-For`, and set
  `X-Forwarded-For` / `X-Forwarded-Proto` itself. The API trusts only the web
  proxy's configured private IP (`PROOFOS_WEB_PROXY_IP`). Change the default
  Compose subnet/IP together if it conflicts with your network.
- Containers run as a non-root user with `HEALTHCHECK`s.

The web proxy exposes the database-aware API health at `https://proofos.example.com/health`.
The API sets `Strict-Transport-Security` only when `ENV=production`. MeshCentral's
web and agent ports are loopback-bound by default; publish the agent port only on
the protected interface required by your fleet and firewall it to expected agent traffic.

## 4. Operational notes

- **Multi-worker chain coordination** — the proof chain is serialized with a
  PostgreSQL transaction-level advisory lock (`pg_advisory_xact_lock`), so multiple
  API workers coordinate on the chain head safely. SQLite (dev) uses an in-process lock.
- **Proof records are org-scoped** — `GET /v1/proof`, `/chain`, and `/verify/{id}`
  are filtered to the caller's org.
- **Schema migrations** — API control-plane and standalone proof-ledger tables
  are versioned with Alembic. Local development and tests still use `create_all`;
  production refuses to start if the database revision is not at the app head.
  Before deploying an existing database that predates migration tracking, take a
  backup, inspect it, and run `python -m alembic stamp head` once from
  `services/api` with its production `DATABASE_URL`, then run
  `python -m alembic check`. Do not stamp if the schema differs from the checked-in
  baseline; reconcile it first.
- **Rate limiting** — login is limited to 10/min/IP in-process; front it with
  trusted proxy / shared Redis limits when scaling horizontally. The app ignores
  untrusted raw `X-Forwarded-For` values.
- **Password recovery** — configure `SMTP_HOST` and `SMTP_FROM`; authenticated SMTP
  also needs `SMTP_USER` and `SMTP_PASSWORD`. Reset links expire after 20 minutes
  and are single-use. Requests are rate-limited by client IP.
- **WebSocket tenant isolation** — live events are sent only to clients with the
  matching organization claim; events without an organization are dropped.
- **Backups** — back up Postgres (`pgdata`) and `omniroute-data` (if using the AI
  gateway profile).

## 5. What was hardened (v1 hardening pass)

- Fail-closed secret validation in production.
- Bootstrap gated off in production; org/user creation now requires auth + role.
- Per-device agent secrets (SHA-256, returned once at registration); `AGENT_TOKEN`
  is limited to legacy devices without a per-device secret.
- Proof records org-scoped (list/chain/verify/emit) + compliance export (`/v1/proof/export`) and report (`/v1/proof/report`).
- Alert delivery via Slack webhook, SMTP email, or generic webhook (`docs`).
- Security headers (`nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, CSP, Permissions-Policy, HSTS in prod).
- Login rate limiting.
- Password reset links are signed, short-lived, single-use, and sent through SMTP.
- Web: static production build served by nginx, non-root, healthchecks.
- Frontend: auto-logout on 401 + error boundary + component tests.
- Test coverage enforced (>=70%) in CI.

See `docs/SECURITY.md` for the full threat model and residual risks.
