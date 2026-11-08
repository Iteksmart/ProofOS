"""DLP (Data Loss Prevention) detection — sensitive-data pattern matching.

The secure-workspace agent scans content leaving the enclave and reports
matches; the actual secret text is never stored, only a redacted hint.
"""
from __future__ import annotations

import re

# (name, regex, severity)
PATTERNS: list[tuple[str, str, str]] = [
    ("ssn", r"\b\d{3}-\d{2}-\d{4}\b", "critical"),
    ("credit_card", r"\b(?:\d[ -]?){13,16}\b", "critical"),
    ("aws_access_key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", "critical"),
    ("google_api_key", r"\bAIza[0-9A-Za-z_\-]{35}\b", "critical"),
    ("private_key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "critical"),
    ("generic_secret", r"(?i)\b(?:api[_-]?key|secret|token|passwd|password)\s*[:=]\s*[^\s,;]{6,}", "warning"),
]


def _redact(s: str) -> str:
    if len(s) <= 8:
        return "*" * len(s)
    return s[:3] + "*" * (len(s) - 6) + s[-3:]


def detect(text: str) -> list[dict]:
    """Return detected sensitive-data patterns (with redacted hints), never the raw value."""
    if not text:
        return []
    hits: list[dict] = []
    for name, pattern, severity in PATTERNS:
        for m in re.finditer(pattern, text):
            hits.append({"pattern": name, "severity": severity, "match": _redact(m.group(0))})
    return hits


def has_sensitive(text: str) -> bool:
    return bool(detect(text))
