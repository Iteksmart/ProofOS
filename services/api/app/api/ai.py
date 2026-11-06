from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import Approval, Ticket
from app.schemas.schemas import AiAsk, AiSummarise
from app.services.ai import answer_query, propose_action, summarise, triage_ticket

router = APIRouter()


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id:
        raise HTTPException(status_code=403, detail="org scope mismatch")


@router.post("/ask")
def ask(payload: AiAsk, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, payload.org_id)
    result = answer_query(db, payload.org_id, payload.query)
    emit(
        db,
        "ai.ask",
        {"query": payload.query[:200], "org_id": payload.org_id},
        actor_of(user),
        {"org_id": payload.org_id},
        {"reason": "copilot query"},
    )
    return {"query": payload.query, **result}


@router.post("/summarise")
def summarise_ep(payload: AiSummarise, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, payload.org_id)
    result = summarise(db, payload.org_id, payload.scope)
    emit(
        db,
        "ai.summarise",
        {"scope": payload.scope, "org_id": payload.org_id},
        actor_of(user),
        {"org_id": payload.org_id},
        {"reason": "copilot summarise"},
    )
    return result


@router.get("/triage/{ticket_id}")
def triage(ticket_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    t = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="ticket not found")
    _scope(user, t.org_id)
    return {"ticket_id": t.id, **triage_ticket(t)}


@router.post("/propose")
def propose(payload: AiAsk, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Propose a remediation action; creates a pending Approval for a human to approve."""
    _scope(user, payload.org_id)
    proposal = propose_action(db, payload.org_id, payload.query)
    if proposal.get("device_id") is None:
        return {"proposed": None, "reason": proposal.get("reason"), "requires_approval": False}

    approval = Approval(
        org_id=payload.org_id,
        requester_kind="ai",
        requester_id="ai",
        kind="command",
        description=proposal["reason"],
        target_type="device",
        target_id=proposal["device_id"],
        payload=json.dumps({"device_id": proposal["device_id"], "body": proposal["command"]}),
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    emit(
        db,
        "ai.proposed",
        {"query": payload.query[:200], "approval_id": approval.id, "action": proposal.get("action")},
        actor_of(user),
        {"org_id": payload.org_id},
        {"reason": "AI remediation proposal (awaiting human approval)"},
    )
    return {"proposed": proposal, "approval_id": approval.id, "status": "pending", "requires_approval": True}
