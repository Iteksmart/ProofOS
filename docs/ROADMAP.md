# Roadmap — Full-parity pack

## M0 — Scaffold
- [x] Monorepo `D:\proofos\` (apps/web, apps/agent, services/api, services/proof, packages/mcp, packages/ui, infra/)
- [x] README, ARCHITECTURE, PROOF-STANDARD
- [x] Docker compose (api/proof/web/postgres/redis)
- [x] CI (`.github/workflows/ci.yml`) + `docs/CONTRIBUTING.md`

## M1 — RMM Core (Atera parity start)
- [x] Auth (JWT), orgs, roles (admin/manager/engineer/auditor)
- [x] Devices + agents (inventory, heartbeat, CPU/disk/mem, last-seen)
- [x] Dashboards: overview, device grid, detail — polished Tailwind, live sync
- [x] Proof emit on every write (What/When/Where/Why/Who)

## M2 — Monitoring + Tickets
- [x] Ping/port/HTTP checks, thresholds, alert timeline, webhook notify
- [x] Tickets (create/assign/SLA due dates), comments, AI summarise/triage
- [~] Notifications (generic webhook; email/Slack via their webhook adapters)

## M3 — Remote scripts + automation
- [x] Versioned scripts, run history + output (live WebSocket streaming pending)
- [x] Automation rules (trigger → condition → action) with create/edit
- [ ] Service accounts + remote terminal (WebSocket)

## M4 — Proof + AI + Integrations
- [x] Proof ledger service (hash-chain, Ed25519, `GET /v1/verify/{id}`, verify UI)
- [x] AI copilot (MCP tools: device/ticket/proof/monitor) with human approval
- [x] MCP adapters (M365, Google Workspace, AWS, Azure, VMware) + tool registry (`/v1/mcp/tools`)
- [ ] Compliance views (SOC2/ISO exports by proof query)

## M5 — Sellable units
- [x] `services/proof` extractable as its own FastAPI deployable (port 8113, own ledger table)
- [ ] Agent-only, proof-only, monitor-only SKUs (same APIs, different `infra/` profiles)
- [~] Public docs + OpenAPI (MCP registry done at `/v1/mcp/tools`)

## Production hardening (done)
- [x] Fail-closed secret validation (`JWT_SECRET`, `PROOF_SIGNING_SEED_HEX`, `AGENT_TOKEN`)
- [x] Bootstrap gated in production; org/user creation authenticated + role-scoped
- [x] Agent-token auth on heartbeat / script queue / complete
- [x] Org-scoped proof records (list/chain/verify/emit)
- [x] Security headers, login rate limiting
- [x] nginx static web, non-root containers, healthchecks
- [x] Frontend auto-logout on 401 + error boundary
- See `docs/PRODUCTION.md` and `docs/SECURITY.md`.

## Non-goals (explicit)
- No silent failures (no `ok:true` + 503).
- No merged ledgers. Two chains, explicit totals.
- No marketing numbers not measured (see `docs/PROOF-STANDARD.md`).
