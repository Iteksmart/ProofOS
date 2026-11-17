"""Patch scan parsing, software deployment and network discovery."""
from __future__ import annotations

from app.services import discovery, patch_scan

APT = """Listing... Done
openssl/jammy-updates,jammy-security 3.0.2-0ubuntu1.15 amd64 [upgradable from: 3.0.2-0ubuntu1.14]
curl/jammy-updates 7.81.0-1ubuntu1.17 amd64 [upgradable from: 7.81.0-1ubuntu1.16]
"""
WINGET = """Name                          Id                        Version       Available     Source
----------------------------------------------------------------------------------------------
Mozilla Firefox (x64 en-US)   Mozilla.Firefox           131.0         132.0.1       winget
7-Zip 23.01 (x64)             7zip.7zip                 23.01         24.09         winget
2 upgrades available.
"""
YUM = """Last metadata expiration check: 0:10:01 ago.

kernel.x86_64                     5.14.0-427.el9                     baseos
openssl.x86_64                    1:3.0.7-28.el9                     rhel-9-security-rpms
"""
ARP_WINDOWS = """
Interface: 10.0.0.20 --- 0x7
  Internet Address      Physical Address      Type
  10.0.0.1              00-11-22-33-44-55     dynamic
  10.0.0.45             a4-5e-60-0b-1c-2d     dynamic
  10.0.0.255            ff-ff-ff-ff-ff-ff     static
  224.0.0.22            01-00-5e-00-00-16     static
"""
IP_NEIGH = """10.0.0.1 dev eth0 lladdr 00:11:22:33:44:55 REACHABLE
10.0.0.77 dev eth0 lladdr 3c:22:fb:0a:0b:0c STALE
10.0.0.99 dev eth0  FAILED
fe80::1 dev eth0 lladdr 00:11:22:33:44:55 router STALE
"""


def test_parsers_handle_real_package_manager_output():
    apt = patch_scan.parse(APT)
    assert [(p["name"], p["category"], p["available_version"]) for p in apt] == [("openssl", "security", "3.0.2-0ubuntu1.15"), ("curl", "os", "7.81.0-1ubuntu1.17")]
    assert apt[0]["current_version"] == "3.0.2-0ubuntu1.14" and apt[0]["severity"] == "important"
    win = patch_scan.parse(WINGET)
    assert [(p["name"], p["current_version"], p["available_version"]) for p in win] == [("Mozilla Firefox (x64 en-US) [Mozilla.Firefox]", "131.0", "132.0.1"), ("7-Zip 23.01 (x64) [7zip.7zip]", "23.01", "24.09")]
    yum = patch_scan.parse(YUM)
    assert [(p["name"], p["category"]) for p in yum] == [("kernel", "os"), ("openssl", "security")]
    assert patch_scan.parse("No packages need updating.") == []


def test_neighbour_parsing_filters_broadcast_multicast_and_failed():
    assert discovery.parse_neighbours(ARP_WINDOWS) == [{"ip": "10.0.0.1", "mac": "00:11:22:33:44:55"}, {"ip": "10.0.0.45", "mac": "a4:5e:60:0b:1c:2d"}]
    assert [r["ip"] for r in discovery.parse_neighbours(IP_NEIGH)] == ["10.0.0.1", "10.0.0.77"]
    assert discovery.parse_neighbours("? (192.168.1.9) at 0:1b:63:84:45:e6 on en0 ifscope [ethernet]") == [{"ip": "192.168.1.9", "mac": "00:1b:63:84:45:e6"}]


def test_scan_results_become_patch_records(auth_client):
    c, org_id, _ = auth_client
    dev = c.post("/v1/devices", json={"org_id": org_id, "hostname": "scan-host", "os": "Ubuntu 22.04"}).json()
    agent = {"X-Agent-Token": dev["device_secret"]}
    run = c.post(f"/v1/patches/scan?device_id={dev['id']}&org_id={org_id}").json()
    assert "apt list --upgradable" in run["command"]
    assert c.post(f"/v1/scripts/runs/{run['run_id']}/complete", headers=agent, json={"output": APT, "exit_code": 0}).status_code == 200
    patches = {p["name"]: p for p in c.get(f"/v1/patches?org_id={org_id}&device_id={dev['id']}").json()}
    assert set(patches) == {"openssl", "curl"} and patches["openssl"]["category"] == "security" and patches["openssl"]["approval"] == "unreviewed"

    # A rescan refreshes versions instead of duplicating, and a failed scan changes nothing.
    rerun = c.post(f"/v1/patches/scan?device_id={dev['id']}&org_id={org_id}").json()
    c.post(f"/v1/scripts/runs/{rerun['run_id']}/complete", headers=agent, json={"output": APT.replace("1.15", "1.16"), "exit_code": 0})
    patches = c.get(f"/v1/patches?org_id={org_id}&device_id={dev['id']}").json()
    assert len(patches) == 2 and next(p for p in patches if p["name"] == "openssl")["available_version"] == "3.0.2-0ubuntu1.16"
    failed = c.post(f"/v1/patches/scan?device_id={dev['id']}&org_id={org_id}").json()
    c.post(f"/v1/scripts/runs/{failed['run_id']}/complete", headers=agent, json={"output": "zzz/x 9 amd64 [upgradable from: 1]", "exit_code": 1})
    assert len(c.get(f"/v1/patches?org_id={org_id}&device_id={dev['id']}").json()) == 2
    assert "patch.scan.completed" in [p["what"] for p in c.get("/v1/proof?limit=200").json()]


