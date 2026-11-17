"""Patch policies: approval rules, maintenance windows, grouped deployment and compliance."""
from __future__ import annotations

import base64
import datetime as dt
import json
import re

from sqlalchemy.orm import Session

from app.core.proof import emit
from app.models.models import Device, Patch, PatchPolicy, Script, ScriptRun
from app.services import kill_switch

SEVERITIES = ["critical", "important", "moderate", "low"]
CATEGORIES = ["os", "security", "third_party", "other"]
OPEN_STATUSES = ("pending", "failed")
AUTO_RUN_COOLDOWN = dt.timedelta(hours=6)

_PACKAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-]{0,127}$")
_KB = re.compile(r"\bKB(\d{5,8})\b", re.I)
_WINGET_ID = re.compile(r"\[([A-Za-z0-9][A-Za-z0-9._+\-]{0,127})\]\s*$")
_REBOOT_PENDING = r"HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending"

# Windows Update Agent (built into Windows): list or install missing software updates.
WINDOWS_UPDATE_SCAN = """$ErrorActionPreference = 'Continue'
try {
  $searcher = (New-Object -ComObject Microsoft.Update.Session).CreateUpdateSearcher()
  foreach ($u in $searcher.Search("IsInstalled=0 and Type='Software' and IsHidden=0").Updates) {
    $kb = ($u.KBArticleIDs | Select-Object -First 1)
    $cats = ($u.Categories | ForEach-Object { $_.Name }) -join ';'
    Write-Output ("WU|KB{0}|{1}|{2}|{3}" -f $kb, $u.MsrcSeverity, $cats, $u.Title)
  }
} catch { Write-Output ("WU-ERROR|" + $_.Exception.Message) }
winget upgrade --include-unknown --accept-source-agreements | Out-String -Width 400
"""
# Installs only the listed KBs; {kbs} is filled with validated KB numbers.
WINDOWS_UPDATE_INSTALL = """$approved = @({kbs})
$session = New-Object -ComObject Microsoft.Update.Session
$selected = New-Object -ComObject Microsoft.Update.UpdateColl
foreach ($u in $session.CreateUpdateSearcher().Search("IsInstalled=0 and Type='Software' and IsHidden=0").Updates) {
  if ($approved -contains ('KB' + ($u.KBArticleIDs | Select-Object -First 1))) { $null = $selected.Add($u) }
}
if ($selected.Count -gt 0) {
  $downloader = $session.CreateUpdateDownloader(); $downloader.Updates = $selected; $null = $downloader.Download()
  $installer = $session.CreateUpdateInstaller(); $installer.Updates = $selected; $result = $installer.Install()
  Write-Output ("Windows Update installed {0} update(s); result code {1}; reboot required: {2}" -f $selected.Count, $result.ResultCode, $result.RebootRequired)
  if ($result.ResultCode -ne 2) { exit 1 }
} else { Write-Output 'None of the approved Windows updates are still pending.' }
"""


def targets(device: Device, patch: Patch) -> tuple[str, str] | None:
    """The exact identifier to install for one patch, or None when it cannot be targeted safely."""
    if (device.os or "").lower().startswith("windows"):
        kb = _KB.search(f"{patch.available_version} {patch.name}")
        if kb:
            return ("kb", f"KB{kb.group(1)}")
        winget = _WINGET_ID.search(patch.name or "")
        return ("winget", winget.group(1)) if winget else None
    return ("package", patch.name) if _PACKAGE.match(patch.name or "") else None


def encoded_powershell(script: str) -> str:
    """-EncodedCommand avoids every quoting problem of nested shells."""
    return "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand " + base64.b64encode(script.encode("utf-16-le")).decode()


def loads(raw: str | None) -> list:
    try:
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) else []
    except json.JSONDecodeError:
        return []


def _utc(value: dt.datetime | None) -> dt.datetime | None:
    return value.replace(tzinfo=dt.timezone.utc) if value is not None and value.tzinfo is None else value


def in_window(policy: PatchPolicy, now: dt.datetime) -> bool:
    """Window hours are UTC. A window like 22:00–04:00 belongs to the day it starts."""
    start, end, hour = policy.window_start_hour, policy.window_end_hour, now.hour
    days = set(loads(policy.window_days))
    if start == end:
        return now.weekday() in days
    if start < end:
        return now.weekday() in days and start <= hour < end
    if hour >= start:
        return now.weekday() in days
    if hour < end:
        return (now - dt.timedelta(days=1)).weekday() in days
    return False


