"""Firebase Cloud Messaging (FCM) push delivery via the HTTP v1 API."""
from __future__ import annotations

import json

import httpx
from google.auth.transport import requests as google_requests
from google.oauth2 import service_account

from app.core.config import get_settings

settings = get_settings()
FCM_SCOPE = ["https://www.googleapis.com/auth/firebase.messaging"]


def configured() -> bool:
    return bool(settings.fcm_project_id and settings.fcm_service_account_json)


def _load_sa() -> dict:
    raw = settings.fcm_service_account_json.strip()
    if raw.startswith("{") or raw.startswith("["):
        return json.loads(raw)
    with open(raw, encoding="utf-8") as f:
        return json.load(f)


def send_push(token: str, title: str, body: str, data: dict | None = None) -> dict:
    """Send one push message to an FCM device token (best-effort, never raises)."""
    if not configured():
        return {"ok": False, "error": "FCM not configured — set FCM_PROJECT_ID and FCM_SERVICE_ACCOUNT_JSON"}
    try:
        creds = service_account.Credentials.from_service_account_info(_load_sa(), scopes=FCM_SCOPE)
        creds.refresh(google_requests.Request())
        message: dict = {"token": token, "notification": {"title": title, "body": body}}
        if data:
            message["data"] = {k: str(v) for k, v in data.items()}
        r = httpx.post(
            f"https://fcm.googleapis.com/v1/projects/{settings.fcm_project_id}/messages:send",
            json={"message": message},
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=15,
        )
        if r.status_code != 200:
            return {"ok": False, "status": r.status_code, "error": r.text[:200]}
        return {"ok": True, "name": r.json().get("name")}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
