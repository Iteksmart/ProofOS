# Architecture — ProofOS

## One reason this exists

Atera-class RMMs manage devices. ProofOS manages **evidence**: every inventory change, ticket, script run, and automation emits a hash-chained proof. Audits become a query, not a project.

## System topology

```
┌────────────────────────────────────────────────────────────────────────┐
│ apps/web (React)  Dashboard · Tickets · Devices · Monitoring · AI   │
└──────────────────────────────▲───────────────────────────────────┘
                               │ REST /v1/*
┌──────────────────────────────┴───────────────────────────────────┐
│ services/api (FastAPI)                                            │
│  auth · orgs · devices · agents · monitor · tickets · scripts    │
│  automation · integrations · AI copilot (MCP client)              │
└──────────────────┬───────────────────────────────┬────────────────┘
                   │ SQLAlchemy                   │ proof emit (Ed25519)
                   ▼                              ▼
           Postgres 15 (RMM state)       services/proof (ledger)
                                                └─ GET /v1/verify/{id}
                               ▲
┌──────────────────────────────┴───────────────────────────────────┐
│ apps/agent (daemon)  inventory · heartbeat · exec script · queue │
└───────────────────────────────────────────────────────────────────┘
        packages/mcp — Microsoft/Google/AWS/VMware/Fortinet/Cisco/…
        infra/ — docker-compose (api, web, postgres, redis, proof)
```

## Boundaries

- **Product / Service / Node autonomy (Must):** every domain has `routers/`, `models/`, `schemas/`, `services/` and can be extracted as its own FastAPI app. No cross-imports except via `core/` + HTTP.
- **Proof is append-only:** canonical JSON → SHA-256 → Ed25519. Sidecar provenance, never mutate receipt bodies (D-011 pattern).
- **AI never acts alone:** copilot suggests, human approves, proof records both.

## Data model (core)

- `orgs` — tenant, `users` (roles: admin/manager/engineer/auditor), `devices`, `agents` (device link, version, status)
- `tickets` (`what/when/where/why/who` + status/priority), `scripts` (versioned), `script_runs`, `automations` (triggers → actions)
- `proof_records` — hash-chain head, signing key id, category, actor, payload_digest, canonical_bytes
- `integrations` — vendor, scopes, token ref (never plaintext), MCP endpoint

## Proof standard (What/When/Where/Why/Who)

See `PROOF-STANDARD.md`. Every write path calls `core/proof.py: emit(...)` before returning 200.

## AI copilot (LLM backends)

The copilot (`/v1/ai/*`) has three modes selected by `AI_PROVIDER`:

- `heuristic` (default) — deterministic, offline, auditable rules.
- `openrouter` — routes LLM calls through [OpenRouter](https://openrouter.ai), a hosted
  OpenAI-compatible API with free-tier models (`OPENROUTER_MODEL`, e.g. `nvidia/nemotron-3-ultra-550b-a55b:free`).
- `omniroute` — routes LLM calls through [OmniRoute](https://github.com/cheaper-inference/OmniRoute),
  an OpenAI-compatible gateway at `OMNIROUTE_URL` (`http://localhost:20128` / compose
  `http://omniroute:20128`) using `model: auto`.

Any LLM failure falls back to the heuristic and records `fallback_reason`; the request
is still proof-logged. `/v1/ai/triage/{id}` stays deterministic in all modes (auditable).
See `docs/AI-BACKENDS.md`.

## Ports (local compose)

| Service | Port | Notes |
|---|---|---|
| api | 8000 | FastAPI, `/docs`, `/health`, `/v1/*` |
| web | 5173 | Vite dev; `4173` preview |
| postgres | 5432 | `proofos` DB |
| redis | 6379 | cache / queue |
| proof | 8113 | verify / chain (mirrors suite `:8113`) |

## Vendor integrations (MCP-first)

`packages/mcp/` exposes tools: `device.list`, `ticket.create`, `proof.verify`, `monitor.health` — plus per-vendor adapters in `packages/mcp/adapters/`. Each adapter is thin: translate MCP tool → vendor REST.

## Failure modes

- Agent offline > 5 min → device `stale`, monitor alert, automation skip (proof records skip).
- Proof sign fails → request blocks (no silent success). Verify returns `signature_valid: null` + note, never false-negative (D-012 pattern).
- DB down → `/health` 503 with `ok:false` and machine-readable reason (fix the `ok:true` + 503 bug from the start).
