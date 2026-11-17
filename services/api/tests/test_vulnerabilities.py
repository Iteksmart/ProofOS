"""OSV vulnerability matching against endpoint software inventory."""
from __future__ import annotations

import httpx

from app.services import vulnerabilities

VULNS = {
    "USN-7000-1": {"id": "USN-7000-1", "summary": "OpenSSL vulnerabilities", "aliases": ["CVE-2026-1111"],
        "affected": [{"package": {"name": "openssl", "ecosystem": "Ubuntu:22.04:LTS"}, "ecosystem_specific": {"severity": "high"},
            "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "3.0.2-0ubuntu1.18"}]}]}]},
    "USN-7001-1": {"id": "USN-7001-1", "summary": "curl regression", "affected": [{"package": {"name": "curl", "ecosystem": "Ubuntu:22.04:LTS"},
        "database_specific": {"severity": "negligible"}}]},
}


class FakeOsv:
    def __init__(self):
        self.affected = {("openssl", "3.0.2-0ubuntu1.15"): ["USN-7000-1"], ("curl", "7.81.0-1ubuntu1.16"): ["USN-7001-1"]}
        self.queries = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/querybatch"):
            import json
            queries = json.loads(request.content)["queries"]
            self.queries.append(queries)
            return httpx.Response(200, json={"results": [{"vulns": [{"id": i} for i in self.affected.get((q["package"]["name"], q["version"]), [])]} for q in queries]})
        vuln_id = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=VULNS[vuln_id]) if vuln_id in VULNS else httpx.Response(404)


def test_ecosystem_mapping():
    assert vulnerabilities.ecosystem({"id": "ubuntu", "version_id": "22.04"}) == "Ubuntu:22.04:LTS"
    assert vulnerabilities.ecosystem({"id": "ubuntu", "version_id": "23.10"}) == "Ubuntu:23.10"
    assert vulnerabilities.ecosystem({"id": "debian", "version_id": "12"}) == "Debian:12"
    assert vulnerabilities.ecosystem({"id": "alpine", "version_id": "3.19.1"}) == "Alpine:v3.19"
    assert vulnerabilities.ecosystem({"id": "rocky", "version_id": "9.3"}) == "Rocky Linux:9"
    assert vulnerabilities.ecosystem({"id": "windows"}) is None


def test_severity_from_distro_rating_and_cvss_vectors():
    # Reference scores from the FIRST CVSS v3.1 calculator.
    assert vulnerabilities.cvss3_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H") == 9.8
    assert vulnerabilities.cvss3_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H") == 10.0
    assert vulnerabilities.cvss3_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:L") == 5.3
    assert vulnerabilities.cvss3_score("CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N") == 5.5
    assert vulnerabilities.cvss3_score("CVSS:3.1/AV:N/AC:H/PR:H/UI:R/S:C/C:L/I:L/A:N") == 4.0
    assert vulnerabilities.cvss3_score("garbage") is None
    ubuntu = {"severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:L"}, {"type": "Ubuntu", "score": "low"}]}
    assert vulnerabilities._severity(ubuntu, "openssl") == "low"
    debian = {"severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}],
              "affected": [{"package": {"name": "openssl"}, "ecosystem_specific": {"urgency": "not yet assigned"}}]}
    assert vulnerabilities._severity(debian, "openssl") == "critical"


def test_scan_matches_source_packages_resolves_fixed_and_scopes(auth_client, monkeypatch):
    c, org_id, _ = auth_client
    fake = FakeOsv()
    original = vulnerabilities.scan
    monkeypatch.setattr(vulnerabilities, "scan", lambda db, org, transport=None: original(db, org, httpx.MockTransport(fake.handler)))
    linux = c.post("/v1/devices", json={"org_id": org_id, "hostname": "vuln-ubuntu", "os": "Ubuntu 22.04"}).json()
    win = c.post("/v1/devices", json={"org_id": org_id, "hostname": "vuln-win", "os": "Windows 11"}).json()
    software = [{"name": "libssl3", "version": "3.0.2-0ubuntu1.15", "source": "openssl", "source_version": "3.0.2-0ubuntu1.15"},
                {"name": "curl", "version": "7.81.0-1ubuntu1.16"}, {"name": "bash", "version": "5.1-6ubuntu1"}]
    agent = {"X-Agent-Token": linux["device_secret"]}
    assert c.post(f"/v1/devices/{linux['id']}/inventory", headers=agent, json={"software": software, "software_status": "complete",
        "os_release": {"id": "ubuntu", "version_id": "22.04"}}).status_code == 200
    c.post(f"/v1/devices/{win['id']}/inventory", headers={"X-Agent-Token": win["device_secret"]}, json={"software": [{"name": "7-Zip", "version": "24"}], "software_status": "complete"})
    c.post("/v1/patches", json={"org_id": org_id, "device_id": linux["id"], "name": "openssl", "severity": "important"})

    result = c.post("/v1/vulnerabilities/scan").json()
    assert result["devices_covered"] == 1 and result["devices_not_covered"] == ["vuln-win"] and result["new_findings"] == 2
    queried = {q["package"]["name"] for q in fake.queries[0]}
    assert "openssl" in queried and "libssl3" not in queried  # the source package is what OSV indexes
    data = c.get("/v1/vulnerabilities").json()
    first = data["findings"][0]
    assert first["vuln_id"] == "USN-7000-1" and first["severity"] == "high" and first["fixed_version"] == "3.0.2-0ubuntu1.18"
    assert first["aliases"] == ["CVE-2026-1111"] and first["patch_pending"] is True and first["hostname"] == "vuln-ubuntu"
    assert data["findings"][1]["severity"] == "low" and data["counts"]["high"] == 1

    # After an upgrade the finding is resolved, not deleted.
    fake.affected.pop(("openssl", "3.0.2-0ubuntu1.15"))
    software[0]["source_version"] = "3.0.2-0ubuntu1.18"
    c.post(f"/v1/devices/{linux['id']}/inventory", headers=agent, json={"software": software, "software_status": "complete", "os_release": {"id": "ubuntu", "version_id": "22.04"}})
    assert c.post("/v1/vulnerabilities/scan").json()["new_findings"] == 0
    assert [f["vuln_id"] for f in c.get("/v1/vulnerabilities?status=resolved").json()["findings"]] == ["USN-7000-1"]
    assert [f["vuln_id"] for f in c.get("/v1/vulnerabilities").json()["findings"]] == ["USN-7001-1"]

    other = c.post("/v1/auth/bootstrap", json={"name": "Other vuln tenant"}).json()
    assert c.get("/v1/vulnerabilities", headers={"Authorization": f"Bearer {other['access_token']}"}).json()["findings"] == []
    down = httpx.MockTransport(lambda r: httpx.Response(503))
    monkeypatch.setattr(vulnerabilities, "scan", lambda db, org, transport=None: original(db, org, down))
    assert c.post("/v1/vulnerabilities/scan").status_code == 502
