from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


# --- Auth / Orgs ---
class OrgCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)


class WorkspaceBootstrap(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=12, max_length=256)

    @model_validator(mode="after")
    def require_admin_credentials_together(self):
        if bool(self.email) != bool(self.password):
            raise ValueError("email and password must be provided together")
        return self


class OrgRename(BaseModel):
    name: str = Field(min_length=2, max_length=255)


class PasswordResetRequestIn(BaseModel):
    email: EmailStr


class PasswordResetConfirmIn(BaseModel):
    token: str = Field(min_length=20, max_length=4096)
    new_password: str = Field(min_length=12, max_length=256)


class OrgOut(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    org_id: int
    email: EmailStr
    password: str = Field(min_length=8)
    role: str = "engineer"


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class PasswordChangeIn(BaseModel):
    current_password: str | None = None
    new_password: str = Field(min_length=12, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    org_id: int
    email: str
    role: str

    model_config = ConfigDict(from_attributes=True)


# --- Devices ---
class DeviceCreate(BaseModel):
    org_id: int
    hostname: str = Field(min_length=1, max_length=255)
    os: str = ""
    ip: str = ""
    device_type: str = "workstation"


class DeviceHeartbeat(BaseModel):
    cpu: float = 0.0
    disk: float = 0.0
    mem: float = 0.0
    status: str = "online"
    agent_version: str = ""


class DeviceOut(BaseModel):
    id: int
    org_id: int
    hostname: str
    os: str
    ip: str
    device_type: str = "workstation"
    status: str
    cpu: float
    disk: float
    mem: float
    agent_version: str = ""
    last_seen: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class DeviceCreateOut(DeviceOut):
    """Device plus the one-time agent secret (returned only on registration)."""

    device_secret: str = ""


class DeviceMetricOut(BaseModel):
    id: int
    device_id: int
    cpu: float
    disk: float
    mem: float
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# --- Tickets ---
class TicketCreate(BaseModel):
    org_id: int
    title: str = Field(min_length=3, max_length=500)
    body: str = ""
    priority: str = "normal"
    device_id: int | None = None


class TicketUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    status: str | None = None
    priority: str | None = None
    assignee: str | None = None
    device_id: int | None = None
    due_at: datetime | None = None


class TicketCommentCreate(BaseModel):
    body: str = Field(min_length=1)
    author: str = ""


class TicketOut(BaseModel):
    id: int
    org_id: int
    title: str
    body: str
    status: str
    priority: str
    severity: str = "P3"
    assignee: str
    device_id: int | None = None
    due_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# --- Scripts ---
class ScriptCreate(BaseModel):
    org_id: int
    name: str = Field(min_length=2, max_length=255)
    body: str = Field(min_length=1)
    version: str = "1.0.0"


class ScriptOut(BaseModel):
    id: int
    org_id: int
    name: str
    body: str
    version: str

    model_config = ConfigDict(from_attributes=True)


class ScriptRunOut(BaseModel):
    id: int
    org_id: int
    device_id: int
    script_id: int
    status: str
    output: str
    exit_code: int | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class RunComplete(BaseModel):
    output: str = ""
    exit_code: int | None = None


# --- Automations ---
class AutomationCreate(BaseModel):
    org_id: int
    name: str = Field(min_length=2, max_length=255)
    trigger: str = "ticket.opened"
    action: str = "notify"
    condition: str = ""
    autonomy: str = "semi"
    remediation_script_id: int | None = None


class AutomationUpdate(BaseModel):
    name: str | None = None
    trigger: str | None = None
    action: str | None = None
    condition: str | None = None
    autonomy: str | None = None
    enabled: bool | None = None
    remediation_script_id: int | None = None


class AutomationOut(BaseModel):
    id: int
    org_id: int
    name: str
    trigger: str
    action: str
    condition: str = ""
    autonomy: str = "semi"
    remediation_script_id: int | None = None
    enabled: bool

    model_config = ConfigDict(from_attributes=True)


class SimulateIn(BaseModel):
    org_id: int
    trigger: str = "ticket.opened"
    context: dict = {}


# --- Monitor / Alerts ---
class CheckCreate(BaseModel):
    org_id: int
    device_id: int
    kind: str = "ping"
    target: str = ""
    status: str = "ok"
    latency_ms: float = 0.0
    threshold_ms: float = 0.0


class CheckOut(BaseModel):
    id: int
    org_id: int
    device_id: int
    kind: str
    target: str = ""
    status: str
    latency_ms: float
    threshold_ms: float = 0.0

    model_config = ConfigDict(from_attributes=True)


class AlertOut(BaseModel):
    id: int
    org_id: int
    device_id: int | None
    kind: str
    severity: str
    message: str
    acked: bool

    model_config = ConfigDict(from_attributes=True)


# --- Proof ---
class ProofOut(BaseModel):
    id: str
    what: str
    canonical_bytes: str
    payload_digest: str
    prev_hash: str
    signature: str
    anchored: bool = False
    anchor_commitment: str = ""

    model_config = ConfigDict(from_attributes=True)


class ProofVerifyOut(BaseModel):
    id: str
    what: str = ""
    verified: bool
    checks: dict
    trust: dict


class ProofEmitIn(BaseModel):
    what: str = "note"
    payload: dict = {}
    who: dict = {}
    where: dict = {}
    why: dict = {}


# --- AI ---
class AiAsk(BaseModel):
    org_id: int
    query: str


class AiSummarise(BaseModel):
    org_id: int
    scope: str = "open"


# --- Approvals / Remote command ---
class CommandIn(BaseModel):
    body: str = Field(min_length=1)
    description: str = ""


class ApprovalOut(BaseModel):
    id: int
    org_id: int
    requester_kind: str
    kind: str
    description: str
    target_type: str
    target_id: int | None = None
    status: str
    decided_by: str = ""
    created_at: datetime | None = None
    decided_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# --- Audit ---
class AuditFindingOut(BaseModel):
    id: int
    audit_id: int
    category: str
    severity: str
    title: str
    detail: str

    model_config = ConfigDict(from_attributes=True)


class AuditOut(BaseModel):
    id: int
    org_id: int
    kind: str
    score: float
    summary: str
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class AuditRunOut(BaseModel):
    audit: AuditOut
    findings: list[AuditFindingOut]
    score: float


# --- Onboarding ---
class OnboardingStepOut(BaseModel):
    id: int
    org_id: int
    title: str
    detail: str
    step_order: int
    done: bool

    model_config = ConfigDict(from_attributes=True)


# --- Consulting ---
class ClientProfileIn(BaseModel):
    contact_name: str = ""
    contact_email: str = ""
    phone: str = ""
    industry: str = ""
    status: str = "active"
    notes: str = ""


class ClientProfileOut(BaseModel):
    id: int
    org_id: int
    contact_name: str
    contact_email: str
    phone: str
    industry: str
    status: str
    notes: str

    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    org_id: int
    name: str = Field(min_length=2, max_length=255)
    description: str = ""
    status: str = "planning"


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    notes: str | None = None


class ProjectOut(BaseModel):
    id: int
    org_id: int
    name: str
    description: str
    status: str
    notes: str
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# --- CMDB / Knowledge / Vault / Time / Changes ---
class CiCreate(BaseModel):
    org_id: int
    name: str = Field(min_length=2, max_length=255)
    ci_type: str = "server"
    status: str = "operational"
    description: str = ""
    attributes: str = "{}"


class CiOut(BaseModel):
    id: int
    org_id: int
    name: str
    ci_type: str
    status: str
    description: str
    attributes: str

    model_config = ConfigDict(from_attributes=True)


class ArticleCreate(BaseModel):
    org_id: int
    title: str = Field(min_length=2, max_length=255)
    body: str = ""
    category: str = "general"
    tags: str = ""
    published: bool = True


class ArticleOut(BaseModel):
    id: int
    org_id: int
    title: str
    body: str
    category: str
    tags: str
    published: bool

    model_config = ConfigDict(from_attributes=True)


class SecretCreate(BaseModel):
    org_id: int
    name: str = Field(min_length=2, max_length=255)
    value: str = Field(min_length=1)
    category: str = "general"
    notes: str = ""


class SecretOut(BaseModel):
    id: int
    org_id: int
    name: str
    category: str
    notes: str

    model_config = ConfigDict(from_attributes=True)


class TimeEntryCreate(BaseModel):
    org_id: int
    minutes: int = Field(ge=1)
    notes: str = ""
    billable: bool = True
    ticket_id: int | None = None
    project_id: int | None = None


class TimeEntryOut(BaseModel):
    id: int
    org_id: int
    user_id: int
    minutes: int
    notes: str
    billable: bool
    ticket_id: int | None = None
    project_id: int | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ChangeCreate(BaseModel):
    org_id: int
    title: str = Field(min_length=2, max_length=255)
    description: str = ""
    risk: str = "medium"
    impact: str = "medium"
    plan: str = ""


class ChangeUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    risk: str | None = None
    impact: str | None = None
    plan: str | None = None
    status: str | None = None


class ChangeOut(BaseModel):
    id: int
    org_id: int
    title: str
    description: str
    risk: str
    impact: str
    plan: str
    status: str
    requester_id: int

    model_config = ConfigDict(from_attributes=True)


# --- Integrations (metrics webhook) ---
class MetricIn(BaseModel):
    org_id: int
    source: str = "prometheus"
    host: str = ""
    metrics: list[dict] = []


class IntegrationMetricOut(BaseModel):
    id: int
    org_id: int
    source: str
    name: str
    value: float
    host: str
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# --- VMs / Remote control ---
class VmCreate(BaseModel):
    org_id: int
    host_id: int
    name: str = Field(min_length=1, max_length=255)
    hypervisor: str = "hyper-v"
    state: str = "unknown"
    vcpu: int = 0
    memory_mb: int = 0
    notes: str = ""


class VmOut(BaseModel):
    id: int
    org_id: int
    host_id: int
    name: str
    hypervisor: str
    state: str
    vcpu: int
    memory_mb: int
    notes: str

    model_config = ConfigDict(from_attributes=True)


class RemoteSessionIn(BaseModel):
    kind: str = "console"  # console | kvm
    provider: str = "native"  # native | meshcentral | vnc | guacamole


class RemoteSessionOut(BaseModel):
    id: int
    org_id: int
    device_id: int
    kind: str
    provider: str
    status: str
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# --- Patch management / SSO ---
class PatchCreate(BaseModel):
    org_id: int
    device_id: int
    name: str = Field(min_length=1, max_length=255)
    category: str = "os"
    current_version: str = ""
    available_version: str = ""
    severity: str = "moderate"


class PatchOut(BaseModel):
    id: int
    org_id: int
    device_id: int
    name: str
    category: str
    current_version: str
    available_version: str
    severity: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class SsoConfigIn(BaseModel):
    provider: str = "saml"
    entity_id: str = ""
    metadata_url: str = ""
    enabled: bool = False


class SsoConfigOut(BaseModel):
    id: int
    org_id: int
    provider: str
    entity_id: str
    metadata_url: str
    enabled: bool

    model_config = ConfigDict(from_attributes=True)


class PushRegister(BaseModel):
    org_id: int
    user_id: int
    fcm_token: str = Field(min_length=10, max_length=512)
    platform: str = "web"


class PushDeviceOut(BaseModel):
    id: int
    org_id: int
    user_id: int
    fcm_token: str
    platform: str

    model_config = ConfigDict(from_attributes=True)


# --- Secure Workspace (encrypted enclave) ---
class EnclavePolicyIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    allowed_apps: str = "[]"
    blocked_apps: str = "[]"
    network_allowlist: str = "[]"
    dlp_rules: str = "{}"
    clipboard_enabled: bool = False
    watermark_enabled: bool = True
    ai_governed: bool = True


class EnclavePolicyOut(BaseModel):
    id: int
    org_id: int
    name: str
    allowed_apps: str
    blocked_apps: str
    network_allowlist: str
    dlp_rules: str
    clipboard_enabled: bool
    watermark_enabled: bool
    ai_governed: bool

    model_config = ConfigDict(from_attributes=True)


class EnclaveCreate(BaseModel):
    org_id: int
    device_id: int
    name: str = "Secure Workspace"
    policy_id: int | None = None


class EnclaveOut(BaseModel):
    id: int
    org_id: int
    device_id: int
    policy_id: int | None = None
    name: str
    status: str
    encryption_key_id: str
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class EnclaveEventIn(BaseModel):
    kind: str
    severity: str = "info"
    detail: str = ""
    source: str = ""


class EnclaveEventOut(BaseModel):
    id: int
    org_id: int
    enclave_id: int
    device_id: int
    kind: str
    severity: str
    detail: str
    source: str
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
