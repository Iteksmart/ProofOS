"""Short-lived, single-use password reset email delivery."""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import quote

from app.core.config import get_settings
from app.core.security import create_password_reset_token

settings = get_settings()


def email_delivery_configured() -> bool:
    return bool(settings.smtp_host and (settings.smtp_from or settings.smtp_user))


def send_password_reset_email(user) -> None:
    if not email_delivery_configured():
        raise RuntimeError("SMTP email delivery is not configured")

    token = create_password_reset_token(user)
    reset_url = f"{settings.web_url.rstrip('/')}/#password_reset={quote(token)}"
    message = EmailMessage()
    message["Subject"] = "Reset your ProofOS password"
    message["From"] = settings.smtp_from or settings.smtp_user
    message["To"] = user.email
    message.set_content(
        "A password reset was requested for your ProofOS account.\n\n"
        f"Use this link within 20 minutes to choose a new password:\n{reset_url}\n\n"
        "If you did not request this, you can ignore this message."
    )

    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=10, context=ssl.create_default_context()
        ) as server:
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
        return

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
        server.starttls(context=ssl.create_default_context())
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(message)
