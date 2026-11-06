from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import Audit, AuditFinding, Org
from app.schemas.schemas import AuditFindingOut, AuditOut, AuditRunOut
from app.services.audit import create_audit
from app.services.report import build_audit_pdf

router = APIRouter()


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id:
        raise HTTPException(status_code=403, detail="org scope mismatch")


def _findings(db: Session, audit_id: int) -> list[AuditFinding]:
    return db.query(AuditFinding).filter(AuditFinding.audit_id == audit_id).order_by(AuditFinding.id.asc()).all()


def _ai_summary(db: Session, org_id: int, findings: list[AuditFinding]) -> str | None:
    try:
        from app.services.llm import get_llm_client

        client = get_llm_client()
        if client and client.is_configured():
            titles = [f.title for f in findings[:10]]
            return client.chat(
                [{"role": "user", "content": f"Write a 2-3 sentence executive summary of these audit findings for an IT client: {titles}"}]
            )
    except Exception:
        pass
    return None


@router.post("/run", response_model=AuditRunOut, status_code=201)
def run(db: Session = Depends(get_db), user=Depends(get_current_user), org_id: int = 0, kind: str = "full"):
    org_id = org_id or user.org_id
    _scope(user, org_id)
    if kind not in {"security", "compliance", "governance", "full"}:
        raise HTTPException(status_code=400, detail="kind must be security|compliance|governance|full")
    audit = create_audit(db, org_id, kind)
    findings = _findings(db, audit.id)
    emit(db, "audit.run", {"audit_id": audit.id, "kind": kind, "score": audit.score}, actor_of(user), {"org_id": org_id}, {"reason": "infrastructure audit"})
    return {"audit": audit, "findings": findings, "score": audit.score}


@router.get("", response_model=list[AuditOut])
def list_audits(org_id: int, limit: int = Query(100, le=500), db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    return db.query(Audit).filter(Audit.org_id == org_id).order_by(Audit.created_at.desc()).limit(limit).all()


@router.get("/{audit_id}")
def get_audit(audit_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    audit = db.query(Audit).filter(Audit.id == audit_id).first()
    if not audit:
        raise HTTPException(status_code=404, detail="audit not found")
    _scope(user, audit.org_id)
    return {"audit": audit, "findings": _findings(db, audit.id)}


@router.get("/{audit_id}/report.pdf")
def report_pdf(audit_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    audit = db.query(Audit).filter(Audit.id == audit_id).first()
    if not audit:
        raise HTTPException(status_code=404, detail="audit not found")
    _scope(user, audit.org_id)
    org = db.query(Org).filter(Org.id == audit.org_id).first()
    findings = _findings(db, audit.id)
    summary = _ai_summary(db, audit.org_id, findings) or audit.summary
    pdf = build_audit_pdf(audit, findings, org.name if org else "Unknown", summary)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="proofos-audit-{audit.id}.pdf"'},
    )
