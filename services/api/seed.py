"""Dev seed: bootstrap org + admin + demo devices/tickets via API. Idempotent."""
from __future__ import annotations

import os
import sys

import httpx

API = os.getenv("API_URL", "http://localhost:8000")
ORG_NAME = os.getenv("ORG_NAME", "ProofOS Demo")


def main() -> None:
    r = httpx.post(f"{API}/v1/auth/bootstrap", json={"name": ORG_NAME}, timeout=10)
    r.raise_for_status()
    boot = r.json()
    token = boot["access_token"]
    org_id = boot["org"]["id"]
    h = {"Authorization": f"Bearer {token}"}
    print(f"org={org_id} token ok")

    # demo device
    dev = httpx.post(
        f"{API}/v1/devices",
        headers=h,
        json={"org_id": org_id, "hostname": "demo-ws-01", "os": "Windows 11", "ip": "10.0.0.11"},
        timeout=10,
    )
    if dev.status_code in (200, 201):
        print(f"device id={dev.json().get('id')}")
        httpx.post(f"{API}/v1/devices/{dev.json()['id']}/heartbeat", json={"cpu": 12.0, "disk": 44.0, "mem": 58.0, "status": "online"}, timeout=10)

    # demo ticket
    tk = httpx.post(
        f"{API}/v1/tickets",
        headers=h,
        json={"org_id": org_id, "title": "Demo: printer offline", "body": "User reports cannot print.", "priority": "normal"},
        timeout=10,
    )
    print(f"ticket status={tk.status_code} {tk.text[:200]}")

    # proof chain
    chain = httpx.get(f"{API}/v1/proof/chain", headers=h, timeout=10)
    print(f"chain: {chain.json()}")
    print("seed done")


if __name__ == "__main__":
    main()
