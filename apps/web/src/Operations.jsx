import React, { useEffect, useState } from "react";

const date = (value) => value ? new Date(value).toLocaleString() : "Not received";
const bytes = (value) => value == null ? "Not reported" : value >= 2 ** 30 ? `${(value / 2 ** 30).toFixed(1)} GB` : `${(value / 2 ** 20).toFixed(0)} MB`;
const fresh = (value) => value && Date.now() - new Date(value).getTime() < 86400000;

function Status({ children, tone = "neutral" }) {
  return <span className={`ops-status ${tone}`}>{children}</span>;
}

function Empty({ title, children }) {
  return <div className="ops-empty"><span className="ops-empty-symbol" aria-hidden="true">◇</span><h3>{title}</h3><p>{children}</p></div>;
}

function PageHead({ eyebrow, title, description, children }) {
  return <div className="ops-head"><div><p className="ops-eyebrow">{eyebrow}</p><h1>{title}</h1><p className="ops-description">{description}</p></div><div className="ops-head-actions">{children}</div></div>;
}

function Metrics({ items }) {
  return <div className="ops-metrics">{items.map(([label, value, detail]) => <div className="card ops-metric" key={label}><p className="stat-label">{label}</p><strong>{value}</strong><span>{detail}</span></div>)}</div>;
}

function DataTable({ columns, children }) {
  return <div className="card overflow-x-auto"><table className="ops-table"><thead><tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr></thead><tbody>{children}</tbody></table></div>;
}

