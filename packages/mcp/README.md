# ProofOS MCP connectors

These connectors use the providers' supported APIs directly. They do not expect
an undocumented gateway or report success when credentials are missing. Each
`list_resources()` call validates its credentials, follows provider pagination,
normalizes the records, and emits a ProofOS proof event when `PROOFOS_TOKEN` is
set.

Install the connector dependencies:

```powershell
python -m pip install -r packages/mcp/requirements.txt
```

## Providers and permissions

| Adapter | API and authentication | Required configuration / access |
|---|---|---|
| `Microsoft365Adapter` | Microsoft Graph v1.0 with Entra client credentials | `M365_TENANT_ID`, `M365_CLIENT_ID`, `M365_CLIENT_SECRET`; grant admin consent for the Graph application permission `User.Read.All`. |
| `GoogleWorkspaceAdapter` | Admin SDK Directory API with service account domain-wide delegation | Set `GOOGLE_WORKSPACE_SERVICE_ACCOUNT_FILE` (or JSON env), `GOOGLE_WORKSPACE_ADMIN_EMAIL`, and optionally `GOOGLE_WORKSPACE_CUSTOMER_ID`. Delegate `admin.directory.user.readonly` in Workspace Admin. |
| `AwsAdapter` | EC2 `DescribeInstances` through Boto3 | `AWS_REGION`; credentials come from the standard AWS SDK chain (role, environment, shared config, or `AWS_PROFILE`). Grant `ec2:DescribeInstances`. |
| `AzureAdapter` | Azure Resource Manager Compute REST API with Entra client credentials | `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_SUBSCRIPTION_ID`; grant a read-only role such as Reader at the subscription/resource-group scope. |
| `VmwareAdapter` | vSphere Automation API session and VM inventory | `VMWARE_BASE_URL`, `VMWARE_USERNAME`, `VMWARE_PASSWORD`; use a vCenter read-only inventory account. For private CA, set `VMWARE_CA_BUNDLE` to the trusted CA file. |

Credentials remain in environment or a mounted secret file. Do not commit them.
The connector never disables TLS verification. Missing credentials, insufficient
permissions, rejected TLS certificates, HTTP failures, unsafe pagination links,
and pagination-limit overflows raise errors instead of returning partial success.

## Example

```python
from packages.mcp.adapters import Microsoft365Adapter

users = Microsoft365Adapter().list_resources()
print(f"Synced {len(users)} Microsoft 365 users")
```

Run the server from the repository root with `python -m packages.mcp.mcp_server`.
It exposes the read-only `vendor_resources_list(vendor)` MCP tool for all five
adapters. Restrict access to users authorized to read the configured tenants.

Set `PROOFOS_API_URL` (default `http://localhost:8000`) and `PROOFOS_TOKEN` to
record completed syncs in the ProofOS ledger. Without a ProofOS token, the
provider sync still runs and returns its normalized resources but does not emit a
ProofOS proof event.

## Supported inventory

- Microsoft 365: users, email, enabled state.
- Google Workspace: users, primary email, suspended state.
- AWS: EC2 instances, state, type, IP addresses, availability zone and Name tag.
- Azure: virtual machines, resource group, size, OS type and power state.
- VMware: vCenter virtual machines, power state, vCPU and memory.
