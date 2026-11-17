# ProofOS Agent 2

The endpoint agent for ProofOS. It runs as a system service on Windows, Linux
and macOS, reports health and inventory, and executes commands that operators
push from the console. It refuses any command the server did not sign.

## What it does

| Capability | How |
| --- | --- |
| Instant command delivery | A WebSocket push channel (`/v1/agent/ws`) notifies the agent the moment a job is queued. If the channel drops, the agent falls back to polling and reconnects with backoff. |
| Signed jobs only | Every job is an Ed25519-signed envelope. The agent pins the server key at enrollment and checks the signature, purpose, device id, expiry (24 h) and command hash. It also refuses replays, because run ids are recorded on disk before execution, so a job runs at most once. |
| Live output | Output streams to the console while the command runs, over the push channel or HTTP. |
| Cancel and timeouts | The operator can cancel; timeouts kill the whole process tree. Exit 130 = cancelled, 124 = timed out, 126 = refused. |
| Interpreters | The OS default shell (`cmd` / `sh`). A first line of `#proofos:shell=powershell` (or `pwsh`, `bash`, `python`) selects another interpreter. |
| Concurrency | Up to 4 jobs at once (`max_concurrency`). |
| Offline tolerance | Results that cannot be delivered are kept in `state/spool` and sent when the server is back. Jobs queued while the agent is off run when it reconnects. |
| Local control | `proofos-agent lockdown on` blocks remote execution on this machine. `allow_commands: false` and `deny_patterns` (regexes) in the config do the same by rule. The server cannot override these. |
| Self-update | Every 6 hours the agent checks `/v1/agent/release`. It installs a newer build only if both the SHA-256 and the server's signature over the release manifest verify, then exits with code 75 so the service manager restarts it on the new version. |
| Inventory | Hardware, OS, disks, network, installed software (with Debian/Ubuntu source packages for vulnerability matching), pending reboot. |
| Service | systemd unit, launchd daemon, or a Windows scheduled task that runs as SYSTEM at boot and restarts on failure. |

## Install

The console's **Install agent** panel gives a ready-to-paste command with the
device's id, secret and the pinned server key. It does this:

```bash
curl -fsSL https://proofos.example/v1/agent/download -o proofos-agent.pyz
sudo python3 -m pip install httpx psutil websockets cryptography
sudo python3 proofos-agent.pyz enroll --api https://proofos.example --device-id 12 --token <secret> --server-key <hex>
sudo python3 proofos-agent.pyz install-service
```

On Windows, run the same steps in an elevated PowerShell with `py` in place of
`sudo python3`.

Other commands: `status`, `run` (foreground), `lockdown on|off`,
`uninstall-service`, `version`. Configuration lives in
`/etc/proofos-agent/config.json`, `/Library/Application Support/ProofOS/agent/`
or `%ProgramData%\ProofOS\agent\`, and is readable only by root, SYSTEM or
Administrators.

## Build

```bash
python apps/agent/build.py           # reproducible proofos-agent.pyz, published to the API
python apps/agent/build.py --check   # CI: the published build must match the source
python apps/agent/build.py --binary  # optional standalone executable (needs PyInstaller)
python -m pytest apps/agent/tests
```

The build is byte-for-byte reproducible, so the SHA-256 the server signs can be
checked by rebuilding from source.

`python agent.py --api … --device-id … --token …` still works for development:
it runs the agent in the foreground and pins the server key on first contact.

## Not yet included

- Signed native installers (MSI / pkg / deb) and code-signed binaries. These need
  your code-signing certificates. Today the agent needs Python 3.10+ on the
  endpoint, or a PyInstaller build.
- Interactive remote shell or desktop (the console runs discrete commands).
