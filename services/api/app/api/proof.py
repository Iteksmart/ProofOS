from __future__ import annotations

import csv
import hashlib
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import decode_canonical, emit, verify, verify_chain
from app.core.security import actor_of, get_current_user
from app.models.models import ProofRecord
from app.schemas.schemas import ProofEmitIn, ProofOut, ProofVerifyOut

router = APIRouter()


@router.get("", response_model=list[ProofOut])
def list_proofs(limit: int = Query(100, le=500), db: Session = Depends(get_db), user=Depends(get_current_user)):
    # Org-scoped: a tenant can only see its own receipts.
    return db.query(ProofRecord).filter(ProofRecord.org_id == user.org_id).order_by(ProofRecord.created_at.desc()).limit(limit).all()


@router.get("/chain")
def chain(db: Session = Depends(get_db), user=Depends(get_current_user)):
    # The embedded ledger is one global chain. Verify its links using all
    # records, but return only counts and broken IDs belonging to this tenant.
    recs = db.query(ProofRecord).order_by(ProofRecord.created_at.asc()).limit(500).all()
    result = verify_chain(recs)
    own_ids = {rec.id for rec in recs if rec.org_id == user.org_id}
    result["count"] = len(own_ids)
    result["broken_ids"] = [rid for rid in result["broken_ids"] if rid in own_ids]
    return result


@router.get("/verify/{rid}", response_model=ProofVerifyOut)
def verify_proof(rid: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    rec = db.query(ProofRecord).filter(ProofRecord.id == rid).first()
    if not rec:
        raise HTTPException(status_code=404, detail="receipt not found")
    if rec.org_id is not None and rec.org_id != user.org_id:
        raise HTTPException(status_code=403, detail="receipt not in your org")
    return verify(rec)


@router.get("/export")
def export_proofs(fmt: str = "csv", db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Export org proof records for audit/compliance (SOC2/ISO evidence)."""
    recs = (
        db.query(ProofRecord)
        .filter(ProofRecord.org_id == user.org_id)
        .order_by(ProofRecord.created_at.asc())
        .all()
    )
    rows = []
    for r in recs:
        body = decode_canonical(r) or {}
        rows.append(
            {
                "id": r.id,
                "what": r.what,
                "when": body.get("when", ""),
                "who": json.dumps(body.get("who", {})),
                "where": json.dumps(body.get("where", {})),
                "why": json.dumps(body.get("why", {})),
                "payload_digest": r.payload_digest,
                "prev_hash": r.prev_hash,
                "signature": r.signature,
                "signing_key_id": r.signing_key_id,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
        )
    if fmt == "json":
        return {"count": len(rows), "records": rows}
    fieldnames = ["id", "what", "when", "who", "where", "why", "payload_digest", "prev_hash", "signature", "signing_key_id", "created_at"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(rows)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="proofos-proof-{user.org_id}.csv"'},
    )


@router.get("/report")
def compliance_report(db: Session = Depends(get_db), user=Depends(get_current_user)):
    recs = (
        db.query(ProofRecord)
        .filter(ProofRecord.org_id == user.org_id)
        .order_by(ProofRecord.created_at.asc())
        .all()
    )
    chain = verify_chain(recs)
    verified = invalid = unchecked = 0
    for r in recs:
        sig = verify(r)["checks"]["signature_valid"]
        if sig is True:
            verified += 1
        elif sig is False:
            invalid += 1
        else:
            unchecked += 1
    return {
        "org_id": user.org_id,
        "total_records": len(recs),
        "chain_ok": chain["chain_ok"],
        "signature_verified": verified,
        "signature_invalid": invalid,
        "signature_unchecked": unchecked,
        "key_trust": "self-attested (embedded in receipt) — not pinned to a CA/KMS",
        "note": "Verifiable self-attested hash chain. Independent verification requires pinning the signing public key.",
    }


@router.post("/anchor/{rid}")
def anchor_proof(rid: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Seal a receipt with an OpenTimestamps-style commitment (local; full Bitcoin submit is roadmap)."""
    rec = db.query(ProofRecord).filter(ProofRecord.id == rid).first()
    if not rec:
        raise HTTPException(status_code=404, detail="receipt not found")
    if rec.org_id is not None and rec.org_id != user.org_id:
        raise HTTPException(status_code=403, detail="receipt not in your org")
    if rec.anchored:
        return {"id": rec.id, "anchored": True, "commitment": rec.anchor_commitment}
    commitment = hashlib.sha256((rec.payload_digest + rec.signature).encode()).hexdigest()
    rec.anchored = True
    rec.anchor_commitment = commitment
    db.commit()
    db.refresh(rec)
    emit(db, "proof.anchored", {"id": rec.id, "commitment": commitment}, actor_of(user), {"org_id": rec.org_id}, {"reason": "timestamp anchor"})
    return {"id": rec.id, "anchored": True, "commitment": commitment}


@router.post("/emit", response_model=ProofOut, status_code=201)
def emit_proof(body: ProofEmitIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    where = dict(body.where or {})
    where.setdefault("org_id", user.org_id)
    return emit(
        db,
        body.what,
        body.payload,
        body.who or actor_of(user),
        where,
        body.why,
    )
