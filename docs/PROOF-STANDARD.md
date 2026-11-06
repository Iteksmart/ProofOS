# Proof Standard — What / When / Where / Why / Who

Every mutation in ProofOS emits one proof record. No proof → no 200.

## Schema

```json
{
  "what": "ticket.created | device.inventory | script.ran | automation.applied | auth.login | ...",
  "when": "2026-11-06T12:00:00Z  (server UTC, monotonic seq per actor)",
  "where": { "org_id": "...", "device_id": "...", "site": "...", "ip": "10.0.0.1" },
  "why": { "reason": "User requested patch", "ticket_id": "...", "change_id": "..." },
  "who": { "actor_id": "...", "actor_type": "user|agent|ai|system", "email": "...", "role": "..." },
  "payload_digest": "sha256:<hex  (of canonical payload)>",
  "canonical_bytes": "<base64url of canonical JSON>",
  "prev_hash": "<hex of previous record>",
  "signature": "<ed25519 sig>",
  "signing_key_id": "self-attested (embedded) — not pinned (say so in UI)"
}
```

## Rules (from D-011 / D-012)

1. **Canonical bytes recompute** — `canonical_bytes` must hash to `payload_digest` on verify. Any enrichment goes in a **sidecar** (`proof_id → source`), never in the body.
2. **Distinguish failed vs not checked** — missing `cryptography` → `signature_valid: null` + note, never `false`.
3. **Two ledgers, never merged** — archive vs live. Genesis states the gap plainly: `"no receipts backfilled or reconstructed for the gap period ever"`.
4. **Verify is a verb** — `GET /v1/verify/{id}` recomputes canonical bytes, checks SHA-256, verifies Ed25519. The UI's VERIFY button calls it.

## Coverage claim (D-013 pattern)

Measured, conservative. Example: `157,316 signed proof records · 111,897 signature-verified (Ed25519) · 0 invalid`. No "Bitcoin-anchored" without an attached OpenTimestamps proof. No "independently verifiable" without qualification (self-attested key).

## Audit query

```http
GET /v1/proofs?org_id=acme&what=script.ran&since=2026-11-01
GET /v1/verify/{id}   → { verified: true, checks: { hash_matches_canonical, canonical_recomputes, signature_valid } }
```
