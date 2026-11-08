"""ProofOS MCP server — typed tools over the control-plane API.

Set PROOFOS_API_URL (default http://localhost:8000) and PROOFOS_TOKEN.
"""
from __future__ import annotations

import os

import httpx
from packages.mcp.adapters import ADAPTERS

API = os.getenv("PROOFOS_API_URL", "http://localhost:8000").rstrip("/")
TOKEN = os.getenv("PROOFOS_TOKEN", "")


def _headers() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}


def device_list(org_id: int) -> list:
    return httpx.get(f"{API}/v1/devices", params={"org_id": org_id}, headers=_headers()).json()


def device_get(device_id: int) -> dict:
    return httpx.get(f"{API}/v1/devices/{device_id}", headers=_headers()).json()


def device_metrics(device_id: int) -> list:
    return httpx.get(f"{API}/v1/devices/{device_id}/metrics", headers=_headers()).json()


def ticket_list(org_id: int) -> list:
    return httpx.get(f"{API}/v1/tickets", params={"org_id": org_id}, headers=_headers()).json()


def ticket_create(org_id: int, title: str, body: str = "", priority: str = "normal") -> dict:
    return httpx.post(
        f"{API}/v1/tickets",
        json={"org_id": org_id, "title": title, "body": body, "priority": priority},
        headers=_headers(),
    ).json()


def ticket_comment(ticket_id: int, body: str) -> dict:
    return httpx.post(f"{API}/v1/tickets/{ticket_id}/comments", json={"body": body}, headers=_headers()).json()


def proof_list() -> list:
    return httpx.get(f"{API}/v1/proof", headers=_headers()).json()


def proof_verify(receipt_id: str) -> dict:
    return httpx.get(f"{API}/v1/proof/verify/{receipt_id}", headers=_headers()).json()


def monitor_list(org_id: int) -> list:
    return httpx.get(f"{API}/v1/monitor", params={"org_id": org_id}, headers=_headers()).json()


def monitor_run(org_id: int) -> dict:
    return httpx.post(f"{API}/v1/monitor/run", params={"org_id": org_id}, headers=_headers()).json()


def script_list(org_id: int) -> list:
    return httpx.get(f"{API}/v1/scripts", params={"org_id": org_id}, headers=_headers()).json()


def script_run(org_id: int, script_id: int, device_id: int) -> dict:
    return httpx.post(
        f"{API}/v1/scripts/{script_id}/runs",
        params={"device_id": device_id},
        headers=_headers(),
    ).json()


def automation_list(org_id: int) -> list:
    return httpx.get(f"{API}/v1/automations", params={"org_id": org_id}, headers=_headers()).json()


def device_command(device_id: int, body: str) -> dict:
    return httpx.post(f"{API}/v1/devices/{device_id}/command", json={"body": body}, headers=_headers()).json()


def approval_list(org_id: int) -> list:
    return httpx.get(f"{API}/v1/approvals", params={"org_id": org_id}, headers=_headers()).json()


def approval_approve(approval_id: int) -> dict:
    return httpx.post(f"{API}/v1/approvals/{approval_id}/approve", headers=_headers()).json()


def ai_propose(org_id: int, query: str) -> dict:
    return httpx.post(f"{API}/v1/ai/propose", json={"org_id": org_id, "query": query}, headers=_headers()).json()


def audit_run(org_id: int, kind: str = "full") -> dict:
    return httpx.post(f"{API}/v1/audits/run", params={"org_id": org_id, "kind": kind}, headers=_headers()).json()


def audit_list(org_id: int) -> list:
    return httpx.get(f"{API}/v1/audits", params={"org_id": org_id}, headers=_headers()).json()


def ai_ask(org_id: int, query: str) -> dict:
    return httpx.post(f"{API}/v1/ai/ask", json={"org_id": org_id, "query": query}, headers=_headers()).json()


def vendor_resources_list(vendor: str) -> dict:
    """Read inventory directly from a configured first-party vendor adapter."""
    adapter_type = ADAPTERS.get(vendor)
    if adapter_type is None:
        supported = ", ".join(sorted(ADAPTERS))
        raise ValueError(f"unsupported vendor {vendor!r}; choose one of: {supported}")
    resources = adapter_type().list_resources()
    return {"vendor": vendor, "count": len(resources), "resources": resources}


TOOLS = {
    "device_list": device_list,
    "device_get": device_get,
    "device_metrics": device_metrics,
    "device_command": device_command,
    "ticket_list": ticket_list,
    "ticket_create": ticket_create,
    "ticket_comment": ticket_comment,
    "proof_list": proof_list,
    "proof_verify": proof_verify,
    "monitor_list": monitor_list,
    "monitor_run": monitor_run,
    "script_list": script_list,
    "script_run": script_run,
    "automation_list": automation_list,
    "approval_list": approval_list,
    "approval_approve": approval_approve,
    "ai_propose": ai_propose,
    "ai_ask": ai_ask,
    "audit_run": audit_run,
    "audit_list": audit_list,
    "vendor_resources_list": vendor_resources_list,
}


def _register() -> None:
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "The ProofOS MCP server requires the MCP SDK. Install packages/mcp/requirements.txt."
        ) from exc

    mcp = FastMCP("proofos")
    for fn in TOOLS.values():
        mcp.tool()(fn)
    mcp.run()


if __name__ == "__main__":
    _register()
