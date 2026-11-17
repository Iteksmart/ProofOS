"""Self-update: only a build whose hash and server signature both verify is installed."""
from __future__ import annotations

import hashlib
import logging
import os
import pathlib
import sys

import httpx

from proofos_agent import __version__, jobs

log = logging.getLogger("proofos-agent")
RESTART_EXIT = 75  # service managers restart the agent on this code


def _parse(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in version.split("."))
    except ValueError:
        return ()


def running_archive() -> pathlib.Path | None:
    """The .pyz this agent runs from, if any (source checkouts and frozen binaries do not self-update)."""
    archive = getattr(sys.modules.get("proofos_agent"), "__loader__", None)
    path = getattr(archive, "archive", None)
    return pathlib.Path(path) if path and str(path).endswith(".pyz") else None


def apply_if_newer(client: httpx.Client, server_key: str, target: pathlib.Path | None = None) -> bool:
    target = target or running_archive()
    if target is None:
        return False
    r = client.get("/v1/agent/release")
    if r.status_code != 200:
        return False
    info = r.json()
    if _parse(info.get("version", "")) <= _parse(__version__):
        return False
    manifest = {k: info.get(k) for k in ("purpose", "version", "sha256", "size")}
    if manifest["purpose"] != jobs.RELEASE_PURPOSE or not jobs.verify_signature(manifest, info.get("signature", ""), server_key):
        log.warning("release %s rejected: signature does not verify against the pinned key", info.get("version"))
        return False
    data = client.get("/v1/agent/download", timeout=120).content
    if hashlib.sha256(data).hexdigest() != manifest["sha256"] or len(data) != manifest["size"]:
        log.warning("release %s rejected: download does not match the signed hash", info.get("version"))
        return False
    staged = target.with_suffix(".pyz.new")
    staged.write_bytes(data)
    os.replace(staged, target)
    log.info("updated agent %s -> %s", __version__, manifest["version"])
    return True
