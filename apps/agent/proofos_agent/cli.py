"""proofos-agent command line.

  proofos-agent enroll --api URL --device-id N --token SECRET [--server-key HEX]
  proofos-agent install-service | uninstall-service
  proofos-agent run                 run in the foreground (what the service executes)
  proofos-agent status              show configuration and connectivity
  proofos-agent lockdown on|off     locally block or allow remote execution
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import logging.handlers
import pathlib
import sys

import httpx

from proofos_agent import __version__
from proofos_agent.config import Config, default_config_path


def _logging(state_dir: pathlib.Path | None, verbose: bool) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if state_dir:
        try:
            state_dir.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.handlers.RotatingFileHandler(state_dir / "agent.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"))
        except OSError:
            pass
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(threadName)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)


def fingerprint(key_hex: str) -> str:
    digest = hashlib.sha256(bytes.fromhex(key_hex)).hexdigest()
    return ":".join(digest[i:i + 4] for i in range(0, 32, 4))


def enroll(args) -> int:
    path = pathlib.Path(args.config)
    verify = args.ca_bundle or True
    with httpx.Client(base_url=args.api.rstrip("/"), timeout=20, verify=verify) as client:
        key = client.get("/v1/agent/server-key").raise_for_status().json()["public_key"]
        if args.server_key and args.server_key.lower() != key.lower():
            print("The server's signing key does not match --server-key. Refusing to enroll.", file=sys.stderr)
            return 2
        if not args.server_key:
            print(f"Pinning server signing key {fingerprint(key)} (trust on first use). Pass --server-key to pin it explicitly.")
        beat = client.post(f"/v1/devices/{args.device_id}/heartbeat", headers={"X-Agent-Token": args.token},
                           json={"status": "online", "agent_version": __version__})
        if beat.status_code != 200:
            print(f"The server rejected the device credentials ({beat.status_code}). Check the device id and secret.", file=sys.stderr)
            return 3
    Config(api=args.api, device_id=args.device_id, token=args.token, server_key=key, ca_bundle=args.ca_bundle or "",
           state_dir=args.state_dir or "").save(path)
    print(f"Enrolled device {args.device_id}. Configuration written to {path}.")
    return 0


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="proofos-agent", description="ProofOS endpoint agent")
    ap.add_argument("--config", default=str(default_config_path()))
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="command", required=True)
    e = sub.add_parser("enroll", help="register this endpoint with a ProofOS server")
    e.add_argument("--api", required=True)
    e.add_argument("--device-id", type=int, required=True)
    e.add_argument("--token", required=True)
    e.add_argument("--server-key", default="", help="expected server signing key (hex); recommended")
    e.add_argument("--ca-bundle", default="")
    e.add_argument("--state-dir", default="")
    sub.add_parser("run", help="run the agent in the foreground")
    sub.add_parser("install-service", help="install and start as a system service")
    sub.add_parser("uninstall-service", help="stop and remove the system service")
    sub.add_parser("status", help="show configuration and server connectivity")
    lk = sub.add_parser("lockdown", help="block (on) or allow (off) remote execution on this endpoint")
    lk.add_argument("mode", choices=["on", "off"])
    sub.add_parser("version")
    args = ap.parse_args(argv)

    if args.command == "version":
        print(__version__)
        return
    if args.command == "enroll":
        _logging(None, args.verbose)
        raise SystemExit(enroll(args))
    path = pathlib.Path(args.config)
    if args.command == "uninstall-service":
        from proofos_agent import service

        print(service.uninstall())
        return
    if not path.exists():
        raise SystemExit(f"No configuration at {path}. Run 'proofos-agent enroll' first.")
    cfg = Config.load(path)
    if args.command == "install-service":
        from proofos_agent import service

        print(service.install(path))
        return
    if args.command == "lockdown":
        from proofos_agent.state import State

        State(cfg.state).set_lockdown(args.mode == "on")
        print("Remote execution is now " + ("LOCKED on this endpoint." if args.mode == "on" else "allowed."))
        return
    if args.command == "status":
        from proofos_agent.state import State

        state = State(cfg.state)
        print(f"version       {__version__}\nserver        {cfg.api}\ndevice        {cfg.device_id}\nserver key    {fingerprint(cfg.server_key)}"
              f"\nlockdown      {'on' if state.locked else 'off'}\nspooled       {len(state.spooled())} result(s)")
        try:
            r = httpx.get(cfg.api.rstrip("/") + "/v1/agent/server-key", timeout=10, verify=cfg.verify())
            match = r.json().get("public_key") == cfg.server_key
            print(f"reachable     yes ({'key matches' if match else 'KEY CHANGED - jobs will be refused'})")
        except httpx.HTTPError as exc:
            print(f"reachable     no ({type(exc).__name__})")
        return
    _logging(cfg.state, args.verbose)
    from proofos_agent.daemon import Agent

    agent = Agent(cfg)
    try:
        code = agent.run_forever()
    except KeyboardInterrupt:
        agent.stop.set()
        code = 0
    raise SystemExit(code)
