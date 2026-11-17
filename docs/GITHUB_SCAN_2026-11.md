# GitHub scan: features worth adding — November 2026

Scope: open-source IT operations projects reviewed on 17 November 2026 through the
GitHub API (stars, last push, archived flag, licence SPDX id). Archived projects
and those with no push in 12 months were excluded (for example Peppermint and
OpenClarity). Items already covered in `COMPETITIVE_RESEARCH_2026-11-17.md`
(in-toto, OPA, Robusta, Keep, Fleet, SigNoz) are only repeated where something
new applies. No third-party code was copied into ProofOS.

Ranked by value to effort.

| # | Idea | Source projects (licence) | Why it matters | Effort | Approach | Status |
|---|---|---|---|---|---|---|
| 1 | Publish the proof-chain head to an external, independently witnessed transparency log | transparency-dev/tessera, transparency-dev/witness, sigstore/rekor (Apache-2.0) | Auditors can check the ledger without trusting ProofOS's own key; no competitor documents this | S–M | Integrate | Planned |
| 2 | Match installed software to known vulnerabilities | google/osv-scanner, aquasecurity/trivy (Apache-2.0) | Prioritise patches by real exposure using the inventory ProofOS already collects | M | Integrate (OSV API) | Planned |
| 3 | Declarative agent-side health checks for recovery | goss-org/goss, prometheus/blackbox_exporter (Apache-2.0) | "Recovered" means the service, process and port are right, not only that a port answers | S | Reimplement | Planned |
| 4 | SQL queries against endpoints, each signed | osquery/osquery (Apache-2.0 / GPL-2.0 dual) | Technicians and the AI can ask any endpoint precise questions | M | Integrate under Apache-2.0 | Planned |
| 5 | Network discovery of unmanaged devices | projectdiscovery/naabu (MIT); netdisco (BSD-3, learn only) | Closes Atera's Network Discovery gap; feeds topology | M | Agent-side | **Shipped (ARP/neighbour table)**; active port scanning still planned |
| 6 | Multi-step AI investigation with read-only tool calls | HolmesGPT (Apache-2.0, CNCF Sandbox), k8sgpt (Apache-2.0) | Approaches Datadog Bits / Dynatrace agents while signing every step | M | Learn and reimplement | Planned |
| 7 | Root-cause ranking from SLOs and topology | coroot/coroot (Apache-2.0) | Narrows the causal-AI gap with Dynatrace | M–L | Learn and reimplement | Planned |
| 8 | Signed multi-step runbooks with approval gates | rundeck, StackStorm st2 (Apache-2.0) | Competes with ServiceNow playbooks | M | Learn; extend automations | Planned |
| 9 | Policy-as-code decisions stored in proof records | OPA, Kyverno (Apache-2.0) | "Why this action was allowed" becomes verifiable evidence | S–M | Integrate OPA sidecar | Planned |
| 10 | Package-manager software deployment | microsoft/winget-cli (MIT), chocolatey/choco (Apache-2.0) | Matches Atera's software installation | S | Agent commands | **Shipped (winget, apt/dnf, brew)** |
| 11 | Uptime and certificate-expiry monitors with status pages | uptime-kuma (MIT), gatus (Apache-2.0) | Strengthens the customer offering | S | Learn and reimplement | Planned |
| 12 | Recorded privileged sessions as signed evidence | MeshCentral (Apache-2.0, already used); Teleport (AGPL-3.0, learn only) | Closes the CyberArk gap | L | Build on MeshCentral | Planned |

## Licence cautions

- **Do not copy code (AGPL):** Zabbix, Zammad, Teleport, Snipe-IT, Renovate, RustDesk.
- **Do not copy code (GPL-3):** GLPI, LibreNMS, Ansible.
- **Learn only:** Tactical RMM's licence forbids competing use. Wazuh is dual-licensed, mostly GPL-2. Nmap's NPSL restricts redistribution.
- **Safe to integrate:** the Apache-2.0 and MIT projects above, and NetBox (Apache-2.0), which is a candidate for CMDB and IP-address-management sync.

## Sources

transparency-dev/tessera, transparency-dev/witness, sigstore/rekor, google/osv-scanner,
aquasecurity/trivy, goss-org/goss, prometheus/blackbox_exporter, osquery/osquery,
projectdiscovery/naabu, netdisco/netdisco, HolmesGPT/holmesgpt, k8sgpt-ai/k8sgpt,
coroot/coroot, rundeck/rundeck, StackStorm/st2, open-policy-agent/opa, kyverno/kyverno,
microsoft/winget-cli, chocolatey/choco, louislam/uptime-kuma, TwiN/gatus,
gravitational/teleport, Ylianst/MeshCentral, netbox-community/netbox, amidaware/tacticalrmm,
zabbix/zabbix, zammad/zammad, glpi-project/glpi, wazuh/wazuh (all on github.com).