def next_window_start(policy: PatchPolicy, now: dt.datetime) -> dt.datetime | None:
    days = set(loads(policy.window_days))
    if not days:
        return None
    base = now.replace(minute=0, second=0, microsecond=0)
    for offset in range(0, 8 * 24):
        candidate = base + dt.timedelta(hours=offset)
        if candidate > now and candidate.hour == policy.window_start_hour and candidate.weekday() in days:
            return candidate
    return None


def _devices_in_scope(db: Session, policy: PatchPolicy) -> list[Device]:
    query = db.query(Device).filter(Device.org_id == policy.org_id)
    types = loads(policy.device_types)
    if types:
        query = query.filter(Device.device_type.in_(types))
    if policy.customer_id:
        query = query.filter(Device.customer_id == policy.customer_id)
    return query.order_by(Device.hostname).all()


def eligible(db: Session, policy: PatchPolicy, now: dt.datetime) -> dict[int, list[Patch]]:
    """Patches this policy would deploy now, grouped by device id."""
    devices = {d.id: d for d in _devices_in_scope(db, policy)}
    if not devices:
        return {}
    severities, categories = set(loads(policy.auto_approve)), set(loads(policy.categories))
    cutoff = now - dt.timedelta(days=max(0, policy.defer_days))
    grouped: dict[int, list[Patch]] = {}
    patches = db.query(Patch).filter(Patch.org_id == policy.org_id, Patch.device_id.in_(list(devices)),
        Patch.status.in_(OPEN_STATUSES)).order_by(Patch.id).all()
    for patch in patches:
        if categories and patch.category not in categories:
            continue
        if patch.approval == "approved":
            ok = True
        elif patch.approval == "unreviewed":
            ok = patch.severity in severities and (_utc(patch.created_at) or now) <= cutoff
        else:
            ok = False  # rejected or deferred are never deployed automatically
        if ok:
            grouped.setdefault(patch.device_id, []).append(patch)
    return grouped


def deploy_command(device: Device, reboot: str, patches: list[Patch]) -> str:
    """Install exactly the given patches; never a blanket upgrade, so rejected patches stay uninstalled."""
    picked = [t for t in (targets(device, p) for p in patches) if t]
    if not picked:
        raise ValueError("none of these patches can be targeted precisely")
    if (device.os or "").lower().startswith("windows"):
        lines = []
        kbs = [value for kind, value in picked if kind == "kb"]
        if kbs:
            lines.append(WINDOWS_UPDATE_INSTALL.replace("{kbs}", ", ".join(f"'{kb}'" for kb in kbs)))
        for kind, value in picked:
            if kind == "winget":
                lines.append(f"winget upgrade --id {value} --exact --silent --accept-source-agreements --accept-package-agreements")
        if reboot == "always":
            lines.append("shutdown /r /t 300 /c 'ProofOS patch policy reboot in 5 minutes'")
        elif reboot == "if_required":
            lines.append(f"if (Test-Path '{_REBOOT_PENDING}') {{ shutdown /r /t 300 /c 'ProofOS patch policy reboot in 5 minutes' }}")
        return encoded_powershell("\n".join(lines) + "\n")
    names = " ".join(value for _kind, value in picked)
    command = f"sudo apt-get update -y >/dev/null 2>&1; sudo apt-get install -y --only-upgrade {names} 2>/dev/null || sudo dnf upgrade -y {names}"
    if reboot == "always":
        command += ' ; sudo shutdown -r +5 "ProofOS patch policy reboot"'
    elif reboot == "if_required":
        command += ' ; if [ -f /var/run/reboot-required ]; then sudo shutdown -r +5 "ProofOS patch policy reboot"; fi'
    return command


def deploy(db: Session, device: Device, patches: list[Patch], reboot: str, actor: dict, reason: str) -> ScriptRun:
    """Queue one agent run covering every listed patch on one device."""
    command = deploy_command(device, reboot, patches)
    script = Script(org_id=device.org_id, name="patch-deploy:" + ",".join(str(p.id) for p in patches), body=command, version="1.0.0")
    db.add(script)
    db.flush()
    run = ScriptRun(org_id=device.org_id, device_id=device.id, script_id=script.id, status="pending")
    db.add(run)
    for patch in patches:
        patch.status = "deploying"
    db.flush()
    emit(db, "patch.deployment.queued", {"run_id": run.id, "device_id": device.id, "patch_ids": [p.id for p in patches],
        "names": [p.name for p in patches], "reboot": reboot}, actor, {"org_id": device.org_id, "device_id": device.id}, {"reason": reason})
    return run