export function InventoryDetail({ snapshot }) {
  const [query, setQuery] = useState("");
  const data = snapshot?.inventory;
  if (!data) return <Empty title="Waiting for the first inventory">Run agent v1.1.0 or later with this device’s enrollment secret. Hardware, storage, network, and installed software are collected at startup and hourly.</Empty>;
  const hardware = data.hardware || {};
  const software = (data.software || []).filter((s) => `${s.name} ${s.version} ${s.publisher}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="ops-section-stack">
    <div className="ops-inline-meta"><Status tone={fresh(snapshot.collected_at) ? "good" : "warn"}>{fresh(snapshot.collected_at) ? "Fresh inventory" : "Inventory older than 24h"}</Status><span>Received {date(snapshot.collected_at)}</span></div>
    <dl className="ops-facts">{[
      ["Manufacturer", hardware.manufacturer], ["Model", hardware.model], ["Processor", hardware.processor],
      ["Architecture", hardware.architecture], ["Physical / logical cores", hardware.logical_cores == null ? null : `${hardware.physical_cores ?? "—"} / ${hardware.logical_cores}`],
      ["Installed memory", bytes(hardware.memory_bytes)], ["Last boot", hardware.boot_time ? date(hardware.boot_time) : null], ["Operating system", data.os],
    ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || "Not reported"}</dd></div>)}</dl>
    <div><h3 className="ops-section-title">Storage</h3>{data.disks.length ? <DataTable columns={["Volume", "Filesystem", "Capacity", "Free"]}>{data.disks.map((d, i) => <tr key={i}><td><strong>{d.mountpoint}</strong><small>{d.device}</small></td><td>{d.filesystem || "—"}</td><td>{bytes(d.total_bytes)}</td><td>{bytes(d.free_bytes)}</td></tr>)}</DataTable> : <p className="ops-muted">No volumes reported.</p>}</div>
    <div><h3 className="ops-section-title">Network interfaces</h3><div className="ops-network-grid">{data.networks.map((n, i) => <div key={i}><strong>{n.name}</strong><code>{n.address}</code></div>)}</div></div>
    <div><div className="ops-toolbar"><div><h3 className="ops-section-title">Installed software</h3><p className="ops-muted">{data.software.length} packages · collection {data.software_status}</p></div><input aria-label="Search installed software" placeholder="Search name, version, publisher" value={query} onChange={(e) => setQuery(e.target.value)} /></div>
      {software.length ? <div className="ops-scroll"><DataTable columns={["Application / package", "Version", "Publisher"]}>{software.map((s, i) => <tr key={i}><td>{s.name}</td><td><code>{s.version || "—"}</code></td><td>{s.publisher || "—"}</td></tr>)}</DataTable></div> : <Empty title={query ? "No matching software" : "Software not reported"}>{query ? "Try a different search." : "Check the collection status and agent permissions."}</Empty>}
    </div>
    {data.errors.length > 0 && <div className="ops-note">{data.errors.join(" · ")}</div>}
  </div>;
}

export function InventoryPage({ api, orgId, onOpenDevice }) {
  const [rows, setRows] = useState([]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [mode, setMode] = useState("endpoints");
  const [software, setSoftware] = useState({ items: [], total: 0 });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  async function load() {
    setLoading(true); setError("");
    try { setRows(await api(`/v1/devices/inventory?org_id=${orgId}`)); } catch (e) { setError(e.message); } finally { setLoading(false); }
  }
  useEffect(() => { load(); }, [orgId]);
  useEffect(() => {
    if (mode !== "software") return;
    let current = true;
    const timer = setTimeout(async () => {
      try { const data = await api(`/v1/devices/software?org_id=${orgId}&q=${encodeURIComponent(query)}`); if (current) setSoftware(data); }
      catch (e) { if (current) setError(e.message); }
    }, 180);
    return () => { current = false; clearTimeout(timer); };
  }, [orgId, query, mode]);
  const filtered = rows.filter((r) => `${r.hostname} ${r.os} ${r.hardware?.manufacturer || ""} ${r.hardware?.model || ""}`.toLowerCase().includes(query.toLowerCase()) && (filter === "all" || (filter === "missing" ? !r.collected_at : filter === "stale" ? r.collected_at && !fresh(r.collected_at) : fresh(r.collected_at))));
  const covered = rows.filter((r) => r.collected_at).length;
  return <div className="ops-page">
    <PageHead eyebrow="Endpoint intelligence" title="Know every endpoint." description="Hardware, software, storage, and network inventory with visible collection coverage."><button className="ops-button" onClick={load} disabled={loading}>{loading ? "Refreshing…" : "Refresh inventory"}</button></PageHead>
    {error && <p role="alert">{error}</p>}
    <Metrics items={[["Endpoints", rows.length, "All registered devices"], ["Inventory coverage", rows.length ? `${Math.round(covered / rows.length * 100)}%` : "—", `${covered} devices have reported`], ["Fresh snapshots", rows.filter((r) => fresh(r.collected_at)).length, "Received in the last 24 hours"], ["Software packages", rows.reduce((sum, r) => sum + r.software_count, 0).toLocaleString(), "Across collected endpoints"]]} />
    <div className="ops-toolbar"><div className="segmented" aria-label="Inventory view">{[["endpoints", "Endpoints"], ["software", "Software intelligence"]].map(([key, label]) => <button key={key} aria-pressed={mode === key} onClick={() => { setMode(key); setQuery(""); }}>{label}</button>)}</div><input aria-label="Search inventory" placeholder={mode === "software" ? "Search software, version, publisher…" : "Search device, OS, manufacturer…"} value={query} onChange={(e) => setQuery(e.target.value)} /></div>
    {mode === "endpoints" ? <><div className="ops-inline-meta" aria-label="Inventory coverage filter">{[["all", "All endpoints"], ["fresh", "Fresh"], ["stale", "Stale"], ["missing", "Not collected"]].map(([key, label]) => <button className={`ops-filter ${filter === key ? "selected" : ""}`} key={key} aria-pressed={filter === key} onClick={() => setFilter(key)}>{label}</button>)}</div><DataTable columns={["Endpoint", "Hardware", "Memory / cores", "Software", "Collection", ""]}>{filtered.map((r) => <tr key={r.device_id}><td><strong>{r.hostname}</strong><small>{r.os || "OS not reported"}</small></td><td>{[r.hardware.manufacturer, r.hardware.model].filter(Boolean).join(" · ") || "Not collected"}</td><td>{bytes(r.hardware.memory_bytes)}<small>{r.hardware.logical_cores ? `${r.hardware.logical_cores} logical cores` : "Cores not reported"}</small></td><td>{r.collected_at ? r.software_count.toLocaleString() : "—"}<small>{r.software_status}</small></td><td><Status tone={fresh(r.collected_at) ? "good" : "warn"}>{r.collected_at ? fresh(r.collected_at) ? "Fresh" : "Stale" : "Not collected"}</Status><small>{date(r.collected_at)}</small></td><td><button className="ops-link" onClick={() => onOpenDevice(r.device_id)}>Inspect →</button></td></tr>)}</DataTable>
    {!loading && !filtered.length && <Empty title={rows.length ? "No matching endpoints" : "Your inventory starts with an endpoint"}>{rows.length ? "Adjust the search or collection filter." : "Register a device in Devices and run agent v1.1.0 to collect its inventory."}</Empty>}</> : <><p className="ops-muted">{software.total} application/version combinations · Showing up to 200. Search to narrow results.</p><DataTable columns={["Application / package", "Version", "Publisher", "Installed on"]}>{software.items.map((s, i) => <tr key={i}><td><strong>{s.name}</strong></td><td><code>{s.version || "Unknown"}</code></td><td>{s.publisher || "—"}</td><td>{s.devices.map((d) => <button key={d.id} className="ops-software-device" onClick={() => onOpenDevice(d.id)}>{d.hostname} ↗</button>)}</td></tr>)}</DataTable>{!software.items.length && <Empty title="No matching software">Collect software inventory from an agent or adjust your search.</Empty>}</>}
    <div className="ops-note">Collection runs at agent startup and hourly. Missing values stay visible so you can distinguish uncollected data from a healthy endpoint.</div>
  </div>;
}

export function DeviceActivity({ api, deviceId, renderRecovery }) {
  const [rows, setRows] = useState([]);
  const [evidence, setEvidence] = useState(null);
  const [error, setError] = useState("");
  async function load() { try { setRows(await api(`/v1/devices/${deviceId}/activity`)); } catch (e) { setError(e.message); } }
  useEffect(() => { load(); }, [deviceId]);
  return <div className="ops-section-stack"><div className="ops-toolbar"><div><h3 className="ops-section-title">Endpoint execution history</h3><p className="ops-muted">The latest 25 script, command, and patch runs. Expand a run to inspect its output.</p></div><button className="ops-button" onClick={load}>Refresh history</button></div>{error && <p role="alert">{error}</p>}{rows.map((r) => <details key={r.id} className="ops-run"><summary><span><strong>#{r.id} · {r.name}</strong><small>{date(r.created_at)}{r.exit_code != null ? ` · Exit ${r.exit_code}` : ""}</small></span><Status tone={r.status === "failed" ? "warn" : r.status === "completed" ? "good" : "neutral"}>{r.status}</Status></summary><pre>{r.output || "No output reported yet."}</pre><button className="ops-button m-3" onClick={async () => { try { setEvidence(await api(`/v1/scripts/runs/${r.id}/evidence`)); } catch (e) { setError(e.message); } }}>Verify signed result</button></details>)}{evidence && <div className="ops-note"><strong>Run #{evidence.run_id}: {evidence.signed_result_matches ? "Signed result matches" : "Result not verified"}</strong><p>{evidence.trust_note}</p>{renderRecovery && renderRecovery(evidence.run_id)}<details className="mt-2"><summary>Inspect cryptographic receipts</summary><pre className="overflow-auto max-h-80 text-xs whitespace-pre-wrap">{JSON.stringify(evidence, null, 2)}</pre></details></div>}{!rows.length && <Empty title="No executions yet">Commands, scripts, and patch deployments will appear here with their actual agent results.</Empty>}</div>;
}

export function TelemetryChart({ metrics }) {
  const points = metrics.slice(0, 40).reverse();
  if (!points.length) return <Empty title="Waiting for endpoint telemetry">The first agent heartbeat will populate CPU, memory, and disk history.</Empty>;
  const series = [["cpu", "CPU", "#697bec"], ["mem", "Memory", "#29a17d"], ["disk", "Disk", "#d99b38"]];
  const line = (key) => points.map((p, i) => `${points.length === 1 ? 300 : i / (points.length - 1) * 600},${120 - Math.max(0, Math.min(100, Number(p[key]) || 0)) * 1.2}`).join(" ");
  return <div className="telemetry-chart"><div className="ops-toolbar"><h3 className="ops-section-title">Resource utilization</h3><div className="telemetry-legend">{series.map(([key, label, color]) => <span key={key}><i style={{ background: color }} />{label}</span>)}</div></div><div className="telemetry-plot"><span>100%</span><svg viewBox="0 0 600 124" role="img" aria-label={`Resource utilization from ${points.length} actual heartbeat samples`} preserveAspectRatio="none">{[0, 30, 60, 90, 120].map((y) => <line key={y} x1="0" x2="600" y1={y} y2={y} stroke="currentColor" strokeWidth=".5" opacity=".12" />)}{series.map(([key, , color]) => points.length === 1 ? <circle key={key} cx="300" cy={120 - Math.max(0, Math.min(100, Number(points[0][key]) || 0)) * 1.2} r="3" fill={color} /> : <polyline key={key} points={line(key)} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" />)}</svg><span>0%</span></div><div className="ops-chart-labels"><span>Oldest sample</span><span>{points.length} heartbeats · newest sample</span></div></div>;
}

const providers = {
  metrics: { name: "Custom metrics", description: "Connect scripts and monitoring tools through a named metrics webhook.", icon: "↗", sample: { metrics: [{ name: "connection.test", value: 1, host: "proofos-test" }] } },
  grafana: { name: "Grafana Alerting", description: "Bring firing and resolved Grafana alerts into your operations queue.", icon: "◉", sample: { status: "firing", alerts: [{ labels: { alertname: "Integration test", severity: "info" }, annotations: { summary: "ProofOS webhook test" } }] } },
  alertmanager: { name: "Prometheus Alertmanager", description: "Receive Alertmanager webhook notifications with severity and context.", icon: "△", sample: { status: "firing", alerts: [{ labels: { alertname: "Integration test", severity: "info" }, annotations: { summary: "ProofOS webhook test" } }] } },
  otlp: { name: "OpenTelemetry", description: "Receive logs and traces over OTLP/HTTP JSON. Traces also build your service map.", icon: "≋", testPath: "/v1/logs", sample: { resourceLogs: [{ resource: { attributes: [{ key: "service.name", value: { stringValue: "proofos-test" } }] }, scopeLogs: [{ logRecords: [{ severityText: "INFO", body: { stringValue: "ProofOS connection test" } }] }] }] } },
};

export function IntegrationsPage({ api, orgId, apiBase }) {
  const [rows, setRows] = useState([]);
  const [provider, setProvider] = useState("metrics");
  const [name, setName] = useState("");
  const [created, setCreated] = useState(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [metrics, setMetrics] = useState([]);
  async function load() { try { const [connections, samples] = await Promise.all([api(`/v1/integrations/connections?org_id=${orgId}`), api(`/v1/integrations/metrics?org_id=${orgId}&limit=20`)]); setRows(connections); setMetrics(samples); } catch (e) { setError(e.message); } }
  useEffect(() => { setCreated(null); load(); }, [orgId]);
  async function create(e) {
    e.preventDefault(); setBusy(true); setError(""); setNotice("");
    try { setCreated(await api(`/v1/integrations/connections?org_id=${orgId}`, { method: "POST", body: JSON.stringify({ name, provider }) })); setName(""); await load(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function test() {
    setBusy(true); setError(""); setNotice("");
    try {
      const response = await fetch(`${apiBase}${created.webhook_path}${providers[created.provider].testPath || ""}`, { method: "POST", headers: { "Content-Type": "application/json", "X-Integration-Token": created.token }, body: JSON.stringify(providers[created.provider].sample) });
      if (!response.ok) throw new Error(`Webhook test failed (${response.status})`);
      setNotice(created.provider === "otlp" ? "Delivery accepted. A labeled test log record is now in Telemetry." : "Delivery accepted. A labeled test record was added to metrics or alerts."); await load();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  return <div className="ops-page">
    <PageHead eyebrow="Connected operations" title="Signals, in one place." description="Authenticated inbound connections with revocable credentials and real delivery status."><button className="ops-button" onClick={load}>Refresh status</button></PageHead>
    {error && <p role="alert">{error}</p>}{notice && <p className="ops-note" role="status">{notice}</p>}
    <div className="ops-provider-grid">{Object.entries(providers).map(([key, p]) => <button key={key} className={`card ops-provider ${provider === key ? "selected" : ""}`} aria-pressed={provider === key} onClick={() => setProvider(key)}><span className="ops-provider-icon">{p.icon}</span><strong>{p.name}</strong><p>{p.description}</p><span className="ops-link">{provider === key ? "Selected" : "Configure →"}</span></button>)}</div>
    <form className="card ops-connect-form" onSubmit={create}><div><h2>Connect {providers[provider].name}</h2><p>Use a separate connection for each source or environment.</p></div><label>Connection name<input required minLength={2} maxLength={100} placeholder="e.g. Production monitoring" value={name} onChange={(e) => setName(e.target.value)} /></label><button className="ops-button primary" disabled={busy}>{busy ? "Working…" : "Create connection"}</button></form>
    {created && <section className="card ops-credential"><div className="ops-toolbar"><div><h2>Configure your source</h2><p>Copy this credential now. It is shown once and stored as a hash.</p></div><button className="ops-button" onClick={() => setCreated(null)}>Dismiss credential</button></div><label>{created.provider === "otlp" ? "OTLP/HTTP endpoint (the exporter appends /v1/logs and /v1/traces)" : "Webhook URL"}<code>{`${apiBase || window.location.origin}${created.webhook_path}`}</code></label><label>HTTP header<code>X-Integration-Token: {created.token}</code></label><p className="ops-muted">{created.provider === "otlp" ? "In your OpenTelemetry Collector, add an otlphttp exporter with this endpoint, encoding: json, and the header above. Credential-shaped values are redacted on arrival." : created.provider === "metrics" ? "POST a JSON metrics array using this format." : "Add a webhook contact point/receiver in your monitoring source and set the custom header above. Firing alerts create records; resolved notifications arrive acknowledged."}</p><pre>{JSON.stringify(providers[created.provider].sample, null, 2)}</pre><button className="ops-button primary" type="button" disabled={busy} onClick={test}>Send labeled test event</button></section>}
    <div className="ops-toolbar"><h2 className="ops-section-title">Your connections</h2><span className="ops-muted">{rows.length} configured</span></div>
    <DataTable columns={["Connection", "Delivery status", "Deliveries", "Last received", "Access"]}>{rows.map((r) => <tr key={r.id}><td><strong>{r.name}</strong><small>{providers[r.provider]?.name || r.provider}</small></td><td><Status tone={!r.enabled ? "neutral" : r.last_received_at ? "good" : "warn"}>{!r.enabled ? "Disabled" : r.last_received_at ? "Delivery received" : "Awaiting first delivery"}</Status></td><td>{r.received_count}</td><td>{date(r.last_received_at)}</td><td>{r.enabled ? <button className="ops-link" disabled={busy} onClick={async () => { setBusy(true); try { await api(`/v1/integrations/connections/${r.id}/disable`, { method: "POST", body: "{}" }); if (created?.id === r.id) setCreated(null); await load(); } catch (e) { setError(e.message); } finally { setBusy(false); } }}>Disable</button> : "Revoked"}</td></tr>)}</DataTable>
    {!rows.length && <Empty title="Ready for your first connection">Choose a source, create a credential, and send a test event to verify delivery.</Empty>}
    {metrics.length > 0 && <><h2 className="ops-section-title">Recent incoming metrics</h2><DataTable columns={["Metric", "Source / host", "Value", "Received"]}>{metrics.map((m) => <tr key={m.id}><td><strong>{m.name}</strong></td><td>{m.source}<small>{m.host || "No host specified"}</small></td><td><code>{m.value}</code></td><td>{date(m.created_at?.endsWith("Z") || /[+-]\d\d:\d\d$/.test(m.created_at || "") ? m.created_at : `${m.created_at}Z`)}</td></tr>)}</DataTable></>}
  </div>;
}

export function ReportsPage({ api, orgId, apiBase, onNavigate }) {
  const [days, setDays] = useState(30);
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  async function load() { setLoading(true); setError(""); try { setReport(await api(`/v1/reports/operations?org_id=${orgId}&days=${days}`)); } catch (e) { setError(e.message); } finally { setLoading(false); } }
  useEffect(() => { load(); }, [orgId, days]);
  async function download(kind) {
    try {
      const response = await fetch(`${apiBase}/v1/reports/export?org_id=${orgId}&kind=${kind}`, { headers: { Authorization: `Bearer ${localStorage.getItem("proofos_token") || ""}` } });
      if (!response.ok) throw new Error(`Export failed (${response.status})`);
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = `proofos-${kind}.csv`; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError(e.message); }
  }
  const daily = report?.tickets.daily_created || [];
  const peak = Math.max(1, ...daily.map((d) => d.count));
  return <div className="ops-page">
    <PageHead eyebrow="Operational reporting" title="See what needs attention." description="A complete workspace snapshot, with period-based ticket and execution activity."><select aria-label="Reporting period" value={days} onChange={(e) => setDays(Number(e.target.value))}>{[7, 30, 90].map((d) => <option key={d} value={d}>Last {d} days</option>)}</select><button className="ops-button" disabled={loading} onClick={load}>{loading ? "Updating…" : "Refresh report"}</button></PageHead>
    {error && <p role="alert">{error}</p>}
    {report && <>
      <Metrics items={[["Managed endpoints", report.devices.total, `${report.devices.by_status.online || 0} online now`], ["Open service work", report.tickets.open, `${report.tickets.overdue} past SLA due time`], ["Critical patch backlog", report.patches.critical_pending, "Pending or failed critical patches"], ["Active critical alerts", report.alerts.critical, `${report.alerts.unacknowledged} total unacknowledged`]]} />
      <div className="ops-report-grid"><section className="card ops-report-card"><div className="ops-toolbar"><div><h2>Service demand</h2><p>Tickets created per UTC day · last {report.days} days</p></div><strong className="ops-chart-total">{report.tickets.created_in_period}</strong></div><div className="ops-chart" role="img" aria-label={`${report.tickets.created_in_period} tickets created over ${report.days} days`}>{daily.map((d) => <div className="ops-chart-column" key={d.date} title={`${d.date}: ${d.count} tickets`}><div style={{ height: `${d.count ? Math.max(3, d.count / peak * 100) : 0}%` }} /></div>)}</div><div className="ops-chart-labels"><span>{daily[0]?.date}</span><span>{daily.at(-1)?.date}</span></div><div className="ops-report-footer"><span>{report.tickets.resolved_in_cohort} tickets in this cohort are resolved or closed</span><strong>{report.tickets.resolution_rate == null ? "No activity" : `${report.tickets.resolution_rate}%`}</strong></div></section>
      <section className="card ops-report-card"><h2>Collection & execution</h2><p>Coverage you can verify</p><div className="ops-progress-list">{[["Inventory collected", report.devices.with_inventory, report.devices.total], ["Inventory within 24h", report.devices.fresh_inventory, report.devices.total], ["Integrations receiving in 24h", report.integrations.receiving, report.integrations.enabled]].map(([label, value, total]) => <div key={label}><div><span>{label}</span><strong>{value} / {total}</strong></div><div className="ops-progress-track"><span style={{ width: `${total ? Math.min(value / total * 100, 100) : 0}%` }} /></div></div>)}</div><div className="ops-report-footer"><span>Completed executions in period</span><strong>{report.execution.completed} <small>· {report.execution.failed} failed</small></strong></div></section></div>
      <section className="card ops-attention"><div><p className="ops-eyebrow">Action queue</p><h2>Turn the report into progress.</h2></div><div>{[["tickets", "Resolve overdue service work", `${report.tickets.overdue} tickets past due`], ["patches", "Reduce patch exposure", `${report.patches.critical_pending} critical patches waiting`], ["inventory", "Complete inventory coverage", `${report.devices.total - report.devices.with_inventory} endpoints not collected`], ["integrations", "Verify incoming signals", `${report.integrations.enabled - report.integrations.receiving} enabled sources without delivery in 24h`]].map(([view, title, detail]) => <button key={view} onClick={() => onNavigate(view)}><span><strong>{title}</strong><small>{detail}</small></span><span aria-hidden="true">↗</span></button>)}</div></section>
      <div className="ops-toolbar"><div><h2 className="ops-section-title">Export workspace data</h2><p className="ops-muted">Full current records, independent of the activity period. CSV files are safe for spreadsheet use.</p></div><div className="ops-export-actions">{["devices", "software", "tickets", "patches", "integrations"].map((kind) => <button className="ops-button" key={kind} onClick={() => download(kind)}>↓ {kind[0].toUpperCase() + kind.slice(1)}</button>)}</div></div>
      <p className="ops-muted">Generated {date(report.generated_at)} · All figures are scoped to your workspace. Inventory is fresh when received within 24 hours.</p>
    </>}
  </div>;
}

export { DataTable, Empty, Metrics, PageHead, Status };
