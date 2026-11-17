"""Compatibility entry point for the 1.x command line.

  python agent.py --api http://localhost:8000 --device-id 1 --token <device_secret>

Runs the 2.x agent in the foreground with an in-memory configuration. The
server signing key is pinned on first contact (trust on first use). For
production use the packaged agent instead:

  python proofos-agent.pyz enroll --api URL --device-id N --token SECRET --server-key HEX
  python proofos-agent.pyz install-service
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import httpx  # noqa: E402

from proofos_agent.cli import _logging, fingerprint  # noqa: E402
from proofos_agent.config import Config  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--device-id", type=int, default=1)
    ap.add_argument("--interval", type=int, default=15)
    ap.add_argument("--token", default=os.getenv("AGENT_TOKEN", ""), help="device secret (X-Agent-Token)")
    ap.add_argument("--server-key", default="", help="expected server signing key (hex)")
    ap.add_argument("--state-dir", default=str(pathlib.Path.home() / ".proofos-agent"))
    args = ap.parse_args()
    key = httpx.get(args.api.rstrip("/") + "/v1/agent/server-key", timeout=20).raise_for_status().json()["public_key"]
    if args.server_key and args.server_key.lower() != key.lower():
        raise SystemExit("server signing key does not match --server-key")
    cfg = Config(api=args.api, device_id=args.device_id, token=args.token, server_key=key, state_dir=args.state_dir, interval=args.interval)
    _logging(cfg.state, False)
    print(f"ProofOS agent: pinned server key {fingerprint(key)}")
    from proofos_agent.daemon import Agent

    raise SystemExit(Agent(cfg).run_forever())


if __name__ == "__main__":
    main()
