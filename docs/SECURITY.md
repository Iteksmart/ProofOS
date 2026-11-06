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
| XSS → token theft | JWT in `localStorage` is a tradeoff (see residual risks); CSP not yet applied to the SPA. |

## Proof / ledger integrity

- Canonical JSON → SHA-256 → Ed25519; hash-chain via `prev_hash`.
- `verify` distinguishes `signature_valid: null` (verifier absent) from `false` (invalid).
- Signing key is **self-attested** (embedded in receipts) — not pinned to a CA/KMS.
  The UI must say so; do not market as "independently verified".
- Two ledgers are never merged: the control-plane ledger (`proof_records`) and the
  standalone service ledger (`proof_ledger_records`) are separate tables.

## Residual risks (honest)

1. **Agent auth** — each device now has a per-device secret (`device_secret`, SHA-256
   stored, returned once at registration); `AGENT_TOKEN` remains a global
   bootstrap/ops fallback. Remaining: mTLS, and secret rotation tooling.
2. **`localStorage` token storage** — vulnerable to XSS; the SPA now ships a CSP via
   nginx and mitigates clickjacking/MIME-sniffing. Remaining: `HttpOnly` cookie refresh flow.
3. **Single-worker chain** — the in-process `prev_hash` lock assumes one API worker;
   move the chain head to Postgres before horizontal scaling.
4. **No database migrations** — `create_all` only creates missing tables; use Alembic
   for live-schema evolution.
5. **Script execution** — the RMM agent runs scripts via the shell by design; gate
   script creation/queueing with role checks + approvals (roadmap) and never expose
   the API without `AGENT_TOKEN`.
6. **In-process rate limiter** — single-instance only; use Redis for multi-replica.
7. **No CSP** on the SPA yet; add one before enabling third-party scripts.

See `docs/PRODUCTION.md` for the deployment checklist.
