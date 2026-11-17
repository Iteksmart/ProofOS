# ProofOS competitive scorecard — November 2026

Scores are 1–10 judgments for each capability area. Sources: vendor
documentation and press listed in `COMPETITIVE_RESEARCH_2026-11-17.md`, the
Atera trial workspace (device list, device detail, dashboard) reviewed on
17 November 2026, and the ProofOS code and test suite at the time of writing.
Competitor scores reflect publicly documented capability, not hands-on
benchmarks. ProofOS scores reflect what is implemented and tested.

These products target different jobs: Atera is an RMM/PSA for IT teams and
MSPs, ServiceNow is an ITSM/ITOM workflow platform, and Dynatrace and Datadog
are observability platforms. A single blended score would hide that, so read
the rows that match the job you need done.

| Capability | ProofOS (before → now) | Atera | ServiceNow | Dynatrace | Datadog |
| --- | :-: | :-: | :-: | :-: | :-: |
| Endpoint management (agent, inventory, alerts, scripts, software, discovery, remote) | 7 → **8** | 9 | 5 | 3 | 4 |
| Patch management | 5 → **8** | 9 | 5 | 2 | 2 |
| Ticketing, ITSM and PSA (customers, contracts, billing) | 6 → **7** | 8 | 10 | 2 | 4 |
| Logs, metrics and traces | 5 | 3 | 6 | 10 | 10 |
| Service topology and impact | 5 | 2 | 9 | 10 | 8 |
| AI troubleshooting | 6 → **7** | 7 | 8 | 9 | 9 |
| AI remediation with approval and recovery checks | 7 | 6 | 8 | 7 | 7 |
| Verifiable evidence of actions (signatures, hash chain) | 9 | 3 | 5 | 4 | 4 |
| Privileged access (just-in-time, dual control, vault) | 6 | 5 | 5 | 2 | 3 |
| Usability of the console | 7 | 8 | 6 | 7 | 8 |
| Scale, maturity, certifications, ecosystem | 2 | 8 | 10 | 10 | 10 |

### What changed against Atera in the 17 November round

- **Patch management (5 → 8).** Scans now produce patch records: Windows
  Update KBs (with Microsoft severity) and winget apps on Windows, apt and
  dnf/yum on Linux. Policies auto-approve by severity and category, deploy
  inside UTC maintenance windows, defer new patches, and reboot never, always
  or only when the OS requires it. A scheduler runs open windows once each.
  Deployments install exactly the approved KBs and package ids, so rejected
  patches are never installed by a blanket upgrade. Compliance shows the share
  of fully patched endpoints, critical backlog, approvals pending and reboots
  pending. Every approval, run and result is signed.
- **Endpoint management (7 → 8).** Threshold alerts on CPU, memory and disk
  open after N consecutive samples and resolve themselves; agents report pending
  reboots; one-line install commands for Windows, Linux and macOS; bulk software
  install and uninstall through winget, apt/dnf and brew with strict package-id
  validation; passive network discovery from an agent's neighbour table that
  flags unmanaged devices.
- **PSA (6 → 7).** Customers with contacts, assigned endpoints and tickets
  (tickets inherit the endpoint's customer); hourly, retainer and fixed
  contracts with per-endpoint fees; a monthly billing preview from billable
  ticket time; issued invoices that are frozen, signed, exported to CSV, and
  flagged if altered later.
- **AI troubleshooting (6 → 7).** A ticket assistant summarises the ticket,
  conversation, linked device, open alerts, pending patches and matching
  knowledge articles, suggests next steps and drafts a reply that can be posted
  as a comment. It runs on the configured AI provider (verified against the
  iTechSmart Nemotron bridge) and falls back to a rule-based answer that is
  labelled as such.

### Still behind Atera, and what closes each gap

| Area | Gap | Next step |
| --- | --- | --- |
| Endpoint management | The agent needs Python; Atera ships signed MSI and pkg installers | Package the agent as a signed Windows service and macOS pkg |
| Endpoint management | Discovery is passive (neighbour table only); no SNMP or port scanning | Agent-side subnet sweep with SNMP sysDescr, then topology linking |
| Endpoint management | No Windows service or event-log monitoring | Add service-state and event-ID checks to thresholds |
| Patch management | macOS patching not supported; not yet run against a live Windows or Linux endpoint | `softwareupdate -l` scanning; validate on real endpoints before claiming parity |
| PSA | No email-to-ticket, customer portal, or accounting integration | Inbound email webhook, a signed-link customer portal, QuickBooks/Xero export |
| Usability | Tickets, Monitor and several older views still use the earlier layout | Move them onto the shared page, table and form components |
| Scale and maturity | No fleet-scale validation, certifications, or customer base | Load testing, SOC 2 programme, CI unblocked |

## Where ProofOS leads

- **Verifiable evidence.** Every write produces an Ed25519-signed,
  hash-chained record. Command, output and exit code are bound to the approval
  that authorised them, and altered records are detected. Recovery probes are
  signed separately, so "the command ran" and "the service recovered" are
  different, independently checkable claims. None of the public material
  reviewed for the four competitors describes signed, hash-chained action
  receipts.
- **Honest status.** Topology health and recovery report "unknown" or
  "pending" when there is no evidence, rather than defaulting to healthy.
- **Transparent fleet queries.** Describing endpoints in plain English shows the
  exact filters applied and lists any words that were not understood. Atera's
  equivalent AI filter does not show its interpretation in the list view.
- **Least-privilege access.** Engineers can be granted one exact command on one
  endpoint for minutes, approved by a second person, checked at use time.

## Where ProofOS trails, by priority

1. **Scale and maturity.** No fleet-scale validation, no compliance
   certifications, no packaged agent installers or update channel, and CI
   cannot currently run on GitHub (account billing lock).
2. **Patch management** (Atera 9). Missing a vendor patch catalogue,
   scheduled deployment rings, automatic approval policies and reboot
   orchestration.
3. **Observability depth** (Dynatrace, Datadog 10). Missing auto-instrumenting
   APM agents, real-user and synthetic monitoring, long retention and a query
   language. Telemetry is stored in PostgreSQL with seven-day retention.
4. **Discovery and topology** (Dynatrace 10, ServiceNow 9). Dependencies come
   from traces or manual entry; there is no network or process discovery.
5. **PSA** (Atera 8). Missing per-customer billing, contracts, invoicing and a
   customer portal. Atera's Customers model (many client companies under one
   MSP account) has no direct equivalent.
6. **Privileged sessions** (CyberArk). No session isolation or recording.
7. **AI** (Datadog Bits AI SRE, Dynatrace Intelligence). No causal model over
   telemetry and no autonomous multi-step investigation across data sources.

## Added in this round

- Plain-English fleet query (`GET /v1/fleet/query`) with visible
  interpretation, tenant scoping, and no results for an unparsed query.
- Bulk actions (`POST /v1/fleet/bulk`): queue a script or create a ticket on up
  to 200 selected endpoints. Admin/manager required for scripts, read-only
  roles blocked, the kill switch is honoured, per-endpoint results are returned
  and the whole action is recorded as one signed proof record.
- Device list and detail show open alerts and pending patches, with status and
  patch filters (parity with Atera's device list).
