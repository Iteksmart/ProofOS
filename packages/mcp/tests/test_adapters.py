from __future__ import annotations

import json

import boto3
import httpx
import pytest

from packages.mcp.adapters import (
    AdapterConfigurationError,
    AwsAdapter,
    AzureAdapter,
    GoogleWorkspaceAdapter,
    Microsoft365Adapter,
    VmwareAdapter,
)


def test_microsoft_graph_client_credentials_and_pagination(monkeypatch):
    monkeypatch.setenv("M365_TENANT_ID", "tenant-id")
    monkeypatch.setenv("M365_CLIENT_ID", "client-id")
    monkeypatch.setenv("M365_CLIENT_SECRET", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            assert request.url.host == "login.microsoftonline.com"
            assert request.content.decode().find("scope=https%3A%2F%2Fgraph.microsoft.com%2F.default") >= 0
            return httpx.Response(200, json={"access_token": "graph-token", "expires_in": 3600})
        assert request.url.host == "graph.microsoft.com"
        assert request.headers["authorization"] == "Bearer graph-token"
        if request.url.params.get("$skiptoken") == "page-2":
            return httpx.Response(200, json={"value": [{"id": "u2", "displayName": "B", "userPrincipalName": "b@example.com"}]})
        return httpx.Response(200, json={
            "value": [{"id": "u1", "displayName": "A", "mail": "a@example.com", "accountEnabled": True}],
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/users?$skiptoken=page-2",
        })

    adapter = Microsoft365Adapter(transport=httpx.MockTransport(handler))
    rows = adapter.list_resources()
    assert [row["id"] for row in rows] == ["u1", "u2"]
    assert rows[0]["enabled"] is True
    assert rows[1]["email"] == "b@example.com"


def test_vendor_pagination_rejects_foreign_hosts(monkeypatch):
    monkeypatch.setenv("M365_TENANT_ID", "tenant-id")
    monkeypatch.setenv("M365_CLIENT_ID", "client-id")
    monkeypatch.setenv("M365_CLIENT_SECRET", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "graph-token", "expires_in": 3600})
        return httpx.Response(200, json={"value": [], "@odata.nextLink": "https://attacker.example/steal"})

    with pytest.raises(RuntimeError, match="unsafe pagination"):
        Microsoft365Adapter(transport=httpx.MockTransport(handler)).list_resources()


