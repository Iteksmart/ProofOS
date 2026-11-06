"""Secret vault encryption (Fernet) — CyberArk PAM-style encrypted-at-rest secrets."""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

from app.core.config import get_settings

settings = get_settings()


def _key() -> bytes:
    raw = settings.vault_key or settings.jwt_secret
    return base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())


def encrypt(plaintext: str) -> str:
    return Fernet(_key()).encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return Fernet(_key()).decrypt(ciphertext.encode()).decode()
