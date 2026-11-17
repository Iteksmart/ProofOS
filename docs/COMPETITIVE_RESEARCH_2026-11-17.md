# ProofOS competitive research and implementation decisions

Research date: November 17, 2026. Primary vendor documentation and repository
metadata were reviewed. This is a capability comparison, not a hands-on benchmark
of paid enterprise deployments. “Cyberarch” is interpreted as CyberArk.

## Established platforms

| Platform | Capabilities to benchmark | Consequence for ProofOS |
| --- | --- | --- |
| [CyberArk](https://www.cyberark.com/solutions/session-monitoring-and-recording/) | Privileged session isolation, recording, monitoring, searchable audit history, and session termination | A secret vault and signed events alone do not replace privileged access management. Add scoped short-lived credentials, brokered sessions and independent recording retention. |
| [N-able N-central](https://www.n-able.com/products/n-central-rmm) | Endpoint management, discovery, patch/vulnerability workflows, automation, AI assistant and integrations; adjacent backup/security products | Need agent deployment, fleet policy, maintenance windows, reboot handling and tested backup/restore integrations. Current inventory is a foundation, not full UEM parity. |
| [Dynatrace Intelligence](https://www.dynatrace.com/platform/artificial-intelligence/) | Causal analysis, dependency topology, unified telemetry and governed agentic operations | Build service relationships and test hypotheses against observations. A recent alert is not automatically a root cause. |
| [Datadog Bits Remediation](https://docs.datadoghq.com/bits_ai/bits_remediation/) | Investigation-linked fixes, infrastructure actions with guardrails/approval, action history and resolution checks; some actions are preview | Benchmark the complete investigation-to-recovery workflow. Execution exit code zero must remain distinct from restored service. |
| [Splunk Observability](https://www.splunk.com/en_us/products/observability.html) | Infrastructure/APM visibility, telemetry investigation, security integration and on-call workflows | Need real logs/traces collection, service context, retention and query performance benchmarks; a metric webhook is not an observability data plane. |
| [ServiceNow ITOM](https://www.servicenow.com/docs/r/it-operations-management/app-now-assist-itom.html) | AI alert triage, impact assessment, service mapping, probable cause investigation and remediation workflows; historical incident learning | Join devices, services, incidents and changes with explicit relationships; evaluate business impact and permission scope before action. |

## Emerging approaches worth evaluating

- [Resolve AI](https://website-prod.resolve.ai/product/ai-sre): investigation across production tooling and operational context. Evaluate cross-source evidence retrieval and competing hypotheses rather than adopting vendor performance claims as benchmark results.
- [Rootly AI SRE](https://rootly.com/ai-sre): investigation integrated into incident response, with confidence and response assistance. Evaluate incident timelines, handoff quality and postmortem drafting.
- [Causely](https://www.causely.ai/blog/what-is-a-causal-model-in-observability): explicit cause/effect models. Explore topology-aware fault propagation alongside language-model explanations.
- [SigNoz](https://github.com/SigNoz/signoz): OpenTelemetry-oriented observability and AI-accessible operational context. Consider integration rather than building every storage/query subsystem ourselves.

## Targeted GitHub scan

Repository descriptions, archived status, push activity and GitHub license metadata
were checked through the public GitHub API. All seven repositories below were
unarchived at review. Activity does not establish security, compatibility or code
quality. No third-party project code was installed or copied into ProofOS.

| Repository | Useful extension | License metadata observed / adoption decision |
| --- | --- | --- |
| [OpenTelemetry Collector Contrib](https://github.com/open-telemetry/opentelemetry-collector-contrib) | Standard receivers/processors/exporters for telemetry ingestion; redact before AI retrieval | Apache-2.0; preferred telemetry interoperability candidate |
| [OPA](https://github.com/open-policy-agent/opa) | Policy decisions for target scope, allowed actions, maintenance windows and approvals | Apache-2.0; prototype a policy adapter, preserve an explicit fail-closed execution boundary |
| [Robusta](https://github.com/robusta-dev/robusta) | Kubernetes alert grouping, context enrichment and remediation playbooks | MIT; evaluate Kubernetes event/playbook interoperability |
| [Keep](https://github.com/keephq/keep) | Alert correlation and workflow/provider integrations | GitHub SPDX value NOASSERTION; review component licenses before reuse |
| [Fleet](https://github.com/fleetdm/fleet) | Device management and endpoint query interoperability | NOASSERTION; inspect component/edition licensing before embedding or redistribution |
| [SigNoz](https://github.com/SigNoz/signoz) | Logs/metrics/traces backend and investigation integration | NOASSERTION; review component licensing and distribution terms |
| [in-toto](https://github.com/in-toto/in-toto) | Evidence statements binding action inputs, actors and outputs | NOASSERTION in API metadata; inspect actual license files. Explore compatible statement exports rather than claiming current compliance. |

## Shipped from this review

1. Explicit-device troubleshooting with a snapshot of metrics and correlated
   events, an AI explanation when the configured provider is available, and an
   honestly labeled deterministic fallback. The investigation is signed.
2. A bounded action catalog: disk/process diagnostics and Linux nginx or Windows
   print-spooler restarts. Exact commands and targets require human approval.
   This is not arbitrary unattended infrastructure repair.
3. Queue receipts bind the complete command digest to run and approval IDs.
   Agent completion receipts bind command/output hashes and exit code. Queue
   creation and its signed receipt commit together.
4. An authenticated run-evidence view recomputes hashes and verifies Ed25519
   signatures; changing stored command/output invalidates the match. The UI
   exposes these checks under endpoint Activity.

## Next implementation priorities and acceptance tests

1. Post-action service probes: collect several fresh observations after execution;
   distinguish pending validation, failed checks and recovery. Never infer
   recovery solely from exit code or a signed receipt.
2. OTel ingestion and topology: correlate trace/service/deployment IDs, then
   benchmark detection and diagnosis on labeled staging incidents.
3. Policy and rollback: bind a plan digest, target set, approval expiry, maintenance
   window, privilege scope and rollback strategy. Exercise kill-switch and replay
   failures before expanding autonomy.
4. Cryptographic trust: pin verification keys independently, isolate signing keys,
   support rotation, and anchor evidence externally. Signatures authenticate
   records, not endpoint truth. A compromised agent can report false observations;
   local development signing keys are not a production trust root.
5. Evaluate on reproducible scenarios: unavailable service, CPU saturation, disk
   pressure, certificate expiry, configuration regression, denied authorization,
   tampered receipts, missing telemetry and failed rollback. Measure diagnosis
   accuracy, recovery rate, false fixes and human effort against competitors.

Overall superiority is not established by feature counts or vendor literature.
ProofOS's proposed differentiator is a verifiable operational evidence workflow;
fleet-scale validation and the remaining integrations are still required.
