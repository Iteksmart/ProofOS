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

    # Plus only accepts categories prefixed article12_ / tenant_; scope by ProofOS org.
    result = itechsmart.seal(
        {
            "category": "tenant_proofos",
            "actor": user.email,
            "subject": str(rec.what)[:1900],
            "action": "seal",
            "outcome": "ok",
            "tenant_id": str(rec.org_id if rec.org_id is not None else user.org_id),
            "details": {"proofos_receipt_id": rec.id, "digest": rec.payload_digest},
        }
    )
    ok = bool(result.get("ok"))
    emit(db, "itechsmart.sealed" if ok else "itechsmart.seal_failed", {"proofos_receipt": rec.id, "result": result}, actor_of(user), {"org_id": rec.org_id}, {"reason": "ProofLink Plus seal"})
    if not ok:
        status = result.get("status") if isinstance(result.get("status"), int) and result.get("status") >= 400 else 502
        raise HTTPException(status_code=status, detail={"sealed": False, "proofos_receipt": rec.id, "error": result.get("error")})
    return {"proofos_receipt": rec.id, "sealed": True, "result": result}


from app.services import itsm_sync  # noqa: E402  (ITSM <-> ProofOS ticket bridge)


@router.post("/itsm/sync")
def itsm_sync_now(db: Session = Depends(get_db), user=Depends(require_role("admin", "manager"))):
    """Import/refresh ITSM tickets into this org's ProofOS tickets (each change emits a proof receipt)."""
    try:
        return itsm_sync.sync(db, user)
    except itsm_sync.ItsmError as e:
        raise HTTPException(status_code=e.status, detail=e.message)


@router.post("/itsm/push/{ticket_id}")
def itsm_push(ticket_id: int, db: Session = Depends(get_db), user=Depends(require_role("admin", "manager"))):
    """Create the ITSM ticket for a ProofOS ticket and link them (needs ITECHSMART_ITSM_TOKEN)."""
    try:
        return itsm_sync.push(db, user, ticket_id)
    except itsm_sync.ItsmError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
