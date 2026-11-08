"""Google Workspace directory sync using service-account domain delegation."""
from __future__ import annotations

import json
import os
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

from .base import AdapterConfigurationError, VendorAdapter


class GoogleWorkspaceAdapter(VendorAdapter):
    vendor = "google-workspace"
    directory_url = "https://admin.googleapis.com/admin/directory/v1/users"
    scopes = ("https://www.googleapis.com/auth/admin.directory.user.readonly",)

    def __init__(self, *, transport=None, session=None) -> None:
        super().__init__(transport=transport)
        self._session_override = session

    def _authorized_session(self):
        if self._session_override is not None:
            return self._session_override
        service_account_file = os.getenv("GOOGLE_WORKSPACE_SERVICE_ACCOUNT_FILE", "").strip()
        service_account_json = os.getenv("GOOGLE_WORKSPACE_SERVICE_ACCOUNT_JSON", "").strip()
        admin_email = os.getenv("GOOGLE_WORKSPACE_ADMIN_EMAIL", "").strip()
        self._require(("GOOGLE_WORKSPACE_ADMIN_EMAIL", admin_email))
        if service_account_file:
            try:
                info = json.loads(Path(service_account_file).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise AdapterConfigurationError("GOOGLE_WORKSPACE_SERVICE_ACCOUNT_FILE could not be read as JSON") from exc
        elif service_account_json:
            try:
                info = json.loads(service_account_json)
            except json.JSONDecodeError as exc:
                raise AdapterConfigurationError("GOOGLE_WORKSPACE_SERVICE_ACCOUNT_JSON must contain valid JSON") from exc
        else:
            raise AdapterConfigurationError(
                "Set GOOGLE_WORKSPACE_SERVICE_ACCOUNT_FILE or GOOGLE_WORKSPACE_SERVICE_ACCOUNT_JSON"
            )
        credentials = service_account.Credentials.from_service_account_info(info, scopes=self.scopes).with_subject(admin_email)
        return AuthorizedSession(credentials)

    def list_resources(self) -> list[dict]:
        customer = os.getenv("GOOGLE_WORKSPACE_CUSTOMER_ID", "my_customer").strip() or "my_customer"
        session = self._authorized_session()
        users: list[dict] = []
        params = {"customer": customer, "maxResults": 500, "orderBy": "email"}
        try:
            for _ in range(1000):
                response = session.get(self.directory_url, params=params, timeout=30)
                response.raise_for_status()
                page = response.json()
                users.extend(self.normalise(page))
                page_token = page.get("nextPageToken")
                if not page_token:
                    self._proof("vendor.google.users.list", {"count": len(users)}, why={"reason": "Google Workspace directory sync"})
                    return users
                params = {"customer": customer, "maxResults": 500, "orderBy": "email", "pageToken": page_token}
            raise RuntimeError("Google Admin Directory exceeded the 1000-page safety limit")
        finally:
            if self._session_override is None:
                session.close()

    def normalise(self, raw: dict) -> list[dict]:
        return [
            {
                "id": user.get("id"),
                "name": (user.get("name") or {}).get("fullName"),
                "email": user.get("primaryEmail"),
                "suspended": user.get("suspended"),
                "source": self.vendor,
            }
            for user in raw.get("users", [])
            if isinstance(user, dict)
        ]
