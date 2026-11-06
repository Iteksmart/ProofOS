# Proof service

Standalone, extractable hash-chained ledger (canonical bytes + SHA-256 + Ed25519).
Owns its own `proof_ledger_records` table, so it never merges with the
control-plane's embedded ledger — two ledgers, never merged.

## Endpoints (port 8113)
- `GET /health`
- `GET /v1/proof` — list the caller's organization receipts (newest first)
- `GET /v1/proof/verify/{id}` — verify a receipt belonging to the caller's organization
- `POST /v1/proof/emit` — append a receipt to the caller's organization chain
- `GET /v1/proof/chain` — verify the caller's organization chain

All `/v1/proof` routes require a ProofOS control-plane JWT in `Authorization: Bearer …`.
The service must use the same `JWT_SECRET` and `JWT_ALGO` as the control plane. The
organization is read from the signed token; caller-supplied organization IDs are ignored.
Production startup requires a strong JWT secret and an exact 32-byte Ed25519 seed.

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
