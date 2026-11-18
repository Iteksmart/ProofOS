# ProofOS execution tracker — road to 8/10

Single source of truth for the 24-week programme. Update the status and
evidence columns in the same commit as the work. A task is **Done** only when its
evidence exists (test, CI run, report, receipt, or document), not when code is
written.

**Status key:** ✅ Done · 🟡 In progress · ⬜ Not started · ⛔ Blocked (needs owner decision or access)
**Scope key:** **PO** = this repository (ProofOS) · **ITS** = iTechSmart suite / host (outside this repo) · **ORG** = company/business

Last updated: 2026-11-17

## Scoreboard

| Area | Start | Now | Target | Gate to claim the next point |
|---|:-:|:-:|:-:|---|
| Observability | 6 | 6 | 8 | All three OTLP signals into ClickHouse; Explore and dashboards working end to end |
| AI root-cause analysis | 6 | 6 | 8 | Fault benchmark of 50+ scenarios: top-1 ≥ 80%, top-3 ≥ 95%, median under 60 s |
| Autonomous remediation | 6 | 6 | 8 | Typed runbooks with mandatory verification; published auto-fix and rollback rates |
| Compliance evidence | 5 | 5 | 8 | Evidence packs exported; independent SOC 2 report issued (not just in progress) |
| Reliability and scale | 3 | 3 | 8 | Restore drill measured, HA failover tested, 10,000-agent load test published, 3+ design partners |

Scores move only when a gate's evidence is linked below.

## Gap assessment (2026-11-17)

The roadmap made several assumptions. Here is what the code shows.

| Assumption | Finding | Effect on plan |
|---|---|---|
| ~87 containers exposed on 0.0.0.0 | **ProofOS: none.** Every ProofOS container binds 127.0.0.1. **iTechSmart suite: 90 published 0.0.0.0 bindings** (60+ `suite-*` containers) on this host. | Exposure work is ITS-scope; needs owner go-ahead and the suite's compose files. |
| Secrets committed in source | **ProofOS: none found.** Production compose refuses to start without strong secrets. Dev compose falls back to `proofos` only for local dev. **ITS:** defaults remain in suite compose, ops-api, djuane-proxy, gitops seal file; SEAL_TOKEN was in smoke.ps1. | Rotation is ITS-scope. Add gitleaks to ProofOS CI to keep it clean. |
| Hard-coded compliance scores | **ProofOS: none.** Audit score is computed from findings. **ITS:** api-gateway serves fixed NIST 96 / HIPAA 100 / composite 92 and "SOC 2 Type II in progress"; the fix is on disk but not deployed. | ITS-scope: restart api-gateway; agree SOC 2 wording. |
| CI blocked | Workflow is complete (tests, migrations, audits, e2e) but GitHub Actions cannot run (account billing lock). No secret, container or config scanning, and no SBOM. | Add scanners to the workflow; run gates locally until billing is fixed. |
| Backups exist | **None** in ProofOS. No pg_dump, WAL archiving, offsite copy or restore test. | Build backup and verified-restore tooling (P1-05/06). |
| Telemetry store | OTLP HTTP **JSON only**, logs and traces only (no metrics), stored in Postgres with 7-day retention. No query language or dashboards. | Phase 2 as planned. |
| RCA | Dependency-graph probable-cause ranking exists (health and depth only). No change correlation, anomaly baselines or benchmark. | Phase 3 as planned; reuse the break-it simulator from ITS. |
| Remediation | Signed agent jobs, approvals, access grants, recovery probes, cancellation, kill switch exist. No typed runbook registry, risk tiers, canary rollout or mandatory verification. | Phase 3 builds on the signed agent. |
| Receipts | Ed25519 hash chain, RFC 3161 anchoring and ProofLink bridge exist. | Reuse in every workstream. |
| Push hub and rate limits | In-process (single API worker). | Move to Redis before HA (P4). |

