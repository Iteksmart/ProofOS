from __future__ import annotations

import httpx

from .base import VendorAdapter


class AzureAdapter(VendorAdapter):
    """Azure Resource Manager VM sync."""

    vendor = "azure"
    base_url_env = "AZURE_BASE_URL"

    def list_resources(self) -> list[dict]:
        r = httpx.get(f"{self.base_url}/subscriptions/vms", headers=self._headers(), timeout=15)
        r.raise_for_status()
        items = self.normalise(r.json())
        self._proof("vendor.azure.vms.list", {"count": len(items)}, why={"reason": "Azure VM sync"})
        return items

    def normalise(self, raw: dict) -> list[dict]:
        return [
            {"id": v.get("id"), "name": v.get("name"), "location": v.get("location"),
             "resource_group": v.get("resourceGroup")}
            for v in raw.get("value", [])
        ]
