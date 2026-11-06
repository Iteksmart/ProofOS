"""iTechSmart UAIO integration client (ProofLink / ProofLink Plus / MCP / Ledger).

Read endpoints are public locally; writes (seal) and MCP tool invocation require
ITECHSMART_API_KEY (the local key — the public demo key only works on mcp.itechsmart.dev).
"""
from __future__ import annotations

import json

import httpx

from app.core.config import get_settings

settings = get_settings()


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if settings.itechsmart_api_key:
        h["x-itechsmart-mcp-key"] = settings.itechsmart_api_key
        h["Authorization"] = f"Bearer {settings.itechsmart_api_key}"
    return h


def probe() -> dict:
    services = {
        "mcp": settings.itechsmart_mcp_url,
        "prooflink": settings.itechsmart_prooflink_url,
        "prooflink_plus": settings.itechsmart_prooflink_plus_url,
        "ledger": settings.itechsmart_ledger_url,
    }
    out: dict = {}
    for name, url in services.items():
        try:
            r = httpx.get(f"{url}/health", timeout=5)
            out[name] = {"ok": r.status_code < 500, "status": r.status_code, "body": r.json()}
        except Exception as e:  # noqa: BLE001
            out[name] = {"ok": False, "error": str(e)}
    return out


def mcp_tools() -> dict:
    r = httpx.get(f"{settings.itechsmart_mcp_url}/mcp/tools", timeout=10)
    r.raise_for_status()
    data = r.json()
    tools = [t.get("name") for t in data.get("tools", []) if isinstance(t, dict) and t.get("name")]
    return {"server": data.get("server", {}).get("name"), "count": len(tools), "tools": tools}


def chain(limit: int = 20) -> dict:
    r = httpx.get(f"{settings.itechsmart_prooflink_plus_url}/v1/receipts", timeout=10)
    r.raise_for_status()
    data = r.json()
    receipts = data.get("receipts", [])[:limit]
    return {
        "total": data.get("total"),
        "receipts": [
            {"id": x.get("id"), "category": x.get("category"), "actor": x.get("actor"),
             "subject": x.get("subject"), "action": x.get("action"), "outcome": x.get("outcome"),
             "chain_position": x.get("chain_position"), "hash_sha256": (x.get("hash_sha256") or "")[:16],
             "compliance": x.get("compliance_mappings")}
            for x in receipts
        ],
    }


def seal(payload: dict) -> dict:
    """Seal a receipt on ProofLink Plus (requires ITECHSMART_API_KEY)."""
    r = httpx.post(f"{settings.itechsmart_prooflink_plus_url}/seal", json=payload, headers=_headers(), timeout=20)
    if r.status_code == 401:
        return {"ok": False, "error": "unauthorized — set ITECHSMART_API_KEY", "status": 401}
    r.raise_for_status()
    return r.json()


def mcp_call(tool: str, arguments: dict | None = None) -> dict:
    """Invoke an iTechSmart MCP tool over the SSE transport (requires ITECHSMART_API_KEY).

    HTTP+SSE handshake: GET /sse → discover the POST endpoint → initialize →
    tools/call. Responses may arrive on the SSE stream or as the POST body; both
    are attempted.
    """
    if not settings.itechsmart_api_key:
        return {"ok": False, "error": "set ITECHSMART_API_KEY to invoke iTechSmart MCP tools"}

    base = settings.itechsmart_mcp_url.rstrip("/")
    init = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "proofos", "version": "1.0.0"}},
    }
    call = {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": tool, "arguments": arguments or {}},
    }

    sse_client = httpx.Client(timeout=45)
    post_client = httpx.Client(timeout=45)
    try:
        with sse_client.stream("GET", f"{base}/sse", headers=_headers()) as s:
            if s.status_code == 401:
                return {"ok": False, "error": "unauthorized — invalid ITECHSMART_API_KEY", "status": 401}
            s.raise_for_status()

            lines = s.iter_lines()
            endpoint = None
            event = None
            for line in lines:
                if not line:
                    continue
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data = line.split(":", 1)[1].strip()
                    if event == "endpoint":
                        endpoint = data
                        break
            if not endpoint:
                return {"ok": False, "error": "MCP SSE endpoint not discovered"}
            if endpoint.startswith("/"):
                endpoint = base + endpoint

            post_client.post(endpoint, json=init, headers=_headers())
            resp = post_client.post(endpoint, json=call, headers=_headers())

            # 1) response may be returned directly on the POST
            try:
                body = resp.json()
                if isinstance(body, dict) and body.get("id") == 2:
                    return {"ok": True, "result": body.get("result")}
            except Exception:
                pass

            # 2) otherwise read it from the SSE stream
            for line in lines:
                if line.startswith("data:"):
                    try:
                        msg = json.loads(line.split(":", 1)[1].strip())
                        if msg.get("id") == 2:
                            return {"ok": True, "result": msg.get("result")}
                    except Exception:
                        continue
            return {"ok": True, "note": "request accepted; response not captured"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    finally:
        sse_client.close()
        post_client.close()
