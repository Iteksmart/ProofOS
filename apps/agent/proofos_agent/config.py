"""Agent configuration and on-disk locations, per operating system."""
from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import sys
import tempfile


def default_config_path() -> pathlib.Path:
    if override := os.getenv("PROOFOS_AGENT_CONFIG"):
        return pathlib.Path(override)
    if sys.platform.startswith("win"):
        return pathlib.Path(os.getenv("ProgramData", r"C:\ProgramData")) / "ProofOS" / "agent" / "config.json"
    if sys.platform == "darwin":
        return pathlib.Path("/Library/Application Support/ProofOS/agent/config.json")
    return pathlib.Path("/etc/proofos-agent/config.json")


def default_state_dir() -> pathlib.Path:
    if sys.platform.startswith("win"):
        return pathlib.Path(os.getenv("ProgramData", r"C:\ProgramData")) / "ProofOS" / "agent" / "state"
    if sys.platform == "darwin":
        return pathlib.Path("/Library/Application Support/ProofOS/agent/state")
    return pathlib.Path("/var/lib/proofos-agent")


@dataclasses.dataclass
class Config:
    api: str
    device_id: int
    token: str
    server_key: str  # hex Ed25519 public key pinned at enrollment
    state_dir: str = ""
    interval: int = 15
    max_concurrency: int = 4
    allow_commands: bool = True
    deny_patterns: list[str] = dataclasses.field(default_factory=list)
    auto_update: bool = True
    ca_bundle: str = ""  # path to a private CA bundle; empty = system trust store

    @property
    def state(self) -> pathlib.Path:
        return pathlib.Path(self.state_dir) if self.state_dir else default_state_dir()

    def verify(self):
        return self.ca_bundle or True

    @classmethod
    def load(cls, path: pathlib.Path) -> "Config":
        data = json.loads(path.read_text(encoding="utf-8"))
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: pathlib.Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_private(path, json.dumps(dataclasses.asdict(self), indent=2))


def write_private(path: pathlib.Path, text: str) -> None:
    """Write atomically, readable only by the owner (the device secret lives here)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        if not sys.platform.startswith("win"):
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    if sys.platform.startswith("win"):
        restrict_windows_acl(path)


def restrict_windows_acl(path: pathlib.Path) -> None:
    """Limit the file to its owner, SYSTEM and Administrators."""
    import subprocess

    subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", "*S-1-3-4:F", "*S-1-5-18:F", "*S-1-5-32-544:F"],
                   capture_output=True, check=False)
