"""Vendor adapters — thin translation: vendor REST → ProofOS canonical → proof emit.

Each adapter is a stub against a vendor gateway/base URL. No vendor secrets are
stored; tokens come from env (VENDOR_TOKEN) or are passed in. Every adapter can
emit a ProofOS proof record so the sync is auditable.
"""
from __future__ import annotations

import os

import httpx


class VendorAdapter:
    """Base for a vendor adapter.

    Subclasses set `vendor` (machine name) and `base_url_env` (env var holding the
    gateway base URL), then implement `list_resources()` and `normalise()`.
    """

    vendor: str = "unknown"
    base_url_env: str = ""

    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        self.base_url = (base_url or os.getenv(self.base_url_env, "")).rstrip("/")
        self.token = token or os.getenv(f"{self.vendor.upper().replace('-', '_')}_TOKEN", "")
        self.api = os.getenv("PROOFOS_API_URL", "http://localhost:8000").rstrip("/")
        self.proofos_token = os.getenv("PROOFOS_TOKEN", "")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def health(self) -> dict:
        if not self.base_url:
            return {"vendor": self.vendor, "ok": False, "error": "not configured (set base_url env)"}
        try:
            r = httpx.get(f"{self.base_url}/health", headers=self._headers(), timeout=5)
            return {"vendor": self.vendor, "ok": r.status_code < 500, "status": r.status_code}
        except Exception as e:  # noqa: BLE001 - surface connectivity issues
            return {"vendor": self.vendor, "ok": False, "error": str(e)}

    def normalise(self, raw: dict) -> list[dict]:
        """Map vendor payload → ProofOS canonical list."""
        return raw.get("value", raw if isinstance(raw, list) else [])

    def list_resources(self) -> list[dict]:
        raise NotImplementedError

    def _proof(self, what: str, payload: dict, where: dict | None = None, why: dict | None = None) -> dict | None:
        """Emit a proof record for this sync (no token → no proof, but no silent fail)."""
        if not self.proofos_token:
            return None
        body = {
            "what": what,
            "payload": payload,
            "who": {"actor_id": f"adapter:{self.vendor}", "actor_type": "system"},
            "where": where or {"vendor": self.vendor},
            "why": why or {"reason": "vendor sync"},
        }
        r = httpx.post(
            f"{self.api}/v1/proof/emit",
            headers={"Authorization": f"Bearer {self.proofos_token}"},
            json=body,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
