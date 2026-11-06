# Security model

## Threat model & mitigations

| Threat | Mitigation |
|---|---|
| Weak/absent secrets in production | `Settings.validate_production()` fails closed at startup. |
| Anonymous org/user creation | `POST /v1/auth/orgs` and `/users` require JWT; user creation is admin/manager-scoped. |
| Unauthenticated first-run backdoor | `bootstrap` gated off when `ENV=production` and `ALLOW_BOOTSTRAP=false`. |
| Agent endpoints open to anyone | `heartbeat`, `scripts/runs/pending`, `scripts/runs/{id}/complete` require `AGENT_TOKEN`. |
| Cross-tenant proof leakage | Proof records carry `org_id`; list/chain/verify are org-scoped. |
| Login brute-force | In-process sliding-window limiter (10/min/IP); scale via Redis. |
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

## Residual risks (honest)

1. **Agent auth** — per-device secrets (SHA-256, shown once) + `AGENT_TOKEN` fallback.
   Remaining: mTLS and secret rotation tooling.
2. **`localStorage` token storage** — vulnerable to XSS; mitigated by the nginx CSP +
   security headers. Remaining: `HttpOnly` cookie refresh flow.
3. **Script execution** — the agent runs scripts via the shell by design; gated by role
   checks + approvals, a **fail-closed kill switch** (`POST /v1/ops/kill-switch`,
   env `KILL_SWITCH=1` for immediate halt), and per-device secrets. Remaining:
   OS-level execution sandboxing and a signed-script policy.
4. **No database migrations** — `create_all` only creates missing tables; use Alembic
   for live-schema evolution.
5. **In-process rate limiter** — single-instance only; use Redis for multi-replica.

See `docs/PRODUCTION.md` for the deployment checklist.
