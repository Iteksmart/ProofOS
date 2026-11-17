"""Verify signed job envelopes before anything is executed."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

JOB_PURPOSE = "proofos.agent.job.v1"
RELEASE_PURPOSE = "proofos.agent.release.v1"


class Rejected(Exception):
    """A job that must not run. The message is reported back to the server."""


def canonical(obj: dict) -> bytes:
    # Must match the server's encoding byte for byte.
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


def verify_signature(obj: dict, signature_b64: str, public_key_hex: str) -> bool:
    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        key.verify(base64.b64decode(signature_b64, validate=True), canonical(obj))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def check(job: dict, *, public_key_hex: str, device_id: int, seen: set[int], now: dt.datetime | None = None) -> dict:
    """Return the verified envelope, or raise Rejected with the reason."""
    env, sig = job.get("envelope"), job.get("signature", "")
    if not isinstance(env, dict) or not isinstance(sig, str):
        raise Rejected("malformed job")
    if not verify_signature(env, sig, public_key_hex):
        raise Rejected("signature does not verify against the pinned server key")
    if env.get("purpose") != JOB_PURPOSE:
        raise Rejected("envelope is not an agent job")
    if env.get("device_id") != device_id:
        raise Rejected("job is addressed to another device")
    body = env.get("body")
    if not isinstance(body, str) or hashlib.sha256(body.encode()).hexdigest() != env.get("body_sha256"):
        raise Rejected("command does not match its signed hash")
    try:
        expires = dt.datetime.fromisoformat(env["expires_at"])
    except (KeyError, ValueError) as exc:
        raise Rejected("missing expiry") from exc
    if (now or dt.datetime.now(dt.timezone.utc)) > expires:
        raise Rejected("job expired before it could run")
    if env.get("run_id") in seen:
        raise Rejected("job was already executed (replay)")
    return env


def policy_block(body: str, *, allow_commands: bool, deny_patterns: list[str], locked: bool) -> str | None:
    """Local controls the endpoint owner keeps regardless of what the server asks."""
    if locked:
        return "remote execution is locked on this endpoint (proofos-agent lockdown off to allow)"
    if not allow_commands:
        return "remote execution is disabled in the agent configuration"
    for pattern in deny_patterns:
        try:
            if re.search(pattern, body, re.IGNORECASE):
                return f"blocked by local deny rule: {pattern}"
        except re.error:
            continue
    return None
