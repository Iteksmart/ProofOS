from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Org(Base):
    __tablename__ = "orgs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="engineer", index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    hostname: Mapped[str] = mapped_column(String(255), index=True)
    os: Mapped[str] = mapped_column(String(100), default="")
    ip: Mapped[str] = mapped_column(String(50), default="")
    device_type: Mapped[str] = mapped_column(String(30), default="workstation", index=True)
    status: Mapped[str] = mapped_column(String(20), default="online", index=True)
    cpu: Mapped[float] = mapped_column(Float, default=0.0)
    disk: Mapped[float] = mapped_column(Float, default=0.0)
    mem: Mapped[float] = mapped_column(Float, default=0.0)
    last_seen: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    agent_version: Mapped[str] = mapped_column(String(50), default="")
    secret_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="normal", index=True)
    severity: Mapped[str] = mapped_column(String(10), default="P3", index=True)  # P1..P4 (auto-classified)
    assignee: Mapped[str] = mapped_column(String(255), default="", index=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"), nullable=True, index=True)
    due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class DeviceMetric(Base):
    """Per-heartbeat telemetry snapshot (CPU/disk/mem history)."""

    __tablename__ = "device_metrics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    cpu: Mapped[float] = mapped_column(Float, default=0.0)
    disk: Mapped[float] = mapped_column(Float, default=0.0)
    mem: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class TicketComment(Base):
    __tablename__ = "ticket_comments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    author: Mapped[str] = mapped_column(String(255), default="")
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class Script(Base):
    __tablename__ = "scripts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    body: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(50), default="1.0.0")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class ScriptRun(Base):
    __tablename__ = "script_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    script_id: Mapped[int] = mapped_column(ForeignKey("scripts.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    output: Mapped[str] = mapped_column(Text, default="")
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Automation(Base):
    __tablename__ = "automations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    trigger: Mapped[str] = mapped_column(String(100), default="ticket.opened", index=True)
    action: Mapped[str] = mapped_column(String(100), default="notify", index=True)  # notify | alert | remediate
    autonomy: Mapped[str] = mapped_column(String(10), default="semi", index=True)  # manual | semi | auto
    condition: Mapped[str] = mapped_column(Text, default="")
    remediation_script_id: Mapped[int | None] = mapped_column(ForeignKey("scripts.id"), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class IntegrationMetric(Base):
    """Inbound metric point from an external integration (Datadog/Prometheus/Grafana webhook)."""

    __tablename__ = "integration_metrics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    source: Mapped[str] = mapped_column(String(100), default="prometheus", index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    value: Mapped[float] = mapped_column(Float, default=0.0)
    host: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class VirtualMachine(Base):
    """A managed VM on a hypervisor host (Hyper-V, KVM/libvirt, VMware, QEMU)."""

    __tablename__ = "virtual_machines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    hypervisor: Mapped[str] = mapped_column(String(30), default="hyper-v", index=True)  # hyper-v | libvirt | vmware | qemu | other
    state: Mapped[str] = mapped_column(String(20), default="unknown", index=True)  # running | stopped | paused | unknown
    vcpu: Mapped[int] = mapped_column(Integer, default=0)
    memory_mb: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class RemoteSession(Base):
    """A proof-audited remote control / KVM session (console or screen)."""

    __tablename__ = "remote_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="console")  # console | kvm
    provider: Mapped[str] = mapped_column(String(30), default="native")  # native | meshcentral | vnc | guacamole
    token: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)  # active | ended
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Patch(Base):
    """An OS/third-party update needing deployment (patch management)."""

    __tablename__ = "patches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(30), default="os", index=True)  # os | third_party | security | other
    current_version: Mapped[str] = mapped_column(String(100), default="")
    available_version: Mapped[str] = mapped_column(String(100), default="")
    severity: Mapped[str] = mapped_column(String(20), default="moderate", index=True)  # critical | important | moderate | low
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending | installed | failed | superseded
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class SsoConfig(Base):
    """Per-tenant SSO/SAML identity configuration."""

    __tablename__ = "sso_configs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(50), default="saml")  # saml | oidc
    entity_id: Mapped[str] = mapped_column(String(255), default="")
    metadata_url: Mapped[str] = mapped_column(String(500), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class TraceSpan(Base):
    """Lightweight APM/tracing span for request latency analysis."""

    __tablename__ = "trace_spans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int | None] = mapped_column(ForeignKey("orgs.id"), nullable=True, index=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    span_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    method: Mapped[str] = mapped_column(String(10), default="")
    path: Mapped[str] = mapped_column(String(500), default="")
    status_code: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class PushDevice(Base):
    """A registered Firebase Cloud Messaging device token for push notifications."""

    __tablename__ = "push_devices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    fcm_token: Mapped[str] = mapped_column(String(512), index=True)
    platform: Mapped[str] = mapped_column(String(20), default="web")  # web | android | ios
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class KillSwitch(Base):
    """Singleton row (id=1) for the emergency execution kill switch (fail-closed)."""

    __tablename__ = "kill_switch"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    engaged: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(String(255), default="")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class EnclavePolicy(Base):
    """DLP / IT policy governing a secure workspace (app allowlist, network, DLP rules)."""

    __tablename__ = "enclave_policies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    allowed_apps: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    blocked_apps: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    network_allowlist: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of domains/CIDRs
    dlp_rules: Mapped[str] = mapped_column(Text, default="{}")  # JSON: {"patterns":[...], "block_clipboard":bool}
    clipboard_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    watermark_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_governed: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class SecureEnclave(Base):
    """A company-controlled, encrypted secure workspace provisioned on an endpoint."""

    __tablename__ = "secure_enclaves"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    policy_id: Mapped[int | None] = mapped_column(ForeignKey("enclave_policies.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), default="Secure Workspace")
    status: Mapped[str] = mapped_column(String(20), default="provisioning", index=True)  # provisioning|active|suspended|removed
    encryption_key_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class EnclaveEvent(Base):
    """A DLP / policy event reported by the secure-workspace agent."""

    __tablename__ = "enclave_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    enclave_id: Mapped[int] = mapped_column(ForeignKey("secure_enclaves.id"), index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)  # dlp_blocked|app_blocked|network_blocked|policy_violation|ai_usage|provisioned
    severity: Mapped[str] = mapped_column(String(20), default="info")  # info|warning|critical
    detail: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class AutomationRun(Base):
    __tablename__ = "automation_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    automation_id: Mapped[int] = mapped_column(ForeignKey("automations.id"), index=True)
    trigger: Mapped[str] = mapped_column(String(100))
    result: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProofRecord(Base):
    __tablename__ = "proof_records"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[int | None] = mapped_column(ForeignKey("orgs.id"), nullable=True, index=True)
    what: Mapped[str] = mapped_column(String(100), index=True)
    canonical_bytes: Mapped[str] = mapped_column(Text)
    payload_digest: Mapped[str] = mapped_column(String(64), index=True)
    prev_hash: Mapped[str] = mapped_column(String(64))
    signature: Mapped[str] = mapped_column(Text)
    signing_key_id: Mapped[str] = mapped_column(String(100), default="ed25519:proofos-1")
    anchored: Mapped[bool] = mapped_column(Boolean, default=False)
    anchor_commitment: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class StandaloneProofRecord(Base):
    """Schema mirror for the independently operated proof ledger service."""

    __tablename__ = "proof_ledger_records"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    what: Mapped[str] = mapped_column(String(100), index=True)
    canonical_bytes: Mapped[str] = mapped_column(Text)
    payload_digest: Mapped[str] = mapped_column(String(64), index=True)
    prev_hash: Mapped[str] = mapped_column(String(64))
    signature: Mapped[str] = mapped_column(Text)
    signing_key_id: Mapped[str] = mapped_column(String(100), default="ed25519:proofos-1")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class RemediationOutcome(Base):
    """Learning loop: records remediation outcomes (success/failure) to inform future routing."""

    __tablename__ = "remediation_outcomes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    action: Mapped[str] = mapped_column(String(100), default="")
    script_id: Mapped[int | None] = mapped_column(ForeignKey("scripts.id"), nullable=True, index=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"), nullable=True, index=True)
    success: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)  # None = pending
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class MonitorCheck(Base):
    __tablename__ = "monitor_checks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    kind: Mapped[str] = mapped_column(String(50), default="ping")
    target: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20), default="ok", index=True)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    threshold_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(50), default="device_offline")
    severity: Mapped[str] = mapped_column(String(20), default="warning", index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    acked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class Approval(Base):
    """Human-approval gate for AI/automation-proposed state-changing actions."""

    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    requester_id: Mapped[str] = mapped_column(String(255), default="")
    requester_kind: Mapped[str] = mapped_column(String(20), default="user")  # user | ai | automation
    kind: Mapped[str] = mapped_column(String(30), default="command")  # command | script | automation | upgrade
    description: Mapped[str] = mapped_column(Text, default="")
    target_type: Mapped[str] = mapped_column(String(30), default="device")
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")  # JSON of the action to execute on approve
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending | approved | denied
    decided_by: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ClientProfile(Base):
    """Consulting: client/tenant profile."""

    __tablename__ = "client_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), unique=True, index=True)
    contact_name: Mapped[str] = mapped_column(String(255), default="")
    contact_email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    industry: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)  # prospect | active | onboarded | churned
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Project(Base):
    """Consulting: engagement/project for a client."""

    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="planning", index=True)  # planning | active | on_hold | done
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class OnboardingStep(Base):
    """Client onboarding checklist item."""

    __tablename__ = "onboarding_steps"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    detail: Mapped[str] = mapped_column(Text, default="")
    step_order: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class Audit(Base):
    """An infrastructure security/compliance/governance audit run."""

    __tablename__ = "audits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30), default="full")  # security | compliance | governance | full
    score: Mapped[float] = mapped_column(Float, default=0.0)
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class AuditFinding(Base):
    __tablename__ = "audit_findings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id"), index=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    category: Mapped[str] = mapped_column(String(30), default="security")  # security | compliance | governance
    severity: Mapped[str] = mapped_column(String(20), default="info")  # critical | high | medium | low | info
    title: Mapped[str] = mapped_column(String(255))
    detail: Mapped[str] = mapped_column(Text, default="")


