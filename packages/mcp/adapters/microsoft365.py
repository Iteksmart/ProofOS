from __future__ import annotations

import httpx

from .base import VendorAdapter


class Microsoft365Adapter(VendorAdapter):
    """Microsoft Graph users/device sync (Microsoft 365)."""

    vendor = "microsoft365"
    base_url_env = "M365_BASE_URL"

    def list_resources(self) -> list[dict]:
        r = httpx.get(f"{self.base_url}/v1.0/users", headers=self._headers(), timeout=15)
        r.raise_for_status()
        items = self.normalise(r.json())
        self._proof("vendor.m365.users.list", {"count": len(items)}, why={"reason": "M365 users sync"})
        return items

    def normalise(self, raw: dict) -> list[dict]:
        return [
            {"id": u.get("id"), "name": u.get("displayName"), "email": u.get("mail") or u.get("userPrincipalName")}
            for u in raw.get("value", [])
        ]