**Is ProofOS a working application?** Yes. It is deployed locally (Docker: API, web, Postgres, Redis, proof service, MeshCentral), with source in this repository, 138 API tests, 14 agent tests and 18 end-to-end tests passing. Phase 1 here is production hardening, not finishing core architecture.

## Phase 1 — Secure and stabilise (weeks 1–4)

| ID | Task | Scope | Status | Evidence / notes |
|---|---|:-:|:-:|---|
| P1-01 | Inventory ProofOS services, ports and secrets | PO | ✅ | Gap assessment above |
| P1-02 | Inventory iTechSmart suite exposure (90 × 0.0.0.0) and move to loopback behind nginx/cloudflared | ITS | ⛔ | Needs owner go-ahead and access to the suite compose files |
| P1-03 | Rotate SEAL_TOKEN and remove default secrets in suite files | ITS | ⛔ | Owner action |
| P1-04 | Secret, container and config scanning plus SBOM in CI | PO | 🟡 | `security-scan` job added to `.github/workflows/ci.yml` (gitleaks full history, Trivy vuln/misconfig/secret, CycloneDX SBOM) and `.gitleaks.toml`. Cannot run until P1-10; the local secret scan passes |
| P1-05 | Backup tool: Postgres dump, ledger export, signing public key, SHA-256 manifest | PO | ✅ | `scripts/backup.py`; optional Fernet-encrypted archive, refuses an unencrypted offsite copy. First real backup 2026-11-18: 178 receipts, schema b4d6f8a1c3e5 |
| P1-06 | Verified restore drill into an isolated database: chain verifies, RTO recorded | PO | ✅ | `scripts/restore_check.py`: restores into a network-isolated throwaway Postgres 15, checks file hashes, schema, row counts, every receipt's hash, Ed25519 signature (key captured at backup time) and chain. **Measured: 8.9 s restore + verify**, also from an encrypted offsite copy (9.5 s). Tamper test: a re-hashed receipt with a fixed manifest is caught (signature and chain fail) |
| P1-07 | Offsite encrypted copy with retention lock | PO/ORG | 🟡 | 2026-11-18: B2 bucket `proofos-backups-itechsmart` (private, SSE-B2, Object Lock enabled). Write Only key `proofos-backup-writer` in rclone remote `b2proofos`. `scripts/offsite_backup.ps1` → `backup.py --encrypt-key --rclone-remote --keep-local 7`: first encrypted archives uploaded; restore drill on the uploaded archive passed (8.5 s). Scheduled task "ProofOS Offsite Backup" runs daily at 02:45 under the owner's account (only while signed in; catches up when available); test run exit 0. Encryption key at `%USERPROFILE%\.proofosackup-encryption.key` (owner + SYSTEM only). Still open: 30-day default retention on the bucket (Backblaze sign-in/Cloudflare check needs the owner), key copy in a password manager, replace the applicationKey that was exposed during setup, a Read Only key for drills straight from B2. Earlier note: Tooling ready (`backup.py --encrypt-key K --copy-to DIR`). Needs: a storage target with versioning and retention lock (e.g. S3 Object Lock, Backblaze B2, Azure immutable blob), a scheduled task, and the key stored apart from backups. PITR (WAL archiving) is still needed for RPO ≤ 1 h; nightly dumps give RPO ≤ 24 h |
| P1-08 | Deep self-check endpoint (DB, ledger integrity, anchor age, stuck jobs, ingestion) | PO | ✅ | `GET /v1/ops/selfcheck` (admin, manager, auditor): ledger chain and head signature, anchor age, stale and stuck jobs, connected agents, telemetry age, kill switch; `tests/test_selfcheck.py` covers chain tampering. Still needs an external monitor polling it (P1-12) |
| P1-09 | Run CI gates locally until GitHub billing is resolved | PO | ✅ | `scripts/ci_local.py`: 12 gates (secrets, migrations, API, proof, MCP, agent, agent build, web build, web unit, pip-audit, npm audit, e2e); JSON report per run. 2026-11-17: **all 12 passed** (139 API, 14 agent, 18 e2e) |
| P1-10 | Resolve GitHub Actions billing lock | ORG | ⛔ | Owner action |
| P1-11 | Remove hard-coded compliance scores from iTechSmart api-gateway (restart service) | ITS | ✅ | 2026-11-18: ops-api, api-gateway and djuane-ai restarted, all healthy; compliance summary now reports not_assessed with no certification claims. Docker Desktop restarted the same day: ops-api database connection restored. Suite tests after restart: smoke 14/14, closed loop 9/9, products 19/20 (CMDB has no authentication). 2026-11-18 (later): remaining fixed scores removed: MCP server `query_uaio_status` (rebuilt, now "not assessed" / "not authorized"), gateway Probo fallback, and the HIPAA evidence pack (was "100/100" and padded with 50 unrelated receipts; now "not assessed", only matching receipts). Remaining copies only in archived/extracted folders and an offline PDF generator. |
| P1-12 | Bring verify.itechsmart.dev back from 502; add an external uptime monitor and status page | ITS | 🟡 | Back up 2026-11-18 (Docker Desktop port forwarding). Published-client compatibility restored the same day: `/api/receipts` (incl. `?hash=`), `/api/receipt/{id}`, `/api/verify/{id}`, `/api/chain`, `/api/stats`, `/api/export`, `/api/how-to-verify` added to `C:
ebuilderify-svc\main.py` (backup `main.py.bak-20261118`), served from the same ledger with full hash, canonical, Ed25519 and chain checks. Verified against the live site with the published, unmodified clients: conformance suite 185/185 conformant; PyPI `prooflink` 1.1.1 fetch/verify/verify_chain/stats OK; npm `@itechsmart/prooflink-verifier` 2.1.0 chain valid and receipt valid. Still open: external uptime monitor; public docs still claim 79,000+ receipts (live chain: 185); this PC's Windows certificate store rejects the valid Let's Encrypt chain for Python (local only; certifi works) |
| P1-13 | Signed release artifacts (agent and images) | PO | ⬜ | Agent build is reproducible; signing needs a key decision |
| P1-14 | Start design-partner recruiting (3–5 orgs) | ORG | ⬜ | Starts now, not in Phase 4 |
| P1-15 | Select SOC 2 auditor; readiness assessment | ORG | ⬜ | Starts now |

