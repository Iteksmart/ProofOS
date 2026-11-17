"""Independent RFC 3161 anchoring of the proof-chain head."""
from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import ProofAnchor
from app.services import anchoring

router = APIRouter()


def _out(db: Session, anchor: ProofAnchor, verify: bool = True) -> dict:
    out = {"id": anchor.id, "chain_head": anchor.chain_head, "last_record_id": anchor.last_record_id,
        "record_count": anchor.record_count, "imprint": anchor.imprint, "tsa_url": anchor.tsa_url,
        "gen_time": anchor.gen_time, "created_at": anchor.created_at}
    if verify:
        out["verification"] = anchoring.verify_anchor(db, anchor)
    return out


@router.get("")
def list_anchors(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = db.query(ProofAnchor).order_by(ProofAnchor.id.desc()).limit(50).all()
    return {"authorities": anchoring.tsa_urls(), "trusted_roots": sorted(anchoring.trusted_roots()),
        "anchors": [_out(db, a, verify=i < 10) for i, a in enumerate(rows)]}


@router.post("", status_code=201)
def anchor(db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")
    try:
        row = anchoring.anchor_now(db)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=409, detail="the ledger is empty")
    emit(db, "proof.anchor.requested", {"anchor_id": row.id, "chain_head": row.chain_head, "tsa_url": row.tsa_url},
        actor_of(user), {"org_id": user.org_id}, {"reason": "independent timestamp of the ledger head"})
    return _out(db, row)


@router.get("/{anchor_id}")
def get_anchor(anchor_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = db.get(ProofAnchor, anchor_id)
    if not row:
        raise HTTPException(status_code=404, detail="anchor not found")
    return _out(db, row)


@router.get("/{anchor_id}/token")
def download_token(anchor_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """The raw RFC 3161 token, checkable with `openssl ts -verify`."""
    row = db.get(ProofAnchor, anchor_id)
    if not row:
        raise HTTPException(status_code=404, detail="anchor not found")
    return Response(base64.b64decode(row.token), media_type="application/timestamp-reply",
        headers={"Content-Disposition": f'attachment; filename="proofos-anchor-{row.id}.tsr"'})