def test_software_deployment_validates_packages(auth_client):
    c, org_id, _ = auth_client
    win = c.post("/v1/devices", json={"org_id": org_id, "hostname": "sw-win", "os": "Windows 11"}).json()
    lin = c.post("/v1/devices", json={"org_id": org_id, "hostname": "sw-lin", "os": "Ubuntu 24.04"}).json()
    r = c.post("/v1/fleet/bulk", json={"device_ids": [win["id"], lin["id"]], "action": "install_software", "package": "Mozilla.Firefox"})
    assert r.status_code == 200, r.text
    commands = {x["device_id"]: x["command"] for x in r.json()["results"]}
    assert commands[win["id"]].startswith("winget install --id Mozilla.Firefox --exact --silent")
    assert commands[lin["id"]].startswith("sudo apt-get install -y Mozilla.Firefox")
    assert "winget uninstall --id 7zip.7zip" in c.post("/v1/fleet/bulk", json={"device_ids": [win["id"]], "action": "uninstall_software", "package": "7zip.7zip"}).json()["results"][0]["command"]
    for bad in ["firefox; rm -rf /", "x && whoami", "$(id)", "a b", "", "-rf", "`id`", "pkg|sh"]:
        assert c.post("/v1/fleet/bulk", json={"device_ids": [lin["id"]], "action": "install_software", "package": bad}).status_code == 422, bad
    c.post("/v1/auth/users", json={"org_id": org_id, "email": "engineer-sw@proofos.dev", "password": "a-long-test-password", "role": "engineer"})
    eng = {"Authorization": "Bearer " + c.post("/v1/auth/login", json={"email": "engineer-sw@proofos.dev", "password": "a-long-test-password"}).json()["access_token"]}
    assert c.post("/v1/fleet/bulk", json={"device_ids": [lin["id"]], "action": "install_software", "package": "htop"}, headers=eng).status_code == 403


def test_network_discovery_marks_managed_and_unmanaged(auth_client):
    c, org_id, _ = auth_client
    scanner = c.post("/v1/devices", json={"org_id": org_id, "hostname": "scanner", "os": "Windows 11", "ip": "10.0.0.20"}).json()
    c.post("/v1/devices", json={"org_id": org_id, "hostname": "gateway", "os": "Cisco IOS", "ip": "10.0.0.1"})
    queued = c.post("/v1/fleet/discover", json={"device_id": scanner["id"]})
    assert queued.status_code == 201 and queued.json()["command"] == "arp -a"
    assert c.get("/v1/fleet/discovered").json() == {"scans": 0, "unmanaged": 0, "devices": []}  # nothing until the agent reports
    c.post(f"/v1/scripts/runs/{queued.json()['run_id']}/complete", headers={"X-Agent-Token": scanner["device_secret"]}, json={"output": ARP_WINDOWS, "exit_code": 0})
    found = c.get("/v1/fleet/discovered").json()
    assert found["scans"] == 1 and found["unmanaged"] == 1
    rows = {r["ip"]: r for r in found["devices"]}
    assert rows["10.0.0.45"]["managed_device_id"] is None and rows["10.0.0.45"]["seen_by"] == ["scanner"]
    assert rows["10.0.0.1"]["managed_hostname"] == "gateway"
    assert found["devices"][0]["ip"] == "10.0.0.45"  # unmanaged first
    other = c.post("/v1/auth/bootstrap", json={"name": "Other discovery tenant"}).json()
    foreign = {"Authorization": f"Bearer {other['access_token']}"}
    assert c.get("/v1/fleet/discovered", headers=foreign).json()["devices"] == []
    assert c.post("/v1/fleet/discover", json={"device_id": scanner["id"]}, headers=foreign).status_code == 404


def test_windows_update_lines_are_parsed_with_severity_and_kb():
    text = "\n".join([
        "WU|KB5044284|Critical|Security Updates;Windows 11|2024-11 Cumulative Update for Windows 11 (KB5044284)",
        "WU|KB890830||Update Rollups|Windows Malicious Software Removal Tool",
        "WU-ERROR|access denied",
        WINGET,
    ])
    rows = patch_scan.parse(text)
    assert rows[0] == {"name": "2024-11 Cumulative Update for Windows 11 (KB5044284)", "current_version": "", "available_version": "KB5044284", "category": "security", "severity": "critical"}
    assert rows[1]["name"] == "Windows Malicious Software Removal Tool (KB890830)" and rows[1]["category"] == "os"
    assert [r["category"] for r in rows[2:]] == ["third_party", "third_party"]  # winget apps from the same scan
