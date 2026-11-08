# Secure Workspace (Encrypted Enclave) — BYOD & Remote Work

A company-controlled, encrypted enclave installed on any Mac/PC where work apps,
files, network traffic and AI tools run locally under IT policy and DLP. Everything
outside the enclave stays private to the user — securing employees, contractors and
BYOD without VDI or full device management.

## How it works

```
Personal (private)                 |  Company enclave (encrypted + policy-bound)
  apps / files / network           |    work apps · files · network · AI tools
  (untouched, invisible to IT)     |    Fernet-encrypted at rest · DLP scanned · policy enforced
```

1. **Provision** — `POST /v1/enclaves` creates a workspace on a device and returns a
   one-time **enclave encryption key** (only the key id is stored server-side).
2. **Install** — the cross-platform agent (`apps/agent/enclave.py`) creates the
   encrypted workspace directory and applies the policy manifest.
3. **Enforce** — files in the enclave are encrypted at rest; DLP scans content on
   copy-out/write and reports `dlp_blocked` events; apps/network are governed by the
   allowlist policy; AI-tool use is governed and logged.
4. **Prove** — every provision, lifecycle change and DLP event is hash-chained
   (Ed25519) into the ProofOS ledger for audit.

## API

| Endpoint | Purpose |
|---|---|
| `POST /v1/enclaves` | Provision a workspace (returns one-time `enclave_key`) |
| `GET /v1/enclaves?org_id=` | List workspaces |
| `PATCH /v1/enclaves/{id}` | Suspend / resume / remove |
| `GET /v1/enclaves/policies?org_id=` / `POST …` | DLP/IT policies |
| `POST /v1/enclaves/scan` | DLP-scan content (no storage) |
| `POST /v1/enclaves/{id}/events` | Report a DLP/policy event (auto-escalates sensitive data to `critical`) |
| `GET /v1/enclaves/{id}/events` | List DLP events |

## Policy model

`EnclavePolicy`:
- `allowed_apps` / `blocked_apps` — app governance (JSON lists)
- `network_allowlist` — domains/CIDRs allowed for work traffic
- `dlp_rules` — DLP rule config
- `clipboard_enabled`, `watermark_enabled` — data-leak controls
- `ai_governed` — AI tool use inside the enclave is logged + human-approval gated

## DLP detection (server-side)

`services/dlp.py` detects and redacts (never stores the raw value): SSN, credit-card
numbers, AWS/Google API keys, private keys, and generic `secret=…` tokens.

## Honest boundary

Implemented (cross-platform, no admin privileges): encrypted-at-rest workspace, DLP
content scanning, policy management, event reporting, AI-tool governance, proof audit.

Requires OS-native helpers (documented, not pure Python): kernel-level app blocking
and network interception (macOS Network Extension, Windows WFP, Linux netfilter),
clipboard interception, and dynamic screen watermarking. These are the same hooks the
commercial enclave vendors (Island, Venn, Cato) use under the hood.
