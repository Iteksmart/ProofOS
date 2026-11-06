from __future__ import annotations

import httpx

from .base import VendorAdapter


class GoogleWorkspaceAdapter(VendorAdapter):
    """Google Workspace directory sync (Admin SDK users)."""

    vendor = "google-workspace"
    base_url_env = "GOOGLE_WORKSPACE_BASE_URL"

    def list_resources(self) -> list[dict]:
        r = httpx.get(f"{self.base_url}/admin/directory/v1/users", headers=self._headers(), timeout=15)
        r.raise_for_status()
        items = self.normalise(r.json())
        self._proof("vendor.google.users.list", {"count": len(items)}, why={"reason": "Google Workspace users sync"})
        return items

    def normalise(self, raw: dict) -> list[dict]:
        return [
            {"id": u.get("id"), "name": u.get("name", {}).get("fullName"), "email": u.get("primaryEmail")}
            for u in raw.get("users", [])
        ]
