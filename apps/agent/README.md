# Agent

Cross-platform RMM daemon (Python 3.12).

## What it does
- Inventory: hostname, OS, IP, CPU/disk/mem
- Heartbeat (default 15s interval): `POST /v1/devices/{id}/heartbeat`
- Poll `GET /v1/scripts/runs/pending?device_id=...` and run, stream output
- Proof emit on script run (What/When/Where/Why/Who)

## Run
```powershell
cd D:\proofos\apps\agent
python -m pip install -r requirements.txt
python agent.py --api http://localhost:8000 --device-id 1
```

Pass the one-time `device_secret` returned by device registration using
`--token <device_secret>`. New devices always require their own secret; the shared
`AGENT_TOKEN` is limited to legacy devices that do not yet have a per-device secret.

## Sellable alone
`apps/agent/` is a standalone unit: pair it with any ProofOS-compatible API (no monolith required).