def run_policy(db: Session, policy: PatchPolicy, actor: dict, force: bool = False, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    if not force and not in_window(policy, now):
        nxt = next_window_start(policy, now)
        return {"ran": False, "reason": "outside the maintenance window", "next_window": nxt.isoformat() if nxt else None, "runs": []}
    kill_switch.require_disengaged(db)
    devices = {d.id: d for d in _devices_in_scope(db, policy)}
    runs, skipped = [], []
    for device_id, patches in eligible(db, policy, now).items():
        targetable = [p for p in patches if targets(devices[device_id], p)]
        skipped += [{"patch_id": p.id, "name": p.name, "reason": "no exact package id or KB to install"} for p in patches if p not in targetable]
        if not targetable:
            continue
        for patch in targetable:
            if patch.approval == "unreviewed":
                patch.approval = "approved"  # approved by this policy's rules; recorded in the proof below
        run = deploy(db, devices[device_id], targetable, policy.reboot, actor, f"patch policy '{policy.name}'")
        runs.append({"device_id": device_id, "hostname": devices[device_id].hostname, "run_id": run.id, "patch_ids": [p.id for p in targetable]})
    policy.last_run_at = now
    db.commit()
    emit(db, "patch.policy.run", {"policy_id": policy.id, "forced": force, "devices": len(runs),
        "patches": sum(len(r["patch_ids"]) for r in runs)}, actor, {"org_id": policy.org_id}, {"reason": "scheduled" if not force else "run now"})
    return {"ran": True, "runs": runs, "skipped": skipped}


def run_due_policies(db: Session, now: dt.datetime | None = None) -> int:
    """Called by the scheduler: run enabled policies whose window is open, at most once per window."""
    now = now or dt.datetime.now(dt.timezone.utc)
    ran = 0
    for policy in db.query(PatchPolicy).filter(PatchPolicy.enabled.is_(True)).all():
        last = _utc(policy.last_run_at)
        if not in_window(policy, now) or (last and now - last < AUTO_RUN_COOLDOWN):
            continue
        try:
            run_policy(db, policy, {"actor_id": f"patch-policy:{policy.id}", "actor_type": "scheduler"}, now=now)
            ran += 1
        except Exception:  # noqa: BLE001 - a frozen kill switch or one bad policy must not stop the others
            db.rollback()
    return ran


def compliance(db: Session, org_id: int) -> dict:
    devices = db.query(Device).filter(Device.org_id == org_id).order_by(Device.hostname).all()
    open_patches = db.query(Patch).filter(Patch.org_id == org_id, Patch.status.in_(OPEN_STATUSES + ("deploying",))).all()
    per: dict[int, dict] = {d.id: {"device_id": d.id, "hostname": d.hostname, "os": d.os, "pending": 0, "critical": 0,
        "failed": 0, "deploying": 0, "awaiting_approval": 0, "reboot_required": bool(d.reboot_required)} for d in devices}
    for p in open_patches:
        row = per.get(p.device_id)
        if not row:
            continue
        if p.status == "deploying":
            row["deploying"] += 1
            continue
        row["pending"] += 1
        row["failed"] += p.status == "failed"
        row["critical"] += p.severity == "critical"
        row["awaiting_approval"] += p.approval == "unreviewed"
    rows = list(per.values())
    for row in rows:
        row["compliant"] = row["pending"] == 0 and row["deploying"] == 0 and not row["reboot_required"]
    total = len(rows)
    return {
        "devices": rows,
        "total_devices": total,
        "compliant_devices": sum(r["compliant"] for r in rows),
        "compliance_rate": round(sum(r["compliant"] for r in rows) / total, 4) if total else None,
        "pending_patches": sum(r["pending"] for r in rows),
        "critical_patches": sum(r["critical"] for r in rows),
        "failed_patches": sum(r["failed"] for r in rows),
        "awaiting_approval": sum(r["awaiting_approval"] for r in rows),
        "reboot_required": sum(r["reboot_required"] for r in rows),
    }
