# Proof service

Standalone, extractable hash-chained ledger (canonical bytes + SHA-256 + Ed25519).
Owns its own `proof_ledger_records` table, so it never merges with the
control-plane's embedded ledger — two ledgers, never merged.

## Endpoints (port 8113)
- `GET /health`
- `GET /v1/proof` — list (newest first)
- `GET /v1/proof/verify/{id}` — recompute canonical bytes + SHA-256 + Ed25519
- `POST /v1/proof/emit` — append a proof record (service token)
- `GET /v1/proof/chain` — verify hash linkage across the ordered chain

## Run
```powershell
cd D:\proofos\services\proof
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --port 8113
```

## Test
```powershell
cd D:\proofos\services\proof
python -m pytest -q
```

## Rules
- Append-only, sidecar provenance, never mutate receipt bodies.
- Distinguish `signature_valid: null` (not checked) vs `false` (failed).
- Signing key is self-attested (embedded in receipt) — the UI must say so.
