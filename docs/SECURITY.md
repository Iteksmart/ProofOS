# Security model

## Threat model & mitigations

| Threat | Mitigation |
|---|---|
| Weak/absent secrets in production | `Settings.validate_production()` fails closed at startup. |
| Accidental development configuration in production | The production Compose overlay forces `ENV=production`, requires core secrets, and keeps bootstrap off by default. |
| Database exposure to the web tier | Postgres and Redis use an internal data network; the browser network contains only the web proxy and API. |
| Spoofed client IP through proxy headers | Uvicorn trusts only the configured web proxy IP. The outer TLS proxy must replace caller-supplied `X-Forwarded-For` with the verified client address. |
| Anonymous org/user creation | `POST /v1/auth/orgs` and `/users` require JWT; user creation is admin/manager-scoped. |
| Unauthenticated first-run backdoor | Production defaults `ALLOW_BOOTSTRAP` to false; when enabled, bootstrap can only create a new workspace name and can never mint a token for an existing workspace. |
| Agent endpoints open to anyone | Agent requests require the matching per-device secret; the shared token is accepted only for legacy devices without a device secret. |
| Cross-tenant proof leakage | Proof records carry `org_id`; list/chain/verify are org-scoped. |
| Login brute-force | In-process sliding-window limiter (10/min/ASGI peer); raw forwarded headers are not trusted. Use a trusted proxy and shared limiter when scaling horizontally. |
| Cross-tenant WebSocket event leak | Every live event is filtered by the JWT organization claim; organization-less events are not sent to tenant feeds. |
| Clickjacking / MIME sniffing / referrer leak | Security headers (`X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, HSTS in prod). |
| XSS → token theft | JWT in `localStorage` is a tradeoff (see residual risks); CSP is applied via nginx (`apps/web/nginx.conf`). |

## Proof / ledger integrity

- Canonical JSON → SHA-256 → Ed25519; hash-chain via `prev_hash`.
- `verify` distinguishes `signature_valid: null` (verifier absent) from `false` (invalid).
- Signing key is **self-attested** (embedded in receipts) — not pinned to a CA/KMS.
  Roadmap: KMS-backed signing, key rotation + revocation, and external trust anchoring.
  Until then the verifier labels the key `self-attested (not pinned)` — do not market
  as "independently verified".
- **Two ledgers, one contract**: the control-plane ledger (`proof_records`, live API
  actions) and the standalone proof-service ledger (`proof_ledger_records`, the
  export/verification boundary) are separate stores that are never merged. Both use
  the same Ed25519 canonical-JSON → SHA-256 → hash-chain contract and share org
  identity; reconciliation is by `org_id` + `what`/`when`.
- The standalone proof service requires a control-plane JWT signed with the same
  `JWT_SECRET`/`JWT_ALGO` and filters receipts by the signed organization claim.
  Its organizations have independent chains, and PostgreSQL appends use a
  transaction-level advisory lock.

## Residual risks (honest)

1. **Agent auth** — per-device secrets (SHA-256, shown once); `AGENT_TOKEN` is only
   accepted for legacy devices with no per-device secret. Remaining: mTLS and fleet
   secret rotation tooling.
2. **`localStorage` token storage** — vulnerable to XSS; mitigated by the nginx CSP +
   security headers. Remaining: `HttpOnly` cookie refresh flow.
3. **Script execution** — the agent runs scripts via the shell by design; direct
   queueing is restricted to same-organization admins/managers and AI proposals require
   explicit approval. A **fail-closed kill switch** (`POST /v1/ops/kill-switch`,
   env `KILL_SWITCH=1` for immediate halt), and per-device secrets. Remaining:
   OS-level execution sandboxing and a signed-script policy.
4. **Existing-database adoption** — legacy databases need a reviewed one-time Alembic baseline stamp before versioned migrations can run. Follow the backup and schema-check procedure in `docs/PRODUCTION.md`.
5. **In-process rate limiter** — single-instance only; use a shared Redis-backed limiter or edge rate limiting for multi-replica deployments.
6. **Remote control ingress** — MeshCentral ports bind to loopback by default. If remote agents require a published agent port, expose only the required interface and firewall it to the intended fleet.
7. **Container image updates** — the production overlay requires a reviewed MeshCentral tag or digest. Update it on a planned cadence after reviewing vendor releases.

See `docs/PRODUCTION.md` for the deployment checklist.
