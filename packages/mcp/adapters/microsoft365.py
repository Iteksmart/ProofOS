"""Microsoft 365 directory inventory through Microsoft Graph v1.0."""
from __future__ import annotations

from .base import OAuthClientCredentialsAdapter


class Microsoft365Adapter(OAuthClientCredentialsAdapter):
    vendor = "microsoft365"
    tenant_env = "M365_TENANT_ID"
    client_id_env = "M365_CLIENT_ID"
    client_secret_env = "M365_CLIENT_SECRET"
    oauth_scope = "https://graph.microsoft.com/.default"
    graph_url = "https://graph.microsoft.com/v1.0/users"

    def list_resources(self) -> list[dict]:
        token = self._get_access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        url = self.graph_url
        params = {"$select": "id,displayName,mail,userPrincipalName,accountEnabled", "$top": "999"}
        users: list[dict] = []
        with self._http() as client:
            for _ in range(1000):
                response = client.get(url, headers=headers, params=params)
                response.raise_for_status()
                page = response.json()
                users.extend(self.normalise(page))
                next_link = page.get("@odata.nextLink")
                if not next_link:
                    self._proof("vendor.m365.users.list", {"count": len(users)}, why={"reason": "Microsoft Graph directory sync"})
                    return users
                url = self._safe_next_link(next_link, "graph.microsoft.com")
                params = None
        raise RuntimeError("Microsoft Graph exceeded the 1000-page safety limit")

    def normalise(self, raw: dict) -> list[dict]:
        return [
            {
                "id": user.get("id"),
                "name": user.get("displayName"),
                "email": user.get("mail") or user.get("userPrincipalName"),
                "enabled": user.get("accountEnabled"),
                "source": self.vendor,
            }
            for user in raw.get("value", [])
            if isinstance(user, dict)
        ]
