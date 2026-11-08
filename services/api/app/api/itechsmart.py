from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, require_role
from app.models.models import ProofRecord
from app.services import itechsmart

router = APIRouter()


@router.get("/status")
def status(user=Depends(require_role("admin", "manager"))):
    """Live health probe of all local iTechSmart UAIO services."""
    return itechsmart.probe()


@router.get("/tools")
def tools(user=Depends(require_role("admin", "manager"))):
    """List iTechSmart MCP tools (live)."""
    try:
        return itechsmart.mcp_tools()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"iTechSmart MCP unreachable: {e}")


@router.get("/chain")
def chain(user=Depends(require_role("admin", "manager"))):
    """Fetch the ProofLink Plus receipt chain (live)."""
    try:
        return itechsmart.chain()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"ProofLink Plus unreachable: {e}")


@router.post("/mcp/call")
def mcp_call(body: dict, user=Depends(require_role("admin", "manager"))):
    """Invoke an iTechSmart MCP tool (requires ITECHSMART_API_KEY)."""
    tool = body.get("tool") or body.get("name")
    if not tool:
        raise HTTPException(status_code=400, detail="tool name required")
    return itechsmart.mcp_call(tool, body.get("arguments") or {})


@router.post("/seal")
def seal(body: dict, db: Session = Depends(get_db), user=Depends(require_role("admin", "manager"))):
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
