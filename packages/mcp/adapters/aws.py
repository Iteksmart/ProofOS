from __future__ import annotations

import httpx

from .base import VendorAdapter


class AwsAdapter(VendorAdapter):
    """AWS EC2 instance sync via a thin REST gateway (SigV4 handled upstream)."""

    vendor = "aws"
    base_url_env = "AWS_BASE_URL"

    def list_resources(self) -> list[dict]:
        r = httpx.get(f"{self.base_url}/ec2/instances", headers=self._headers(), timeout=15)
        r.raise_for_status()
        items = self.normalise(r.json())
        self._proof("vendor.aws.instances.list", {"count": len(items)}, why={"reason": "AWS EC2 sync"})
        return items

    def normalise(self, raw: dict) -> list[dict]:
        out = []
        for res in raw.get("Reservations", []):
            for i in res.get("Instances", []):
                out.append(
                    {
                        "id": i.get("InstanceId"),
                        "name": next((t.get("Value") for t in i.get("Tags", []) if t.get("Key") == "Name"), ""),
                        "state": i.get("State", {}).get("Name"),
                        "type": i.get("InstanceType"),
                    }
                )
        return out
