from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import get_current_user

router = APIRouter()

TOOL_CATALOG = [
    {"name": "device.list", "description": "List devices in an org", "method": "GET", "path": "/v1/devices?org_id={org_id}"},
    {"name": "device.get", "description": "Get one device", "method": "GET", "path": "/v1/devices/{device_id}"},
    {"name": "device.metrics", "description": "Device telemetry history", "method": "GET", "path": "/v1/devices/{device_id}/metrics"},
    {"name": "ticket.list", "description": "List tickets in an org", "method": "GET", "path": "/v1/tickets?org_id={org_id}"},
    {"name": "ticket.create", "description": "Create a ticket", "method": "POST", "path": "/v1/tickets"},
    {"name": "ticket.comment", "description": "Comment on a ticket", "method": "POST", "path": "/v1/tickets/{ticket_id}/comments"},
    {"name": "script.list", "description": "List scripts", "method": "GET", "path": "/v1/scripts?org_id={org_id}"},
    {"name": "script.run", "description": "Queue a script on a device", "method": "POST", "path": "/v1/scripts/{script_id}/runs?device_id={device_id}"},
    {"name": "device.command", "description": "Run a shell command on a device (admin)", "method": "POST", "path": "/v1/devices/{device_id}/command"},
    {"name": "approval.list", "description": "List human-gated approvals", "method": "GET", "path": "/v1/approvals?org_id={org_id}"},
    {"name": "approval.approve", "description": "Approve a pending action", "method": "POST", "path": "/v1/approvals/{id}/approve"},
    {"name": "ai.propose", "description": "Propose a remediation action for approval", "method": "POST", "path": "/v1/ai/propose"},
    {"name": "audit.run", "description": "Run a security/compliance/governance audit", "method": "POST", "path": "/v1/audits/run?org_id={org_id}&kind={kind}"},
    {"name": "audit.list", "description": "List audit runs", "method": "GET", "path": "/v1/audits?org_id={org_id}"},
    {"name": "cmdb.list", "description": "List configuration items (CMDB)", "method": "GET", "path": "/v1/cmdb?org_id={org_id}"},
    {"name": "knowledge.search", "description": "Search knowledge base", "method": "GET", "path": "/v1/knowledge?org_id={org_id}&q={q}"},
    {"name": "change.list", "description": "List change requests", "method": "GET", "path": "/v1/changes?org_id={org_id}"},
    {"name": "analytics.anomalies", "description": "Detect telemetry anomalies", "method": "GET", "path": "/v1/analytics/anomalies?org_id={org_id}"},
    {"name": "automation.simulate", "description": "Dry-run automations (no side effects)", "method": "POST", "path": "/v1/automations/simulate"},
    {"name": "integration.metrics", "description": "Ingest metrics from Datadog/Prometheus/Grafana", "method": "POST", "path": "/v1/integrations/metrics"},
    {"name": "itechsmart.status", "description": "iTechSmart UAIO service health", "method": "GET", "path": "/v1/itechsmart/status"},
    {"name": "itechsmart.tools", "description": "List iTechSmart MCP tools", "method": "GET", "path": "/v1/itechsmart/tools"},
    {"name": "itechsmart.chain", "description": "ProofLink Plus receipt chain", "method": "GET", "path": "/v1/itechsmart/chain"},
    {"name": "itechsmart.mcp_call", "description": "Invoke an iTechSmart MCP tool", "method": "POST", "path": "/v1/itechsmart/mcp/call"},
    {"name": "vm.list", "description": "List virtual machines", "method": "GET", "path": "/v1/vms?org_id={org_id}"},
    {"name": "vm.start", "description": "Start a virtual machine", "method": "POST", "path": "/v1/vms/{id}/start"},
    {"name": "remote.session", "description": "Open a remote control session", "method": "POST", "path": "/v1/remote/devices/{device_id}/remote-session"},
    {"name": "automation.list", "description": "List automation rules", "method": "GET", "path": "/v1/automations?org_id={org_id}"},
    {"name": "monitor.run", "description": "Run reachability checks for an org", "method": "POST", "path": "/v1/monitor/run?org_id={org_id}"},
    {"name": "proof.list", "description": "List org proof records", "method": "GET", "path": "/v1/proof"},
    {"name": "proof.verify", "description": "Verify a proof receipt", "method": "GET", "path": "/v1/proof/verify/{id}"},
    {"name": "ai.ask", "description": "Ask the AI copilot", "method": "POST", "path": "/v1/ai/ask"},
]


@router.get("/tools")
def list_tools(user=Depends(get_current_user)):
    return {"tools": TOOL_CATALOG}
