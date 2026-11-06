# ProofOS — Production Operations Manual

**Version 1.0 · iTechSmart ProofOS**
A multi-tenant RMM / IT-operations platform with a cryptographic proof ledger, AI copilot, ITSM, PAM, PSA, AIOps, remote control, and SSO.

---

## Table of Contents

1. [Introduction & Architecture](#1-introduction--architecture)
2. [System Requirements](#2-system-requirements)
3. [Installation & Deployment](#3-installation--deployment)
4. [Configuration Reference](#4-configuration-reference)
5. [First Run & Bootstrap](#5-first-run--bootstrap)
6. [Multi-Tenancy & User Management](#6-multi-tenancy--user-management)
7. [Device Enrollment & Agent](#7-device-enrollment--agent)
8. [Feature Walkthroughs](#8-feature-walkthroughs)
9. [Integrations](#9-integrations)
10. [Single Sign-On (SSO)](#10-single-sign-on-sso)
11. [Remote Control & Virtualization](#11-remote-control--virtualization)
12. [Operations Runbook](#12-operations-runbook)
13. [Security Hardening](#13-security-hardening)
14. [Troubleshooting](#14-troubleshooting)
15. [API Reference](#15-api-reference)
16. [FAQ](#16-faq)

---

## 1. Introduction & Architecture

ProofOS consolidates RMM (remote monitoring & management), ITSM (ticketing, change, CMDB, knowledge), PAM (secrets vault), PSA (time tracking, consulting), and AIOps (anomaly detection, automation, AI copilot) into **one pane of glass**, with every action backed by a **tamper-evident Ed25519 hash-chain proof ledger**.

### Components

```
Browser (React UI)
   │  HTTPS
   ▼
nginx (static SPA + reverse proxy)
   │  /v1/*
   ▼
FastAPI control plane (:8000)  ──┬── Postgres (state)
   │                             ├── Redis (cache / pub-sub)
   │                             ├── Proof service (:8113, Ed25519 chain)
   │                             ├── Agents (on each endpoint: heartbeat, exec, VM)
   │                             ├── AI (OpenRouter / OmniRoute / heuristic)
   │                             ├── MCP server (tool registry + vendor adapters)
   │                             └── MeshCentral (optional, remote desktop)
   ▼
WebSocket /v1/ws/events (org-scoped live updates)
```

### Core loop: **Detect → Decide → Do → Prove**

1. **Detect** — agents heartbeat (inventory + CPU/disk/mem) → status sync marks devices online/stale/offline → monitoring checks (ping/port/HTTP/SNMP) raise alerts.
2. **Decide** — alerts/tickets auto-classified (P1–P4) → automations (trigger→condition→action) with autonomy routing (manual/semi/auto) + digital-twin simulation (blast radius + safe path).
3. **Do** — human-gated approvals → remediation/command runs through the agent.
4. **Prove** — every write emits a hash-chained Ed25519 receipt; verify/export/audit (CSV/JSON/PDF), with timestamp anchoring and iTechSmart ProofLink bridging.

### Multi-tenant model

- An **Org** is a tenant — fully isolated (all data is `org_id`-scoped, including WebSocket events).
- **Roles**: `admin`, `manager`, `engineer`, `auditor`, `viewer`.

---

## 2. System Requirements

| Tier | CPU | RAM | Disk | Notes |
|---|---|---|---|---|
| **Minimum** (dev / 1–5 clients) | 2 vCPU | 4 GB | 10 GB SSD | single Compose host |
| **Recommended** (production) | 4 vCPU | 8 GB | 50 GB SSD | + managed Postgres/Redis optional |
| **Agent** (per endpoint) | ~0.1 vCPU | ~40 MB | — | heartbeat + command exec |

**Images**: API ~250–350 MB · Web ~40–80 MB · Proof ~150 MB · Postgres 420 MB · Redis 61 MB · MeshCentral ~993 MB (optional).

---

## 3. Installation & Deployment

### 3.1 Prerequisites

- Docker Engine 24+ and Docker Compose v2
- A domain name and TLS certificate (recommended: Let's Encrypt)
- Ports: `80/443` (web), `8000` (API), `8113` (proof), `8096` (MeshCentral web), `44330` (MeshCentral agent)

### 3.2 Clone & configure

```powershell
git clone <your-repo> proofos
cd proofos
copy .env.example .env
```

Edit `.env` (see [Configuration Reference](#4-configuration-reference)).

### 3.3 Start the stack

```powershell
docker compose -f infra/docker-compose.yml up -d --build
```

Verify:

```powershell
curl http://localhost:8000/health
# {"ok":true,"status":"ok","platform":"ProofOS","version":"1.0.0","db":"ok"}
```

Open the web UI at `http://localhost:5173` (dev) or `https://<your-domain>` (production).

### 3.4 Production hardening (required before go-live)

1. Put **nginx** (or Caddy/Cloudflare) in front with TLS termination.
2. Set `ENV=production` (enables fail-closed validation — see §13).
3. Use **managed Postgres/Redis** or enable host volume persistence (already in Compose).
4. Set strong secrets: `JWT_SECRET`, `PROOF_SIGNING_SEED_HEX`, `VAULT_KEY`, `AGENT_TOKEN`.
5. Set `ALLOW_BOOTSTRAP=false` after creating your first org.
6. Back up Postgres + the proof chain (see §12).

---

## 4. Configuration Reference

All settings are read from environment variables (via `.env`).

### Core

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://…` | SQLAlchemy DB URL (or `sqlite:///./app.db`) |
| `REDIS_URL` | `redis://localhost:6379/0` | cache / pub-sub |
| `ENV` | `development` | `production` enables fail-closed checks |
| `JWT_SECRET` | — | **required**, ≥32 chars |
| `PROOF_SIGNING_SEED_HEX` | — | 64 hex chars, Ed25519 signing seed |
| `AGENT_TOKEN` | — | shared agent auth (optional; per-device secrets preferred) |
| `ALLOW_BOOTSTRAP` | `true` | allow first-run bootstrap (disable in prod) |
| `WEB_URL` | `http://localhost:5173` | SPA origin (SSO redirects) |
| `APM_ENABLED` | `false` | record request-trace spans |

### AI

| Variable | Default | Purpose |
|---|---|---|
| `AI_PROVIDER` | `heuristic` | `heuristic` · `omniroute` · `openrouter` |
| `OMNITROUTE_URL` / `OMNITROUTE_API_KEY` | — | OmniRoute gateway |
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | — | OpenRouter (free models) |

### Notifications

| Variable | Purpose |
|---|---|
| `SLACK_WEBHOOK_URL` | Slack alerts |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` / `SMTP_TO` | email alerts |
| `ALERT_WEBHOOK_URL` | generic webhook alerts |

### Security / Vault

| Variable | Purpose |
|---|---|
| `VAULT_KEY` | Fernet key for secrets vault (auto-derived from JWT_SECRET if unset) |

### Integrations

| Variable | Purpose |
|---|---|
| `ITECHSMART_MCP_URL` | iTechSmart MCP server (`http://127.0.0.1:3200`) |
| `ITECHSMART_API_KEY` | iTechSmart MCP key (`x-itechsmart-mcp-key` header) |
| `MESHCENTRAL_URL` | MeshCentral server (`https://localhost:8096`) |
| `VNC_PORT` | VNC launch port (5900) |
| `FCM_PROJECT_ID` / `FCM_SERVICE_ACCOUNT_JSON` | Firebase Cloud Messaging |

### SSO

| Variable | Purpose |
|---|---|
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` | Google OIDC |
| `SAML_ENTITY_ID` / `SAML_ACS_URL` / `SAML_IDP_METADATA_URL` | Okta/SAML |

---

## 5. First Run & Bootstrap

1. Open the web UI → the login screen shows **"Sign in"**, **"Sign in with Google"**, and the bootstrap hint.
2. Enter an **Org name** (e.g. `Acme Corp`) and click **Sign in**.
3. On first run, the app auto-bootstraps: creates the org + an admin user (`admin-<id>@proofos.dev`) and logs you in.
4. **Immediately**: change the admin password and email (Admin → Users), then set `ALLOW_BOOTSTRAP=false` in `.env` and restart.

> **API alternative**: `POST /v1/auth/bootstrap` `{"name": "Acme Corp"}` → returns `{org, user, access_token}`. Idempotent — safe to re-run.

---

## 6. Multi-Tenancy & User Management

### 6.1 Create additional orgs (tenants)

Each client = one Org. Via API:

```powershell
curl -X POST http://localhost:8000/v1/auth/orgs -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" -d '{"name":"Beta LLC"}'
```

### 6.2 Manage users

**Admin → Users** panel, or:

```powershell
# list
curl "http://localhost:8000/v1/auth/users?org_id=1" -H "Authorization: Bearer $JWT"
# create
curl -X POST http://localhost:8000/v1/auth/users -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" -d '{"org_id":1,"email":"eng@acme.com","password":"<strong>","role":"engineer"}'
```

Roles:
- **admin** — full control (users, approvals, secrets, SSO, VM control)
- **manager** — operations, approvals, VM control
- **engineer** — devices, tickets, scripts, monitoring
- **auditor** — read-only + audit
- **viewer** — read-only

> All routes are `org_id`-scoped: a user of Org 1 cannot see or touch Org 2 data.

---

## 7. Device Enrollment & Agent

### 7.1 Enroll a device (UI)

1. **Devices** → fill `hostname`, `os`, `ip`, select `device_type` → **Register**.
2. A one-time **enrollment secret** is shown (copy it now — it's shown once).

### 7.2 Install the agent

```powershell
python agent.py --api http://<proofos-host>:8000 --device-id <id> --token <device_secret>
```

The agent then:
- **Heartbeats** inventory + telemetry (CPU/disk/mem) periodically
- **Polls for commands** and executes them (shell/PowerShell)
- **Runs VM/hypervisor commands** (see §11)

### 7.3 Device states

Status is derived from `last_seen`:
- **online** — heartbeat < 180 s
- **stale** — 180–600 s
- **offline** — > 600 s (raises a critical alert)

### 7.4 Device types

`workstation`, `server`, `access_point`, `gateway`, `switch`, `node`.

### 7.5 Remote command

**Devices** → click a device → type a command → **Run**. Output appears in run history (proof-logged).

---

## 8. Feature Walkthroughs

### 8.1 Dashboard

- **Exec** view (KPIs: devices, tickets, proof records, alerts, approvals, audit score) and **Operations** view (device health, tickets by status, alerts, devices by type).
- **Quick actions**: Run audit, Add device, New ticket, Run checks.
- Live WebSocket updates (no refresh needed).

### 8.2 Devices

Register → search → filter by type → open detail (telemetry, last seen, rotate secret, delete) → **Refresh statuses**.

### 8.3 Tickets

1. **Tickets** → title + details + priority (auto-severity P1–P4 by SLA).
2. Click a ticket → **Status** transitions (open → in_progress → resolved → closed), add **Comments**.
3. SLA due/breach tracking with `due_at`.

### 8.4 Monitoring

1. **Monitor** → select device → kind (`ping`/`port`/`http`/`snmp`) → target + threshold → **Add check**.
2. **Run checks for all devices** → raises alerts on failure.
3. Alerts → **ACK**, and auto-delivered via Slack/email/webhook/FCM (see §9).

### 8.5 Scripts

1. **Scripts** → name + body + version → **Create script**.
2. Select a script + a device → **Run** → output in **Run history** (exit code, stdout).

### 8.6 Automations & Approvals

1. **Automations** → name, trigger, condition JSON, action, **autonomy** (`manual`/`semi`/`auto`), optional remediation script → **Create rule**.
2. **Simulate** → digital-twin preview: blast radius + safe path.
3. When triggered, routing follows autonomy:
   - `manual` → creates an **Approval** (human must approve/deny)
   - `semi` → executes but flags for review
   - `auto` → executes + logs
4. **Admin → Approvals** → **Approve** / **Deny** (every decision proof-logged).

### 8.7 Proof Ledger

- **Proof** view: list records, **Verify** (checks hash-chain integrity), **Export** (CSV/JSON), **Compliance report** (PDF).
- Optional **timestamp anchor** (local SHA-256 commitment) and **iTechSmart ProofLink** bridge (seal receipts).

### 8.8 AI Copilot

1. **AI Copilot** → type a question (e.g. "offline devices") → **Ask** → risk/triage answer over live state.
2. **Propose** a remediation → generates a human-gated approval.

### 8.9 Admin

- Approvals, Users (add/roles), Push notifications (Firebase FCM — register token + send test), Inventory by type.

### 8.10 CMDB

- **CMDB** → name + type + attributes JSON → **Add CI**. Configuration items: server, switch, application, service, database, network.

### 8.11 Knowledge Base

- **Knowledge** → title + body + category + tags → **Add article**. Search across title/body/tags.

### 8.12 Secrets Vault (PAM)

- **Vault** → name + value + category → **Store secret** (encrypted with Fernet at rest).
- **Reveal** decrypts and is **audit-logged** (proof receipt).

### 8.13 Change Management

- **Changes** → title + description + risk + impact + plan → **Create change**.
- Lifecycle: `draft` → **Submit** → **Approve** → implement → close.

### 8.14 Time Tracking (PSA)

- **Time** → minutes + notes + billable → **Log time**. Summary: total/billable hours.

### 8.15 Audits & PDF Reports

- **Audit** → kind (`security`/`compliance`/`governance`/`full`) → **Run audit** → scored findings → **Download PDF**.

### 8.16 Onboarding

- **Onboarding** → **Init checklist** → toggle steps as done (client onboarding walkthrough).

### 8.17 Consulting

- **Consulting** → save **Client profile** → create **Projects** (planning/active/on-hold/done).

### 8.18 Patches

- **Patches** → name + device + category + severity → **Register patch** → **Deploy** (runs `winget`/`apt`/`yum` via the agent).

### 8.19 VMs

- **VMs** → name + host + hypervisor (`hyper-v`/`libvirt`/`vmware`/`qemu`) → **Register VM** → **Start/Stop/Restart** (native hypervisor commands via the agent).

---

## 9. Integrations

### 9.1 iTechSmart (UAIO / ProofLink / MCP)

Configure `ITECHSMART_MCP_URL` + `ITECHSMART_API_KEY`, then:

- `GET /v1/itechsmart/status` — live UAIO health
- `GET /v1/itechsmart/tools` — 66 MCP tools
- `GET /v1/itechsmart/chain` — ProofLink Plus receipts
- `POST /v1/itechsmart/mcp/call` — invoke any tool (e.g. `query_uaio_status`)
- `POST /v1/itechsmart/seal` — seal a ProofOS receipt into ProofLink Plus

### 9.2 MCP (ProofOS as an MCP server)

- `GET /v1/mcp/tools` — registry of 25+ tools (`device.*`, `ticket.*`, `proof.verify`, `audit.run`, `vm.*`, `approval.*`, `itechsmart.mcp_call`, …)
- `GET /.well-known/agent.json` — A2A agent card for agent discovery.
- Connect Claude/Cursor/LangGraph/CrewAI to ProofOS as a tool.

### 9.3 Notifications

- **Slack**: set `SLACK_WEBHOOK_URL`.
- **Email**: set `SMTP_*`.
- **Generic webhook**: set `ALERT_WEBHOOK_URL`.
- **Firebase push**: set `FCM_*` and register device tokens (Admin → Push).

### 9.4 Metrics ingestion (Datadog/Prometheus/Grafana)

`POST /v1/integrations/metrics` — push custom metric points; they feed the anomaly detection.

---

## 10. Single Sign-On (SSO)

### 10.1 Google (OIDC)

1. Google Cloud Console → Credentials → **OAuth client ID (Web)**.
2. Redirect URI: `https://<host>/v1/sso/google/callback`.
3. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `WEB_URL`.
4. Ensure the user's Google email matches a ProofOS user → click **Sign in with Google**.

### 10.2 Okta / SAML 2.0

1. Okta → Applications → **Create App Integration → SAML 2.0**.
2. SSO URL: `https://<host>/v1/sso/acs`; Audience URI: `https://<host>/sp`.
3. Add `email` attribute → `user.email`, Name ID = EmailAddress.
4. Copy the **IdP metadata URL** → set `SAML_IDP_METADATA_URL`.
5. `GET /v1/sso/sp-metadata` returns ProofOS's SP metadata for Okta.

Full steps: `docs/OKTA.md`.

---

## 11. Remote Control & Virtualization

### 11.1 MeshCentral (open-source remote desktop)

MeshCentral ships in the Compose stack (port `8096`). To activate:

1. Open `https://<host>:8096` → create the first account (becomes admin).
2. In MeshCentral → **Add Agent** → install on each endpoint.
3. ProofOS **Devices → Open KVM (VNC)** returns a connect link (or use the MeshCentral deep-link).

### 11.2 VNC (Linux)

- **Devices → Open KVM (VNC)** queues `x11vnc` on the agent and returns `vnc://<ip>:5900`.

### 11.3 Hypervisors

VM control commands are generated per hypervisor and run through the agent:
- **Hyper-V**: `Start-VM` / `Stop-VM` / `Restart-VM`
- **libvirt/QEMU**: `virsh start|shutdown|reboot`
- **VMware**: `vim-cmd vmsvc/power.on|off|reboot`

---

## 12. Operations Runbook

### 12.1 Backup

- **Postgres**: `pg_dump` (or your managed provider's backups).
- **Proof chain**: the `proof_records` table (in Postgres) + export via `/v1/proof/export`.
- **Secrets vault**: encrypted at rest; back up `VAULT_KEY` separately (off-box, e.g. age-encrypted).

### 12.2 Monitoring the platform

- `GET /health` — liveness.
- `GET /v1/analytics/apm` — request latency (enable `APM_ENABLED=true`).
- Container healthchecks are defined in Compose.

### 12.3 Scaling

- **Vertical**: raise CPU/RAM (see §2).
- **Horizontal**: run multiple API workers behind a load balancer; use managed Postgres/Redis; move the proof-chain head to Postgres.

### 12.4 TLS

Terminate TLS at nginx/Caddy/Cloudflare. Keep `:8000`, `:8113`, `:8096` internal (not public).

---

## 13. Security Hardening

1. `ENV=production` — fails closed on missing critical secrets.
2. `ALLOW_BOOTSTRAP=false` after first org.
3. `AGENT_TOKEN` or per-device secrets (enforced) — no open heartbeat endpoint.
4. `VAULT_KEY` in an encrypted secrets manager, never in plaintext VCS.
5. Rate-limited login (sliding window) + security headers are enabled by default.
6. Rotate `JWT_SECRET` / `PROOF_SIGNING_SEED_HEX` only with a planned re-key (proof chain depends on the seed).
7. Restrict the public surface to `443` (web) only.

---

## 14. Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| `403 org scope mismatch` | Wrong `org_id` or role; use your own org id |
| `401 unauthorized` on iTechSmart seal | ProofLink Plus has separate auth; MCP key only covers MCP tools |
| Device stuck `offline` | Agent not heartbeating; check `agent.py` connectivity + token |
| Proof verify fails | Chain tampered or re-seeded; restore from backup |
| SQLite `bad parameter` (dev) | Use Postgres in production; SQLite pool fixed for concurrent reads |
| SSO login loops | Check `WEB_URL` + redirect URI match exactly |

Logs: `docker compose logs -f api web proof`.

---

## 15. API Reference

All routes are under `/v1/*`, JWT via `Authorization: Bearer <token>`. Interactive docs at `GET /docs` (Swagger).

| Prefix | Domain |
|---|---|
| `/v1/auth` | login, bootstrap, orgs, users, SSO |
| `/v1/devices` | enrollment, heartbeat, telemetry, commands |
| `/v1/tickets` | tickets + comments |
| `/v1/monitor` | checks, alerts, ack |
| `/v1/scripts` | scripts + runs |
| `/v1/automations` | rules + simulate |
| `/v1/approvals` | human-gated approvals |
| `/v1/ai` | ask, propose |
| `/v1/proof` | verify, export, report, anchor |
| `/v1/audits` | run + findings |
| `/v1/cmdb`, `/v1/knowledge`, `/v1/secrets` | CMDB / KB / vault |
| `/v1/changes`, `/v1/time` | change mgmt / time |
| `/v1/vms`, `/v1/remote`, `/v1/patches` | virtualization / remote / patches |
| `/v1/analytics` | anomalies, root-cause, APM |
| `/v1/integrations` | metrics ingestion |
| `/v1/itechsmart`, `/v1/mcp`, `/v1/push`, `/v1/sso` | integrations / MCP / push / SSO |
| `/v1/ws/events` | WebSocket (org-scoped) |

---

## 16. FAQ

**Q: One platform or many?** One — ProofOS replaces RMM + ticketing + PAM + PSA + AIOps + audit in a single multi-tenant pane.

**Q: How do I add a second client?** Create a new Org (tenant); its data and users are fully isolated.

**Q: Does the proof chain survive restarts?** Yes — records persist in Postgres; verify recomputes the chain.

**Q: Can I run the agent on Windows?** Yes — the agent runs Python; Windows devices use PowerShell for commands and Hyper-V for VM control.

**Q: Is the Bitcoin anchor on-chain?** The built-in anchor is a local SHA-256 commitment; on-chain anchoring is available via iTechSmart ProofLink Plus.

**Q: Where are passwords stored?** Passwords are bcrypt-hashed; vault secrets are Fernet-encrypted.

---

*ProofOS — secure by design, provable by default.*