**Phase 1 exit gate:** external exposure fixed, secrets rotated, restore drill passed with measured RTO/RPO, CI green with scanners, unverified claims removed, independent monitoring live.

### Startup-budget route for blocked items (decided 2026-11-18)

| ID | Recommended route | Expected cost |
|---|---|---|
| P1-10 | Clear the account billing lock (Settings → Billing), then set the Actions spending limit to $0. ProofOS is a public repo, so standard GitHub-hosted runners cost nothing. Interim: `scripts/ci_local.py` | $0 (plus any overdue balance) |
| P1-07 | Backblaze B2 bucket with Object Lock (compliance mode, 30–90 day retention) + rclone, nightly Windows scheduled task; encryption key in a password manager plus an offline printed copy. Backups are under 1 MB, well inside the 10 GB free tier | $0 |
| P1-07b | Point-in-time recovery: WAL archiving + encrypted shipping to the same B2 bucket (`scripts/pitr.py`) | $0 (done 2026-11-18) |
| P1-02 | Bind iTechSmart suite containers to 127.0.0.1; expose only what must be public through Cloudflare Tunnel + Cloudflare Access (free for small teams); Windows Firewall blocks inbound as immediate containment | $0 |
| P1-03 | Rotate SEAL_TOKEN and default secrets; keep them in git-ignored .env files now, SOPS + age (open source) for secrets that must live in git | $0 |
| P1-11 | Restart ops-api, djuane-ai and api-gateway via the Host Services Watchdog task; re-run the three suites | $0 |
| P1-12 | Fix the origin behind verify.itechsmart.dev (Cloudflare 502 = origin/tunnel down). Monitoring: Uptime Kuma (open source) on an Oracle Cloud Always Free VM, so it is off this machine, with its status page | $0 |
| P1-13 | Sigstore cosign keyless signing in GitHub Actions for containers and the agent archive; Azure Artifact Signing Basic only when Windows binaries ship | $0 now; $9.99/month later |
| P1-14 | Design partners from the owner's network and MSP communities; free 90-day pilot in exchange for measured results and a reference | $0 |
| P1-15 | Self-host Probo (already in the iTechSmart stack) or Comp AI (open source) for policies and evidence; buy a SOC 2 Type I audit only when a design partner or deal requires it | $0 now; Type I audit typically $5k–$15k later |

