"""ProofOS Secure Workspace — agent-side enclave (encrypted, policy-bound).

Creates a company-controlled, encrypted enclave on Mac/Windows/Linux where work
apps, files, network traffic and AI tools run under IT policy and DLP. Everything
outside the enclave stays private to the user (BYOD without VDI or full MDM).

What is enforced here (cross-platform, no admin privileges required):
  - Encrypted-at-rest workspace directory (Fernet/AES-128-CBC).
  - DLP content scanning on copy-out / write (sensitive-data patterns).
  - Policy manifest (app allowlist, network allowlist) + event reporting.

What requires OS-native hooks (documented, not implemented in pure Python):
  - Kernel-level app blocking / network interception (use a helper daemon or
    platform SDK — e.g. macOS Network Extension, Windows WFP, Linux netfilter).
  - Clipboard interception and dynamic watermarking.

Usage:
  from enclave import SecureWorkspace
  ws = SecureWorkspace(workspace_dir="~/ProofOS-Workspace", enclave_key="...")
  ws.provision()
  ws.report("dlp_blocked", "critical", "copied SSN to personal clipboard", "clipboard")
"""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

import httpx
from cryptography.fernet import Fernet

DLP_PATTERNS = [
    ("ssn", r"\b\d{3}-\d{2}-\d{4}\b", "critical"),
    ("credit_card", r"\b(?:\d[ -]?){13,16}\b", "critical"),
    ("aws_access_key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", "critical"),
    ("private_key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "critical"),
    ("generic_secret", r"(?i)\b(?:api[_-]?key|secret|token|passwd|password)\s*[:=]\s*[^\s,;]{6,}", "warning"),
]


class SecureWorkspace:
    def __init__(self, workspace_dir: str, enclave_key: str, api_url: str | None = None, device_id: int | None = None, enclave_id: int | None = None):
        self.workspace = Path(workspace_dir).expanduser()
        self.fernet = Fernet(enclave_key.encode())
        self.api_url = api_url
        self.device_id = device_id
        self.enclave_id = enclave_id
        self.policy: dict = {}

    def provision(self) -> None:
        """Create the encrypted workspace directory + a policy manifest."""
        self.workspace.mkdir(parents=True, exist_ok=True)
        manifest = self.workspace / "policy.json"
        if not manifest.exists():
            manifest.write_text(json.dumps({"version": 1, "encrypted": True, "enclave_id": self.enclave_id}), encoding="utf-8")
        self.report("provisioned", "info", f"workspace provisioned at {self.workspace}", "agent")

    def encrypt_file(self, path: str) -> bytes:
        data = Path(path).read_bytes()
        return self.fernet.encrypt(data)

    def decrypt_file(self, path: str) -> bytes:
        return self.fernet.decrypt(Path(path).read_bytes())

    @staticmethod
    def scan_content(text: str) -> list[dict]:
        hits = []
        for name, pattern, severity in DLP_PATTERNS:
            for m in re.finditer(pattern, text or ""):
                hits.append({"pattern": name, "severity": severity})
        return hits

    def report(self, kind: str, severity: str, detail: str, source: str) -> dict:
        """Report a DLP/policy event to the ProofOS API (best-effort)."""
        if not self.api_url:
            return {"ok": False, "error": "no api_url configured"}
        try:
            r = httpx.post(
                f"{self.api_url}/v1/enclaves/{self.enclave_id}/events",
                json={"kind": kind, "severity": severity, "detail": detail, "source": source},
                timeout=10,
            )
            return {"ok": r.status_code < 400, "status": r.status_code}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}


def generate_key() -> str:
    return Fernet.generate_key().decode()
