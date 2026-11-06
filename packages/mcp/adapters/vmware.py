from __future__ import annotations

import httpx

from .base import VendorAdapter


class VmwareAdapter(VendorAdapter):
    """VMware vSphere VM sync via vCenter REST gateway."""

    vendor = "vmware"
    base_url_env = "VMWARE_BASE_URL"

    def list_resources(self) -> list[dict]:
        r = httpx.get(f"{self.base_url}/api/vcenter/vm", headers=self._headers(), timeout=15)
        r.raise_for_status()
        items = self.normalise(r.json())
        self._proof("vendor.vmware.vms.list", {"count": len(items)}, why={"reason": "vCenter VM sync"})
        return items

    def normalise(self, raw: dict) -> list[dict]:
        return [
            {"id": v.get("vm"), "name": v.get("name"), "power_state": v.get("power_state"),
             "cpu_count": v.get("cpu_count"), "memory": v.get("memory_size_MiB")}
            for v in raw if isinstance(v, dict)
        ]
