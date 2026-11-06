# Production runbook

ProofOS is designed to run multi-tenant in production. This doc is the checklist
for a hardened deployment. The API **fails closed** at startup if a required
production secret is missing or weak.

## 1. Secrets (fail-closed)

Create a `.env` with these values (all REQUIRED in production):

```ini
ENV=production

# Random >=32 chars, not "change-me*"
JWT_SECRET=<openssl rand -hex 32>

# 64 hex chars (32 bytes) — the Ed25519 proof-signing key seed.
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
PROOF_SIGNING_SEED_HEX=<64 hex chars>

# Shared secret agents present as X-Agent-Token / Authorization: Bearer
AGENT_TOKEN=<openssl rand -hex 24>

# Disable unauthenticated first-run bootstrap after you have an admin
ALLOW_BOOTSTRAP=false

DATABASE_URL=postgresql+psycopg://proofos:<strong-password>@postgres:5432/proofos
REDIS_URL=redis://redis:6379/0
CORS_ORIGINS=https://proofos.example.com
```

On startup the API runs `Settings.validate_production()` and refuses to serve if
`JWT_SECRET` is weak, `PROOF_SIGNING_SEED_HEX` is unset/short, or `AGENT_TOKEN`
is empty. This is intentional — no silent weak-secret deployment.

## 2. First-run bootstrap

With `ALLOW_BOOTSTRAP=true` and `ENV=production` (one-time only):

```powershell
curl -X POST https://proofos.example.com/v1/auth/bootstrap \
  -H "Content-Type: application/json" -d '{"name":"Your Org"}'
```

This creates the org plus `admin-<id>@proofos.dev / admin12345`. **Immediately
change the admin password** (create a new admin or rotate), then set
`ALLOW_BOOTSTRAP=false` and restart. Subsequent orgs/users are created through the
authenticated `POST /v1/auth/orgs` and `POST /v1/auth/users` (admin/manager).

## 3. Deploy

```powershell
docker compose -f infra/docker-compose.yml up -d --build
# api :8000 · proof :8113 · web :5173 (nginx) · postgres :5432 · redis :6379
```

- `postgres`/`redis` have healthchecks; `api`/`proof` wait for `service_healthy`.
- The web image is a multi-stage build: Vite produces static assets, served by
  nginx (`VITE_API_URL` is baked at build time via `build.args`).
- Containers run as a non-root user with `HEALTHCHECK`s.

Put it behind a TLS terminator (nginx/Caddy/ALB). The API sets
`Strict-Transport-Security` only when `ENV=production`.

## 4. Operational notes

- **Single API worker** — the proof chain uses an in-process lock + `prev_hash`
  from the latest row. Run one `uvicorn` worker per instance (or move the chain
  head to Postgres before scaling out). The ledger is still verifiable regardless.
- **Proof records are org-scoped** — `GET /v1/proof`, `/chain`, and `/verify/{id}`
  are filtered to the caller's org.
- **No migrations** — `create_all` on boot is an MVP convenience. Add Alembic
  before evolving the schema on a live database.
- **Rate limiting** — login is limited to 10/min/IP in-process; front it with
  Redis/NGINX limits when scaling horizontally.
- **Backups** — back up Postgres (`pgdata`) and `omniroute-data` (if using the AI
  gateway profile).

## 5. What was hardened (v1 hardening pass)

- Fail-closed secret validation in production.
- Bootstrap gated off in production; org/user creation now requires auth + role.
- Per-device agent secrets (SHA-256, returned once at registration) + global `AGENT_TOKEN` fallback.
- Proof records org-scoped (list/chain/verify/emit) + compliance export (`/v1/proof/export`) and report (`/v1/proof/report`).
- Alert delivery via Slack webhook, SMTP email, or generic webhook (`docs`).
- Security headers (`nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, CSP, Permissions-Policy, HSTS in prod).
- Login rate limiting.
- Web: static production build served by nginx, non-root, healthchecks.
- Frontend: auto-logout on 401 + error boundary + component tests.
- Test coverage enforced (>=70%) in CI.

See `docs/SECURITY.md` for the full threat model and residual risks.