def test_azure_resource_manager_auth_and_pages(monkeypatch):
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant-id")
    monkeypatch.setenv("AZURE_CLIENT_ID", "client-id")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub-123")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            form = request.content.decode()
            assert "management.azure.com%2F%2F.default" in form
            return httpx.Response(200, json={"access_token": "azure-token", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer azure-token"
        assert "/subscriptions/sub-123/providers/Microsoft.Compute/virtualMachines" in request.url.path
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json={"value": [{"id": "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm2", "name": "vm2", "properties": {"hardwareProfile": None, "storageProfile": None}}]})
        assert request.url.params.get("statusOnly") == "true"
        return httpx.Response(200, json={
            "value": [{"id": "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1", "name": "vm1", "location": "eastus", "properties": {"hardwareProfile": {"vmSize": "Standard_B2s"}, "storageProfile": {"osDisk": {"osType": "Linux"}}, "instanceView": {"statuses": [{"code": "PowerState/running", "displayStatus": "VM running"}]}}}],
            "nextLink": "https://management.azure.com/subscriptions/sub-123/providers/Microsoft.Compute/virtualMachines?api-version=2026-03-01&page=2",
        })

    rows = AzureAdapter(transport=httpx.MockTransport(handler)).list_resources()
    assert [row["id"].rsplit("/", 1)[-1] for row in rows] == ["vm1", "vm2"]
    assert rows[0]["resource_group"] == "rg"
    assert rows[0]["power_state"] == "VM running"


def test_google_workspace_uses_directory_pagination_and_normalizes():
    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class Session:
        def __init__(self):
            self.calls = []

        def get(self, url, params, timeout):
            self.calls.append((url, params.copy(), timeout))
            if params.get("pageToken"):
                return Response({"users": [{"id": "u2", "primaryEmail": "two@example.com", "suspended": True}]})
            return Response({
                "users": [{"id": "u1", "name": {"fullName": "One"}, "primaryEmail": "one@example.com"}],
                "nextPageToken": "next-page",
            })

    session = Session()
    rows = GoogleWorkspaceAdapter(session=session).list_resources()
    assert len(session.calls) == 2
    assert session.calls[1][1]["pageToken"] == "next-page"
    assert rows[0]["name"] == "One"
    assert rows[1]["suspended"] is True


def test_google_workspace_builds_delegated_service_account_credentials(monkeypatch):
    from packages.mcp.adapters import google_workspace as google_adapter

    monkeypatch.setenv("GOOGLE_WORKSPACE_SERVICE_ACCOUNT_JSON", json.dumps({"type": "service_account"}))
    monkeypatch.setenv("GOOGLE_WORKSPACE_ADMIN_EMAIL", "admin@workspace.example")
    captured = {}

    class Credentials:
        def with_subject(self, subject):
            captured["subject"] = subject
            return self

    def from_info(info, scopes):
        captured["info"] = info
        captured["scopes"] = scopes
        return Credentials()

    class Session:
        def __init__(self, credentials):
            captured["credentials"] = credentials

        def get(self, url, params, timeout):
            return type("Response", (), {"raise_for_status": lambda self: None, "json": lambda self: {"users": []}})()

        def close(self):
            pass

    monkeypatch.setattr(google_adapter.service_account.Credentials, "from_service_account_info", from_info)
    monkeypatch.setattr(google_adapter, "AuthorizedSession", Session)
    assert GoogleWorkspaceAdapter().list_resources() == []
    assert captured["subject"] == "admin@workspace.example"
    assert captured["scopes"] == ("https://www.googleapis.com/auth/admin.directory.user.readonly",)


def test_aws_uses_boto_credential_chain_paginator(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    captured = {}

    class Paginator:
        def paginate(self):
            return iter([{"Reservations": [{"Instances": [
                {"InstanceId": "i-1", "InstanceType": "t3.small", "State": {"Name": "running"}, "Tags": [{"Key": "Name", "Value": "web"}]},
            ]}]}])

    class Ec2:
        def get_paginator(self, operation):
            captured["operation"] = operation
            return Paginator()

    class Session:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def client(self, name):
            captured["service"] = name
            return Ec2()

    monkeypatch.setattr(boto3, "Session", Session)
    rows = AwsAdapter().list_resources()
    assert captured["region_name"] == "us-east-1"
    assert captured["operation"] == "describe_instances"
    assert rows[0]["name"] == "web"
    assert rows[0]["state"] == "running"


def test_vmware_session_auth_inventory_and_logout(monkeypatch):
    monkeypatch.setenv("VMWARE_BASE_URL", "https://vcenter.example")
    monkeypatch.setenv("VMWARE_USERNAME", "readonly@example.com")
    monkeypatch.setenv("VMWARE_PASSWORD", "secret")
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            assert request.url.path == "/api/session"
            assert request.headers.get("authorization", "").startswith("Basic ")
            return httpx.Response(201, json="session-token")
        if request.method == "GET":
            assert request.headers["vmware-api-session-id"] == "session-token"
            return httpx.Response(200, json=[{"vm": "vm-1", "name": "app", "power_state": "POWERED_ON", "cpu_count": 2, "memory_size_MiB": 4096}])
        assert request.method == "DELETE"
        return httpx.Response(200)

    rows = VmwareAdapter(transport=httpx.MockTransport(handler)).list_resources()
    assert [request.method for request in requests] == ["POST", "GET", "DELETE"]
    assert rows[0]["memory_mb"] == 4096


def test_missing_credentials_fail_without_network(monkeypatch):
    for name in ("M365_TENANT_ID", "M365_CLIENT_ID", "M365_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    adapter = Microsoft365Adapter(transport=httpx.MockTransport(lambda request: pytest.fail("unexpected network request")))
    with pytest.raises(AdapterConfigurationError, match="M365_TENANT_ID"):
        adapter.list_resources()


def test_standalone_mcp_server_exposes_the_real_vendor_connector():
    from packages.mcp.mcp_server import TOOLS, vendor_resources_list

    assert TOOLS["vendor_resources_list"] is vendor_resources_list
    with pytest.raises(ValueError, match="unsupported vendor"):
        vendor_resources_list("not-a-vendor")
