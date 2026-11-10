# iTechSmart ProofOS

**Global standard IT operating system** — RMM + monitoring + ticketing + remote automation + AI copilot + tamper-evident proof (What / When / Where / Why / Who) for seamless audits and compliance.

> Not another tool. A way of life for administrators, managers, engineers, and network/sys admins.

**Name:** ProofOS (iTechSmart ProofOS)
**Stack:** Python 3.14 FastAPI + SQLAlchemy + Postgres · React / Vite / Tailwind · Docker
**Root:** `D:\proofos\`

## Repo map

```
D:\proofos\
├── apps/
│   ├── web/          # React dashboards (Atera-style: devices, monitoring, tickets, automation, AI)
│   └── agent/        # Cross-platform RMM agent (inventory, heartbeat, scripts)
├── services/
│   ├── api/          # FastAPI control plane
│   └── proof/        # Hash-chained proof ledger (Ed25519, canonical bytes, verify endpoint)
├── packages/
│   ├── mcp/          # MCP server + adapters (Microsoft, Google, AWS, VMware, etc.)
│   └── ui/           # Shared React components, tokens, proof UI
├── infra/
│   └── docker-compose.yml
├── docs/
│   ├── ARCHITECTURE.md
│   ├── PROOF-STANDARD.md      # What/When/Where/Why/Who schema
│   ├── ROADMAP.md             # Full-parity milestones
│   ├── SETUP.md               # New coder runbook
│   └── CONTRIBUTING.md
└── README.md
```

## Design principles

1. **Every /product /service /node is a first-class API citizen** — can talk to siblings or be sold alone (REST + MCP).
2. **Every action proofs itself** — What/When/Where/Why/Who attached at write time, hash-chained, re-verifiable via `GET /v1/verify/{id}`.
3. **AI is embedded, not bolted on** — triage, summarise, remediate, answer from proof graph; human override always.
4. **Vendor-agnostic** — M365, Google, AWS, Azure, VMware, Fortinet, Cisco, Dell/HP/Lenovo, etc. via connectors + MCP.
5. **Documentation is code** — this file + `docs/` is the system a new agent/person/coder can run, fix, and ship from.

## Quick start (local)

```powershell
cd D:\proofos
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build
# API:       http://localhost:8000/docs
# Proof:     http://localhost:8113/docs
# Web:       http://localhost:5173
# OmniRoute: http://localhost:20128  (AI gateway — see docs/AI-BACKENDS.md)
# Agents:    see apps/agent/README.md
```

For production, use the hardened overlay and checklist in [docs/PRODUCTION.md](docs/PRODUCTION.md).

### Run without Docker (dev)
```powershell
cd D:\proofos\services\api
python -m pip install -r requirements.txt   # add requirements-dev.txt to run the tests
uvicorn app.main:app --reload --port 8000
# frontend: cd ..\..\apps\web && npm install && npm run dev
```

### Production
See `docs/PRODUCTION.md` (deploy checklist) and `docs/SECURITY.md` (threat model).

## Status

- [x] Monorepo scaffold
- [x] Control plane API (auth, orgs, devices + types + telemetry, tickets + SLA, scripts, automation + conditions, monitor checks + SNMP reachability)
- [x] Web dashboards (one-pane-of-glass overview + analytics with charts, dark/light themes, devices + command console, tickets + comments, monitor, scripts + runs, automations, proof, AI, admin)
- [x] AI-assisted, human-approved operations (AI propose → approvals queue → execution) + remote command via agent + WebSocket live sync
- [x] Audit & consulting (security/compliance/governance audit engine + scored findings + PDF reports, client onboarding checklists, consulting projects & profiles)
- [x] Enterprise ITSM/PAM/AIOps (CMDB, knowledge base, secrets vault, time tracking, change management, anomaly detection)
- [x] UAIO autonomy loop (severity P1–P4 auto-classification, manual/semi/auto routing, digital-twin simulation + blast radius, timestamp anchoring, remediation learning, A2A agent card)
- [x] Agent (inventory + heartbeat + run script + remote command, proof-logged exec)
- [x] Proof ledger + verify UI (embedded `/v1/proof` + standalone `services/proof` on `:8113`) + compliance export/report
- [x] AI copilot (MCP tools: device/ticket/proof/monitor/script/approval; LLM backends: heuristic | OpenRouter | OmniRoute — `docs/AI-BACKENDS.md`)
- [x] Vendor connectors (MCP adapters: Microsoft Graph, Google Workspace Admin Directory, AWS EC2, Azure Resource Manager, VMware vCenter) + MCP tool registry (`/v1/mcp/tools`)
- [x] CI + tests (backend pytest w/ coverage gate, frontend Vitest + Testing Library)
- [x] Production hardening (fail-closed secrets, agent auth, org-scoped proof, security headers, rate limiting, nginx web, non-root, healthchecks)
- [ ] SNMP OID polling · interactive PTY terminal · live vendor API calls — see roadmap

See `docs/ROADMAP.md` for the full-parity milestone list.
