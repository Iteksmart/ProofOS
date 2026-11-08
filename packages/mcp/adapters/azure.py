"""Azure Resource Manager VM inventory using service-principal auth."""
from __future__ import annotations

import os
from urllib.parse import quote

from .base import AdapterConfigurationError, OAuthClientCredentialsAdapter


class AzureAdapter(OAuthClientCredentialsAdapter):
    vendor = "azure"
    tenant_env = "AZURE_TENANT_ID"
    client_id_env = "AZURE_CLIENT_ID"
    client_secret_env = "AZURE_CLIENT_SECRET"
    # Azure Resource Manager's audience requires the trailing slash before /.default.
    oauth_scope = "https://management.azure.com//.default"
    api_url = "https://management.azure.com"
    api_version = "2026-03-01"

    def list_resources(self) -> list[dict]:
        subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID", "").strip()
        if not subscription_id:
            raise AdapterConfigurationError("AZURE_SUBSCRIPTION_ID must be configured")
        token = self._get_access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        url = (
            f"{self.api_url}/subscriptions/{quote(subscription_id, safe='')}/providers/"
            f"Microsoft.Compute/virtualMachines"
        )
        # The List All endpoint's statusOnly=true option returns runtime status
        # for the full subscription inventory without a scale-set filter.
        params = {"api-version": self.api_version, "statusOnly": "true"}
        virtual_machines: list[dict] = []
        with self._http() as client:
            for _ in range(1000):
                response = client.get(url, headers=headers, params=params)
                response.raise_for_status()
                page = response.json()
                virtual_machines.extend(self.normalise(page))
                next_link = page.get("nextLink")
                if not next_link:
                    self._proof("vendor.azure.vms.list", {"count": len(virtual_machines)}, why={"reason": "Azure VM inventory sync"})
                    return virtual_machines
                url = self._safe_next_link(next_link, "management.azure.com")
                params = None
        raise RuntimeError("Azure Resource Manager exceeded the 1000-page safety limit")

    def normalise(self, raw: dict) -> list[dict]:
        result = []
        for vm in raw.get("value", []):
            if not isinstance(vm, dict):
                continue
            resource_group = ""
            parts = str(vm.get("id", "")).split("/")
            for index, part in enumerate(parts[:-1]):
                if part.lower() == "resourcegroups":
                    resource_group = parts[index + 1]
                    break
            properties = vm.get("properties") or {}
            instance_view = properties.get("instanceView") or {}
            statuses = instance_view.get("statuses") or []
            hardware_profile = properties.get("hardwareProfile") or {}
            storage_profile = properties.get("storageProfile") or {}
            os_disk = storage_profile.get("osDisk") or {}
            power_state = next(
                (status.get("displayStatus") for status in statuses if isinstance(status, dict) and str(status.get("code", "")).startswith("PowerState/")),
                None,
            )
            result.append(
                {
                    "id": vm.get("id"),
                    "name": vm.get("name"),
                    "location": vm.get("location"),
                    "resource_group": resource_group,
                    "size": hardware_profile.get("vmSize"),
                    "os_type": os_disk.get("osType"),
                    "power_state": power_state,
                    "source": self.vendor,
                }
            )
        return result
