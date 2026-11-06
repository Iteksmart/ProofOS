from __future__ import annotations

import base64
import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.pubsub import publish
from app.models.models import ProofRecord

settings = get_settings()

_emit_lock = threading.Lock()


def _dev_seed() -> bytes:
    return b"\x00" * 32


def _get_seed_bytes() -> bytes:
    seed_hex = settings.proof_key_seed_hex.strip()
    if seed_hex:
        raw = bytes.fromhex(seed_hex)
        if len(raw) < 32:
            # Pad/truncate deterministically
            raw = (raw + b"\x00" * 32)[:32]
        return raw[:32]
    return _dev_seed()


def get_signing_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(_get_seed_bytes())


def get_public_key() -> Ed25519PublicKey:
    return get_signing_key().public_key()


def public_key_hex() -> str:
    return get_public_key().public_bytes_raw().hex()


def canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def emit(
    db: Session,
    what: str,
    payload: dict,
    who: dict,
    where: dict,
    why: dict,
) -> ProofRecord:
    """Append a proof record. Blocks (raises) if signing/DB fails — never silent success."""
    with _emit_lock:
        now = _now()
        body = {
            "what": what,
            "when": now.isoformat(),
            "where": where or {},
            "why": why or {},
            "who": who or {},
            "payload": payload or {},
        }
        cb = canonical(body)
        digest = hashlib.sha256(cb).hexdigest()
        prev = db.query(ProofRecord).order_by(ProofRecord.created_at.desc()).first()
        prev_hash = prev.payload_digest if prev else "0" * 64
        rec_id = uuid.uuid4().hex[:32]
        priv = get_signing_key()
        signature = priv.sign(cb + prev_hash.encode())
        org_id: int | None = None
        raw_org = (where or {}).get("org_id")
        if raw_org is not None:
            try:
                org_id = int(raw_org)
            except (TypeError, ValueError):
                org_id = None
        rec = ProofRecord(
            id=rec_id,
            org_id=org_id,
            what=what,
            canonical_bytes=base64.urlsafe_b64encode(cb).decode(),
            payload_digest=digest,
            prev_hash=prev_hash,
            signature=base64.urlsafe_b64encode(signature).decode(),
            signing_key_id="ed25519:proofos-1",
            created_at=now,
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)
        publish({"type": "proof", "what": what, "org_id": org_id, "id": rec.id})
        return rec


def verify(rec: ProofRecord) -> dict:
    """Recompute hash + Ed25519. Never false-negative on verifier absence:
    missing cryptography/verifier returns signature_valid=None + note."""
    base = {"id": rec.id, "what": rec.what}
    try:
        cb = base64.urlsafe_b64decode(rec.canonical_bytes)
    except Exception:
        return {
            **base,
            "verified": False,
            "checks": {
                "hash_matches_canonical": False,
                "canonical_recomputes": False,
                "signature_valid": None,
                "note": "canonical bytes undecodable",
            },
            "trust": {"key_trust": "self-attested (embedded in receipt) - not pinned"},
        }
    digest = hashlib.sha256(cb).hexdigest()
    hash_ok = digest == rec.payload_digest
    sig_ok: bool | None
    note = None
    try:
        sig = base64.urlsafe_b64decode(rec.signature)
        pub = get_public_key()
        pub.verify(sig, cb + rec.prev_hash.encode())
        sig_ok = True
    except Exception:
        # Distinguish "crypto backend missing" from genuinely invalid sig.
        try:
            from cryptography import __version__  # noqa: F401

            sig_ok = False
        except Exception:
            sig_ok = None
            note = "verifier unavailable (cryptography missing) — signature not checked"
    checks: dict = {
        "hash_matches_canonical": hash_ok,
        "canonical_recomputes": hash_ok,
        "signature_valid": sig_ok,
    }
    if note:
        checks["note"] = note
    verified = bool(hash_ok and sig_ok is True)
    # Hash ok + verifier absent must NOT claim fully verified.
    return {
        **base,
        "verified": verified,
        "checks": checks,
        "trust": {
            "key_trust": "self-attested (embedded in receipt) - not pinned",
            "algorithm": "Ed25519",
            "signing_key_id": rec.signing_key_id,
        },
    }


def verify_chain(records: list[ProofRecord]) -> dict:
    """Verify hash linkage across an ordered chain (oldest → newest)."""
    ordered = sorted(records, key=lambda r: r.created_at)
    broken: list[str] = []
    for i, rec in enumerate(ordered):
        if i == 0:
            continue
        if rec.prev_hash != ordered[i - 1].payload_digest:
            broken.append(rec.id)
    return {
        "count": len(ordered),
        "chain_ok": len(broken) == 0,
        "broken_ids": broken,
    }


def decode_canonical(rec: ProofRecord) -> dict | None:
    try:
        return json.loads(base64.urlsafe_b64decode(rec.canonical_bytes))
    except Exception:
        return None
