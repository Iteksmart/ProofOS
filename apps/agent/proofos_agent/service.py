"""Install the agent as an always-on system service (systemd, launchd, Windows Task Scheduler)."""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from xml.sax.saxutils import escape

from proofos_agent.updater import RESTART_EXIT, running_archive

LABEL = "dev.proofos.agent"
TASK = "ProofOS Agent"


def install_dir() -> pathlib.Path:
    if sys.platform.startswith("win"):
        return pathlib.Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "ProofOS" / "Agent"
    if sys.platform == "darwin":
        return pathlib.Path("/usr/local/proofos-agent")
    return pathlib.Path("/opt/proofos-agent")


def _install_payload() -> pathlib.Path:
    source = running_archive()
    if source is None:
        raise SystemExit("install-service must be run from proofos-agent.pyz (download it from your ProofOS server)")
    target = install_dir() / "proofos-agent.pyz"
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    return target


def _run(argv: list[str]) -> None:
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"{' '.join(argv[:3])} failed: {(result.stderr or result.stdout).strip()}")


def systemd_unit(python: str, pyz: pathlib.Path, config: pathlib.Path) -> str:
    return f"""[Unit]
Description=ProofOS endpoint agent
After=network-online.target
Wants=network-online.target

[Service]
ExecStart={python} {pyz} run --config {config}
Restart=always
RestartSec=5
SuccessExitStatus={RESTART_EXIT}
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""


def launchd_plist(python: str, pyz: pathlib.Path, config: pathlib.Path) -> str:
    args = "".join(f"<string>{escape(str(a))}</string>" for a in (python, pyz, "run", "--config", config))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>{LABEL}</string>
<key>ProgramArguments</key><array>{args}</array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>StandardErrorPath</key><string>/var/log/proofos-agent.log</string>
</dict></plist>
"""


def windows_task_xml(python: str, pyz: pathlib.Path, config: pathlib.Path) -> str:
    arguments = escape(f'"{pyz}" run --config "{config}"')
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>ProofOS endpoint agent</Description></RegistrationInfo>
  <Triggers><BootTrigger><Enabled>true</Enabled></BootTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
    <StartWhenAvailable>true</StartWhenAvailable>
    <Hidden>true</Hidden>
  </Settings>
  <Actions Context="Author"><Exec><Command>{escape(python)}</Command><Arguments>{arguments}</Arguments></Exec></Actions>
</Task>
"""


def install(config: pathlib.Path) -> str:
    pyz = _install_payload()
    python = sys.executable
    if sys.platform.startswith("win"):
        python = python.replace("python.exe", "pythonw.exe") if os.path.exists(python.replace("python.exe", "pythonw.exe")) else python
        fd, xml = tempfile.mkstemp(suffix=".xml")
        with os.fdopen(fd, "w", encoding="utf-16") as handle:
            handle.write(windows_task_xml(python, pyz, config))
        try:
            _run(["schtasks", "/Create", "/TN", TASK, "/XML", xml, "/F"])
        finally:
            os.unlink(xml)
        _run(["schtasks", "/Run", "/TN", TASK])
        return f"Installed scheduled task '{TASK}' (runs as SYSTEM at boot, restarts on failure)."
    if sys.platform == "darwin":
        plist = pathlib.Path(f"/Library/LaunchDaemons/{LABEL}.plist")
        plist.write_text(launchd_plist(python, pyz, config), encoding="utf-8")
        os.chmod(plist, 0o644)
        subprocess.run(["launchctl", "bootout", f"system/{LABEL}"], capture_output=True)
        _run(["launchctl", "bootstrap", "system", str(plist)])
        return f"Installed launch daemon {LABEL}."
    unit = pathlib.Path("/etc/systemd/system/proofos-agent.service")
    unit.write_text(systemd_unit(python, pyz, config), encoding="utf-8")
    _run(["systemctl", "daemon-reload"])
    _run(["systemctl", "enable", "--now", "proofos-agent.service"])
    return "Installed and started systemd service proofos-agent."


def uninstall() -> str:
    if sys.platform.startswith("win"):
        subprocess.run(["schtasks", "/End", "/TN", TASK], capture_output=True)
        _run(["schtasks", "/Delete", "/TN", TASK, "/F"])
        return f"Removed scheduled task '{TASK}'."
    if sys.platform == "darwin":
        subprocess.run(["launchctl", "bootout", f"system/{LABEL}"], capture_output=True)
        pathlib.Path(f"/Library/LaunchDaemons/{LABEL}.plist").unlink(missing_ok=True)
        return f"Removed launch daemon {LABEL}."
    subprocess.run(["systemctl", "disable", "--now", "proofos-agent.service"], capture_output=True)
    pathlib.Path("/etc/systemd/system/proofos-agent.service").unlink(missing_ok=True)
    subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
    return "Removed systemd service proofos-agent."
