# Contributing

- **Claim before you start** (task list owner). One task = one verifiable outcome.
- **Proof first:** every write path emits a proof record. Never 200 without it.
- **Two ledgers, never merged.** Archive vs live stay separate (see `docs/PROOF-STANDARD.md`).
- **Failed vs not checked:** never report `signature_valid: false` when the verifier is missing — report `null` + note.
- **Docs are code:** update `ARCHITECTURE.md`/`ROADMAP.md` and journal entries with every behaviour change.
- **UI:** friendly, accessible, no dead buttons. Every button calls a real backend.
- **Secrets:** never commit `.env`, tokens, or `keys-decrypted/`. Rotate via `ROTATION-SWEEP.md` pattern.