## Phase 2 — Observability platform (weeks 4–12)

| ID | Task | Status |
|---|---|:-:|
| P2-01 | OTLP metrics ingestion (gauge, sum, histogram semantics) | ⬜ |
| P2-02 | OTLP HTTP/protobuf and gRPC, keeping HTTP/JSON | ⬜ |
| P2-03 | Tenant identity from credentials only; per-tenant quotas and backpressure | ⬜ |
| P2-04 | ClickHouse schemas (logs, spans, metrics, rollups, change events) with TTL | ⬜ |
| P2-05 | Dual-write, compare, feature-flag cutover | ⬜ |
| P2-06 | Constrained query language compiled to tenant-scoped parameterised SQL | ⬜ |
| P2-07 | Explore page with saved queries | ⬜ |
| P2-08 | Dashboards (six widget types) and auto service templates | ⬜ |
| P2-09 | Metric threshold alerts wired into alerts, SLOs and tickets | ⬜ |
| P2-10 | Synthetic HTTP/TCP probes from the agent (SSRF-safe) | ⬜ |
| P2-11 | Ingestion benchmark and cross-tenant adversarial tests | ⬜ |

## Phase 3 — Evidence-based AI RCA (weeks 8–16)

| ID | Task | Status |
|---|---|:-:|
| P3-01 | Unified incident timeline (deploys, config, patches, commands, anomalies) with receipt references | ⬜ |
| P3-02 | Seasonal anomaly baselines per service (error rate, p95, saturation) | ⬜ |
| P3-03 | Evidence-scored ranking with an "insufficient evidence" outcome | ⬜ |
| P3-04 | Multi-step investigation with citations and a time budget | ⬜ |
| P3-05 | Fault benchmark: 50+ scenarios, held-out set, published accuracy | ⬜ |

## Phase 3 — Safe remediation (weeks 8–18)

| ID | Task | Status |
|---|---|:-:|
| P3-10 | Typed, versioned runbook registry (batch A: 5 runbooks) | ⬜ |
| P3-11 | Risk tiers enforced by the policy engine; time-limited approval tokens; idempotency keys | ⬜ |
| P3-12 | Durable remediation state machine with canary-then-rollout | ⬜ |
| P3-13 | Mandatory verification per runbook; compensate or escalate on failure | ⬜ |
| P3-14 | Receipts for every transition | ⬜ |
| P3-15 | Promotion policy (recommend → approve → auto) | ⬜ |

## Phase 3–4 — Compliance evidence (weeks 8–24)

| ID | Task | Status |
|---|---|:-:|
| P3-20 | Canonical control library mapped to SOC 2 / ISO 27001 (professional review) | ⬜ |
| P3-21 | Evidence-pack export (PDF + JSON/CSV manifest + verification results) | ⬜ |
| P3-22 | Honest status model in the UI (not assessed → attested) | ⬜ |
| P3-23 | Company security programme with named owners | ⬜ |
| P3-24 | SOC 2 Type I fieldwork and report | ⬜ |

## Phase 4 — Reliability, scale, customers (weeks 12–24)

