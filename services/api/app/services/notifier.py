"""Alert delivery — Slack webhook, SMTP email, or a generic webhook.

All deliveries are best-effort and never raise: alerting must not block or fail
the request that created the alert.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

import httpx

from app.core.config import get_settings
from app.services import fcm

settings = get_settings()


def send_alert(payload: dict, db=None) -> list[str]:
    """Deliver an alert payload via every configured channel. Returns channels used."""
    sent: list[str] = []

    if settings.alert_slack_webhook_url:
        try:
            httpx.post(
                settings.alert_slack_webhook_url,
                json={"text": f"*ProofOS alert* [{payload.get('severity')}] {payload.get('kind')}: {payload.get('message')}"},
                timeout=3.0,
            )
            sent.append("slack")
        except Exception:
            pass

    if settings.smtp_host and settings.smtp_to:
        try:
            msg = EmailMessage()
            msg["Subject"] = f"ProofOS {payload.get('severity')} alert: {payload.get('kind')}"
            msg["From"] = settings.smtp_from or settings.smtp_user
            msg["To"] = settings.smtp_to
            msg.set_content(str(payload))
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=5) as server:
                if settings.smtp_user:
                    server.starttls()
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
            sent.append("email")
        except Exception:
            pass

    if settings.alert_webhook_url:
        try:
            httpx.post(settings.alert_webhook_url, json=payload, timeout=3.0)
            sent.append("webhook")
        except Exception:
            pass

    if db is not None and fcm.configured() and payload.get("org_id"):
        try:
            from app.models.models import PushDevice

            tokens = db.query(PushDevice).filter(PushDevice.org_id == payload["org_id"]).all()
            for t in tokens:
                fcm.send_push(t.fcm_token, f"ProofOS {payload.get('severity', '')} alert", f"{payload.get('kind')}: {payload.get('message')}")
            if tokens:
                sent.append("fcm")
        except Exception:
            pass

    return sent
