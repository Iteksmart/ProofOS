"""Infrastructure audit engine — security / compliance / governance findings + score."""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.core.proof import verify_chain
from app.models.models import Alert, Automation, Audit, AuditFinding, Device, OnboardingStep, ProofRecord, Ticket, User

SEVERITY_PENALTY = {"critical": 20, "high": 10, "medium": 5, "low": 2, "info": 1}


class _Collector:
    def __init__(self) -> None:
        self.findings: list[dict] = []

    def add(self, category: str, severity: str, title: str, detail: str) -> None:
        self.findings.append({"category": category, "severity": severity, "title": title, "detail": detail})


def _score(findings: list[dict]) -> float:
    penalty = sum(SEVERITY_PENALTY.get(f["severity"], 1) for f in findings)
    return round(max(0.0, min(100.0, 100.0 - penalty)), 1)


def run_audit(db: Session, org_id: int, kind: str) -> tuple[list[dict], float]:
    kind = (kind or "full").lower()
    want = {"security", "compliance", "governance"} if kind == "full" else {kind}
    c = _Collector()

    devices = db.query(Device).filter(Device.org_id == org_id).all()
    tickets = db.query(Ticket).filter(Ticket.org_id == org_id).all()
    alerts = db.query(Alert).filter(Alert.org_id == org_id).all()
    users = db.query(User).filter(User.org_id == org_id).all()
    automations = db.query(Automation).filter(Automation.org_id == org_id).all()
    proofs = db.query(ProofRecord).filter(ProofRecord.org_id == org_id).order_by(ProofRecord.created_at.asc()).all()
    steps = db.query(OnboardingStep).filter(OnboardingStep.org_id == org_id).all()

    if "security" in want:
        offline = [d for d in devices if (d.status or "online") != "online"]
        if offline:
            c.add("security", "high", f"{len(offline)} device(s) offline", ", ".join(d.hostname for d in offline[:5]))
        no_agent = [d for d in devices if not d.agent_version]
        if no_agent:
            c.add("security", "low", f"{len(no_agent)} device(s) without an agent", "Install the ProofOS agent for full management.")
        unacked = [a for a in alerts if not a.acked and a.severity == "critical"]
        if unacked:
            c.add("security", "high", f"{len(unacked)} unacknowledged critical alert(s)", "Review and acknowledge in Monitor → Alerts.")
        if not devices:
            c.add("security", "info", "No devices registered", "Onboard endpoints to begin monitoring.")

    if "compliance" in want:
        now = dt.datetime.now(dt.timezone.utc)
        breached = [t for t in tickets if t.due_at and t.due_at < now and t.status not in {"closed", "cancelled"}]
        if breached:
            c.add("compliance", "high", f"{len(breached)} ticket(s) breached SLA", ", ".join(f"#{t.id} {t.title}" for t in breached[:5]))
        chain = verify_chain(proofs) if proofs else {"chain_ok": True, "count": 0}
        if not chain["chain_ok"]:
            c.add("compliance", "critical", "Proof hash-chain integrity broken", f"Broken links: {chain.get('broken_ids')}")
        if len(proofs) == 0:
            c.add("compliance", "info", "No proof records", "Writes emit proof automatically; none recorded yet.")
        c.add("compliance", "info", "Signing key is self-attested", "Receipts are verifiable; the key is embedded, not pinned to a CA/KMS.")

    if "governance" in want:
        admins = [u for u in users if u.role == "admin"]
        if not admins:
            c.add("governance", "critical", "No admin user", "Create at least one admin for the org.")
        auto_exec = [a for a in automations if a.enabled and a.action not in {"notify", "alert"}]
        if auto_exec:
            c.add("governance", "medium", f"{len(auto_exec)} automation(s) can change state without approval", "Route state-changing actions through the approvals queue.")
        if steps and not all(s.done for s in steps):
            pending = sum(1 for s in steps if not s.done)
            c.add("governance", "low", f"{pending} onboarding step(s) incomplete", "Complete the client onboarding checklist.")

    return c.findings, _score(c.findings)


def build_summary(kind: str, score: float, findings: list[dict]) -> str:
    by_cat: dict[str, int] = {}
    by_sev: dict[str, int] = {}
    for f in findings:
        by_cat[f["category"]] = by_cat.get(f["category"], 0) + 1
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
    top = [f["title"] for f in findings if f["severity"] in {"critical", "high"}][:5]
    lines = [
        f"ProofOS {kind} audit — overall score {score}/100.",
        f"{len(findings)} finding(s) across {', '.join(sorted(by_cat)) or 'none'}.",
        f"Severity: {', '.join(f'{k} {v}' for k, v in sorted(by_sev.items())) or 'none'}.",
    ]
    if top:
        lines.append("Top items: " + "; ".join(top) + ".")
    return " ".join(lines)


def create_audit(db: Session, org_id: int, kind: str) -> Audit:
    findings, score = run_audit(db, org_id, kind)
    audit = Audit(org_id=org_id, kind=kind, score=score, summary=build_summary(kind, score, findings))
    db.add(audit)
    db.commit()
    db.refresh(audit)
    for f in findings:
        db.add(AuditFinding(audit_id=audit.id, org_id=org_id, category=f["category"], severity=f["severity"], title=f["title"], detail=f["detail"]))
    db.commit()
    return audit
