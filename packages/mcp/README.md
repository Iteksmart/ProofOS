# MCP

Model-agnostic tool surface. Each tool is a thin wrapper over `services/api` REST,
so AI can act without knowing DB internals.

## Tools (`mcp_server.py`)
- `device_list(org_id)`
- `ticket_list(org_id)`
- `proof_verify(receipt_id)`
- `monitor_list(org_id)`
- `script_run(org_id, script_id, device_id)`
- `ai_ask(org_id, query)`

Set `PROOFOS_API_URL` (default `http://localhost:8000`) and `PROOFOS_TOKEN`.

## Adapters (`adapters/`)
One per vendor — thin translation `mcp tool → vendor REST → normalise → proof emit`:

- `Microsoft365Adapter` — Microsoft Graph users/device sync
- `GoogleWorkspaceAdapter` — Admin SDK directory sync
- `AwsAdapter` — EC2 instance sync (via REST gateway)
- `AzureAdapter` — Azure Resource Manager VM sync
- `VmwareAdapter` — vCenter VM sync

Each adapter is a stub against a vendor gateway base URL; tokens come from env,
never plaintext. Syncs can emit ProofOS proof records for audit.

```python
from adapters import Microsoft365Adapter
a = Microsoft365Adapter(base_url="https://graph.example", token="...")
print(a.list_resources())
```

## Python deps
```powershell
python -m pip install -r requirements.txt   # httpx + mcp
```

## Sellable alone
`packages/mcp/` can be deployed as its own MCP server against any ProofOS-compatible API.