class ConfigurationItem(Base):
    """CMDB configuration item (ServiceNow-style)."""

    __tablename__ = "configuration_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    ci_type: Mapped[str] = mapped_column(String(50), default="server", index=True)  # server|switch|application|service|database|network|other
    status: Mapped[str] = mapped_column(String(30), default="operational", index=True)  # operational|degraded|offline|retired
    description: Mapped[str] = mapped_column(Text, default="")
    attributes: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Article(Base):
    """Knowledge base article (ServiceNow/ITBoost-style)."""

    __tablename__ = "articles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    body: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(100), default="general", index=True)
    tags: Mapped[str] = mapped_column(String(500), default="")
    published: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Secret(Base):
    """Privileged credential / secret vault entry (CyberArk PAM-style). Value encrypted at rest."""

    __tablename__ = "secrets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(100), default="general", index=True)
    value_encrypted: Mapped[str] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class TimeEntry(Base):
    """PSA time tracking (ConnectWise-style)."""

    __tablename__ = "time_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    minutes: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
    billable: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class ChangeRequest(Base):
    """ITIL change management (ServiceNow-style)."""

    __tablename__ = "change_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    risk: Mapped[str] = mapped_column(String(20), default="medium")  # low | medium | high
    impact: Mapped[str] = mapped_column(String(20), default="medium")  # low | medium | high
    plan: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)  # draft|submitted|approved|rejected|implemented
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
