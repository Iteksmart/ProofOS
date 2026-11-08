"""VMware vCenter VM inventory through the vSphere Automation REST API."""
from __future__ import annotations

import os
from urllib.parse import urlsplit

from .base import AdapterConfigurationError, VendorAdapter


class VmwareAdapter(VendorAdapter):
    vendor = "vmware"

    def list_resources(self) -> list[dict]:
        base_url = os.getenv("VMWARE_BASE_URL", "").strip().rstrip("/")
        username = os.getenv("VMWARE_USERNAME", "").strip()
        password = os.getenv("VMWARE_PASSWORD", "")
        self._require(("VMWARE_BASE_URL", base_url), ("VMWARE_USERNAME", username), ("VMWARE_PASSWORD", password))
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise AdapterConfigurationError("VMWARE_BASE_URL must use HTTPS")
        if parsed.username or parsed.password or not parsed.hostname or parsed.query or parsed.fragment:
            raise AdapterConfigurationError("VMWARE_BASE_URL must be an HTTPS vCenter origin without embedded credentials")
        endpoint = f"{base_url}/api/session"
        with self._http() as client:
            session_response = client.post(endpoint, auth=(username, password))
            session_response.raise_for_status()
            session_id = session_response.json()
            if not isinstance(session_id, str) or not session_id:
                raise RuntimeError("vCenter session response did not contain a session identifier")
            try:
                response = client.get(
                    f"{base_url}/api/vcenter/vm",
                    headers={"vmware-api-session-id": session_id, "Accept": "application/json"},
                )
                response.raise_for_status()
                resources = self.normalise(response.json())
                self._proof("vendor.vmware.vms.list", {"count": len(resources)}, why={"reason": "vCenter inventory sync"})
                return resources
            finally:
                # Session credentials are short-lived; always attempt explicit logout.
                try:
                    client.delete(endpoint, headers={"vmware-api-session-id": session_id})
                except Exception:
                    pass

    def _http(self):
        import httpx

        verify = os.getenv("VMWARE_CA_BUNDLE", "").strip() or True
        return httpx.Client(timeout=httpx.Timeout(30, connect=10), transport=self._transport, follow_redirects=False, verify=verify)

    def normalise(self, raw: list | dict) -> list[dict]:
        values = raw if isinstance(raw, list) else raw.get("value", [])
        return [
            {
                "id": vm.get("vm"),
                "name": vm.get("name"),
                "power_state": vm.get("power_state"),
                "cpu_count": vm.get("cpu_count"),
                "memory_mb": vm.get("memory_size_MiB"),
                "source": self.vendor,
            }
            for vm in values
            if isinstance(vm, dict)
        ]