| ID | Task | Status |
|---|---|:-:|
| P4-01 | Move push hub and rate limits to Redis; multiple API replicas | ⬜ |
| P4-02 | Managed Postgres with tested failover; two zones | ⬜ |
| P4-03 | 10,000-agent load test (connected, reconnect storm, command burst) | ⬜ |
| P4-04 | Integrations wave 1: Slack/Teams, Jira, PagerDuty | ⬜ |
| P4-05 | Integrations wave 2: ServiceNow, Entra ID, Okta | ⬜ |
| P4-06 | Public status page and 99.9% SLO | ⬜ |
| P4-07 | Design-partner pilots with measured outcomes | ⬜ |

## Flagship demo (regression test and sales proof)

A bad deployment breaks checkout. OTel detects it, the incident correlates the deploy receipt, the AI ranks it with citations, a typed rollback runbook is approved, canaried, verified, rolled out, and the evidence pack exports. Build this as an automated end-to-end test as soon as Phase 3 pieces exist.

## Change log

- 2026-11-17: Tracker created; gap assessment done.
- 2026-11-18: Host inventory. 120 ports listen on all interfaces; inbound firewall "allow any port" rules for Python, Node, Docker Desktop and cloudflared on Private and Public profiles, so the whole LAN can reach them; Remote Desktop allowed on all profiles. verify.itechsmart.dev 502: nginx proxies to rebuild-verify on host 127.0.0.1:8113, but Docker Desktop's port forwarding is not serving several published ports (8113, 8004, 18610, 8096). (Correction: the ProofOS proof service never held host 8113. It is on an internal-only network, so its port line was never published; removed.) Watchdog and iTechSmart Backup scheduled tasks are disabled.
- 2026-11-18: Point-in-time recovery. Postgres archives WAL (`archive_timeout` 30 min) to backups/wal-archive; `scripts/pitr.py basebackup|ship|drill`. Nightly task now also takes an encrypted base backup and ships WAL to B2 (`proofos/base`, `proofos/wal`). PITR drill PASSED in 6.5 s: a marker written after the base backup was replayed, the restored ledger verifies (hash, Ed25519, chain) and matches live. RPO: about 30 min locally and under 1 hour offsite: scheduled task "ProofOS WAL Shipping" (`scripts/wal_ship.ps1`) ships every 15 minutes, indefinitely, under the owner's account.
- 2026-11-18: verify.itechsmart.dev `/api/*` compatibility routes added; the published verifier, SDK and conformance suite work again (185/185 conformant).
- 2026-11-18: iTechSmart cleanup. Legacy CMDB (:8095) now requires X-API-Key (fail closed; key in the suite's git-ignored .env); products suite 20/20. Host Services Watchdog re-enabled (runs as owner every 10 min; log rotation + disk guard); test run OK, 11/11 host services. Suite tests: closed loop 9/9, products 20/20, smoke 11/14 (test account hit ProofLink free-tier proof limit; not a regression). Findings: published ProofLink verifier/SDK/conformance call `/api/receipts`, `/api/receipt/{id}`, `/api/verify/{id}`, `/api/chain`, `/api/stats`, `/api/export`, which the live verify service does not serve (it exposes `/v1/...`); the original port-8300 public ledger exists only as a migration rehearsal copy, and the advertised 79,000-receipt chain is not on this host (local chain: 179). cmdb.itechsmart.dev DNS still points at the retired server (Cloudflare 522). Suite compose contains a hard-coded fallback Postgres password (add to P1-03 rotation). Firewall lockdown not yet applied.
- 2026-11-18: Docker Desktop restarted: published ports work again (5433, 8113, 8004, 18610); verify.itechsmart.dev answers publicly. MeshCentral reports no users yet, so the first account created becomes site administrator: create it now (it is loopback-only).
- 2026-11-18: Restarted the three host services. ops-api needs SEAL_TOKEN from the Windows user environment; a session started before that variable existed will not pass it, so start the supervisor with the user environment loaded (or via the scheduled task).
- 2026-11-18: P1-05, P1-06, P1-08 and P1-09 done; P1-04 added to CI (waiting on P1-10). Reliability stays 3: offsite storage, PITR and HA are still open.
