from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models.models import Alert, Approval, Automation, AutomationRun, Device, RemediationOutcome, Script, ScriptRun, Ticket


def _matches(condition: str, context: dict) -> bool:
    if not condition or not condition.strip():
        return True
    try:
        cond = json.loads(condition)
    except Exception:
        return True
    field = cond.get("field")
    op = cond.get("op", "eq")
    expected = cond.get("value")
    if field is None:
        return True
    actual = context.get(field)
    if op == "eq":
        return actual == expected
    if op == "neq":
        return actual != expected
    if op == "in":
        values = expected if isinstance(expected, list) else [expected]
        return actual in values
    if op in {"gt", "lt"}:
        try:
            a, e = float(actual), float(expected)
        except (TypeError, ValueError):
            return False
        return a > e if op == "gt" else a < e
    return True


def _blast_radius(context: dict) -> int:
    if "device_id" in context and context["device_id"] is not None:
        return 1
    return len(context.get("device_ids", []) or [])


def _safe_path(blast: int) -> str:
    if blast <= 1:
        return "auto"
    if blast <= 5:
        return "semi"
    return "manual"


def simulate(db: Session, org_id: int, trigger: str, context: dict | None = None) -> list[dict]:
    """Dry-run (Digital Twin): what would fire, blast radius, and safe autonomy path."""
    context = context or {}
    autos = (
        db.query(Automation)
        .filter(Automation.org_id == org_id, Automation.enabled.is_(True), Automation.trigger == trigger)
        .all()
    )
    plan = []
    for a in autos:
        matched = _matches(a.condition, context)
        blast = _blast_radius(context)
        safe = _safe_path(blast)
        if a.action == "remediate":
            planned = (
                f"run script #{a.remediation_script_id} on device {context.get('device_id')} "
                f"(autonomy={a.autonomy})"
                if (a.remediation_script_id and context.get("device_id"))
                else "skipped: missing script/device"
            )
        else:
            planned = f"{a.action} (severity {'critical' if a.action == 'alert' else 'warning'})"
        plan.append(
            {
                "automation_id": a.id,
                "name": a.name,
                "trigger": trigger,
                "action": a.action,
                "autonomy": a.autonomy,
                "would_fire": matched,
                "blast_radius": blast,
                "safe_path": safe,
                "condition": a.condition or "",
                "remediation_script_id": a.remediation_script_id,
                "planned": planned if matched else "condition not met",
            }
        )
    return plan


def evaluate(db: Session, org_id: int, trigger: str, context: dict | None = None) -> list[AutomationRun]:
    """Run enabled automations. Remediation is routed by autonomy:
    manual → escalate to a ticket; semi → human Approval; auto → execute (recorded outcome).
    """
    context = context or {}
    autos = (
        db.query(Automation)
        .filter(Automation.org_id == org_id, Automation.enabled.is_(True), Automation.trigger == trigger)
        .all()
    )
    runs: list[AutomationRun] = []
    for a in autos:
        if not _matches(a.condition, context):
            run = AutomationRun(org_id=org_id, automation_id=a.id, trigger=trigger, result=f"skipped: condition not met")
            db.add(run)
            runs.append(run)
            continue

        if a.action == "remediate":
            device_id = context.get("device_id")
            device = db.query(Device).filter(Device.id == device_id, Device.org_id == org_id).first() if device_id else None
            script = db.query(Script).filter(Script.id == a.remediation_script_id, Script.org_id == org_id).first() if a.remediation_script_id else None
            if not (device and script):
                result = "remediation skipped: missing script_id or device_id"
            elif a.autonomy == "manual":
                db.add(
                    Ticket(
                        org_id=org_id,
                        title=f"Remediation needed: {a.name}",
                        body=f"Trigger {trigger} on device {device_id}",
                        priority="high",
                        severity="P2",
                    )
                )
                result = f"escalated to human (ticket created)"
            elif a.autonomy == "auto":
                db.add(ScriptRun(org_id=org_id, device_id=device_id, script_id=a.remediation_script_id, status="pending"))
                db.add(RemediationOutcome(org_id=org_id, action=a.name, script_id=a.remediation_script_id, device_id=device_id, success=None, note="auto-executed"))
                result = f"auto-executed script #{a.remediation_script_id} on device {device_id}"
            else:  # semi
                db.add(
                    Approval(
                        org_id=org_id,
                        requester_kind="automation",
                        requester_id=f"automation:{a.id}",
                        kind="script",
                        description=f"Remediation '{a.name}': run script #{a.remediation_script_id}",
                        target_type="device",
                        target_id=device_id,
                        payload=json.dumps({"script_id": a.remediation_script_id, "device_id": device_id}),
                    )
                )
                result = f"remediation pending human approval (script #{a.remediation_script_id}, device {device_id})"
        elif a.action in {"notify", "alert"}:
            sev = "warning" if a.action == "notify" else "critical"
            db.add(Alert(org_id=org_id, device_id=context.get("device_id"), kind=trigger, severity=sev, message=f"Automation '{a.name}' fired: {trigger} {context}"))
            result = f"trigger={trigger} action={a.action}"
        else:
            result = f"trigger={trigger} action={a.action}"

        run = AutomationRun(org_id=org_id, automation_id=a.id, trigger=trigger, result=result[:2000])
        db.add(run)
        runs.append(run)

    if runs:
        db.commit()
        for r in runs:
            db.refresh(r)
    return runs
