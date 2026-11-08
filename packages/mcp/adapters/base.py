"""Shared transport and proof helpers for first-party vendor API adapters."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv


class AdapterConfigurationError(RuntimeError):
    """Raised when the connector is missing a required credential or setting."""


class VendorAdapter:
    vendor: str = "unknown"

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        # Make the repo-level .env usable for the standalone MCP server while
        # allowing explicit process environment values to take precedence.
        load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)
        self.api = os.getenv("PROOFOS_API_URL", "http://localhost:8000").rstrip("/")
        self.proofos_token = os.getenv("PROOFOS_TOKEN", "")
        self._transport = transport

    def _http(self) -> httpx.Client:
        return httpx.Client(timeout=httpx.Timeout(30, connect=10), transport=self._transport, follow_redirects=False)

    @staticmethod
    def _require(*values: tuple[str, str]) -> None:
        missing = [label for label, value in values if not value or not value.strip()]
        if missing:
            raise AdapterConfigurationError(f"{', '.join(missing)} must be configured")

    @staticmethod
    def _safe_next_link(link: str, expected_host: str) -> str:
        """Accept provider pagination URLs only on that provider's HTTPS host."""
        parsed = urlsplit(link)
        if parsed.scheme != "https" or parsed.hostname != expected_host or parsed.username or parsed.password:
            raise RuntimeError("vendor returned an unsafe pagination URL")
        if parsed.port not in (None, 443):
            raise RuntimeError("vendor returned an unsafe pagination URL")
        return link

    def _proof(self, what: str, payload: dict, where: dict | None = None, why: dict | None = None) -> dict | None:
        """Emit a proof event after successful vendor sync when ProofOS is configured."""
        if not self.proofos_token:
            return None
        body = {
            "what": what,
            "payload": payload,
            "who": {"actor_id": f"adapter:{self.vendor}", "actor_type": "system"},
            "where": where or {"vendor": self.vendor},
            "why": why or {"reason": "vendor sync"},
        }
        with self._http() as client:
            response = client.post(
                f"{self.api}/v1/proof/emit",
                headers={"Authorization": f"Bearer {self.proofos_token}"},
                json=body,
            )
            response.raise_for_status()
            return response.json()


class OAuthClientCredentialsAdapter(VendorAdapter):
    """Microsoft Entra confidential-client token acquisition with short cache."""

    tenant_env: str = ""
    client_id_env: str = ""
    client_secret_env: str = ""
    oauth_scope: str = ""

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        super().__init__(transport=transport)
        self._access_token: str = ""
        self._token_expires_at = 0.0

    def _get_access_token(self) -> str:
        tenant = os.getenv(self.tenant_env, "").strip()
        client_id = os.getenv(self.client_id_env, "").strip()
        client_secret = os.getenv(self.client_secret_env, "")
        self._require(
            (self.tenant_env, tenant),
            (self.client_id_env, client_id),
            (self.client_secret_env, client_secret),
        )
        if self._access_token and time.monotonic() < self._token_expires_at - 60:
            return self._access_token

        if not re.fullmatch(r"[A-Za-z0-9.-]+", tenant):
            raise AdapterConfigurationError(f"{self.tenant_env} contains an invalid tenant identifier")
        token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
        with self._http() as client:
            response = client.post(
                token_url,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": self.oauth_scope,
                    "grant_type": "client_credentials",
                },
            )
            response.raise_for_status()
            payload = response.json()
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise RuntimeError(f"{self.vendor} OAuth response did not contain an access token")
        self._access_token = token
        self._token_expires_at = time.monotonic() + int(payload.get("expires_in", 3600))
        return token
