from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import ProofRecord
from app.services import itechsmart

router = APIRouter()


@router.get("/status")
def status(user=Depends(get_current_user)):
    """Live health probe of all local iTechSmart UAIO services."""
    return itechsmart.probe()


@router.get("/tools")
def tools(user=Depends(get_current_user)):
    """List iTechSmart MCP tools (live)."""
    return itechsmart.mcp_tools()


@router.get("/chain")
def chain(user=Depends(get_current_user)):
    """Fetch the ProofLink Plus receipt chain (live)."""
    return itechsmart.chain()


@router.post("/mcp/call")
def mcp_call(body: dict, user=Depends(get_current_user)):
    """Invoke an iTechSmart MCP tool (requires ITECHSMART_API_KEY)."""
    tool = body.get("tool") or body.get("name")
    if not tool:
        raise HTTPException(status_code=400, detail="tool name required")
    return itechsmart.mcp_call(tool, body.get("arguments") or {})


@router.post("/seal")
def seal(body: dict, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Bridge: seal a ProofOS receipt on iTechSmart ProofLink Plus (needs ITECHSMART_API_KEY)."""
    rid = body.get("proof_id")
    if not rid:
        raise HTTPException(status_code=400, detail="proof_id required")
    rec = db.query(ProofRecord).filter(ProofRecord.id == rid).first()
    if not rec:
        raise HTTPException(status_code=404, detail="ProofOS receipt not found")
    if rec.org_id is not None and rec.org_id != user.org_id:
        raise HTTPException(status_code=403, detail="receipt not in your org")

    result = itechsmart.seal(
        {
            "category": "proofos",
            "actor": user.email,
            "subject": rec.what,
            "action": "seal",
            "outcome": "ok",
            "details": {"proofos_receipt_id": rec.id, "digest": rec.payload_digest},
            "human_input": True,
            "auto_resolved": False,
        }
    )
    emit(db, "itechsmart.sealed", {"proofos_receipt": rec.id, "result": result}, actor_of(user), {"org_id": rec.org_id}, {"reason": "ProofLink Plus seal"})
    return {"proofos_receipt": rec.id, "sealed": result.get("ok", True), "result": result}
