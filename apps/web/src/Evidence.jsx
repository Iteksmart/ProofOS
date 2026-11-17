import React, { useEffect, useMemo, useState } from "react";
import { DataTable, Empty, Metrics, PageHead, Status } from "./Operations";
import { ProbableCause } from "./Assurance";

const date = (value) => (value ? new Date(value).toLocaleString() : "—");
const tone = (health) => ({ healthy: "good", degraded: "warn", down: "bad" }[health] || "neutral");
const severityTone = (s) => (["ERROR", "FATAL", "CRITICAL"].includes(s) ? "bad" : s === "WARN" || s === "WARNING" ? "warn" : s === "OK" ? "good" : "neutral");

/* ------------------------------------------------------------------ */
/* Topology                                                            */
/* ------------------------------------------------------------------ */

const NODE_W = 176;
const NODE_H = 50;
const COL_GAP = 232;
const ROW_GAP = 78;

function layout(nodes, edges) {
  const depth = Object.fromEntries(nodes.map((n) => [n.id, 0]));
  // Longest-path layering; the iteration cap keeps cycles from looping forever.
  for (let pass = 0; pass < nodes.length; pass += 1) {
    let changed = false;
    for (const e of edges) {
      if (depth[e.source_id] == null || depth[e.target_id] == null) continue;
      const next = Math.min(nodes.length - 1, depth[e.source_id] + 1);
      if (depth[e.target_id] < next) { depth[e.target_id] = next; changed = true; }
    }
    if (!changed) break;
  }
  const columns = {};
  nodes.forEach((n) => { (columns[depth[n.id]] ||= []).push(n); });
  const position = {};
  Object.entries(columns).forEach(([col, items]) => items.forEach((n, row) => { position[n.id] = { x: 24 + Number(col) * COL_GAP, y: 24 + row * ROW_GAP }; }));
  const cols = Object.keys(columns).length || 1;
  const rows = Math.max(1, ...Object.values(columns).map((c) => c.length));
  return { position, width: 48 + (cols - 1) * COL_GAP + NODE_W, height: 48 + (rows - 1) * ROW_GAP + NODE_H };
}

function TopologyGraph({ nodes, edges, selected, highlighted, onSelect }) {
  const { position, width, height } = useMemo(() => layout(nodes, edges), [nodes, edges]);
  return (
    <div className="card topo-canvas">
      <svg viewBox={`0 0 ${width} ${height}`} style={{ minWidth: Math.min(width, 560), width: "100%", maxHeight: 520 }} role="group" aria-label="Service dependency graph">
        <defs>
          <marker id="topo-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 10 5 0 10z" className="topo-arrow" /></marker>
        </defs>
        {edges.map((e) => {
          const a = position[e.source_id], b = position[e.target_id];
          if (!a || !b) return null;
          const sx = a.x + NODE_W, sy = a.y + NODE_H / 2, tx = b.x, ty = b.y + NODE_H / 2;
          const bend = Math.max(48, Math.abs(tx - sx) / 2);
          const active = selected && (e.source_id === selected || e.target_id === selected || (highlighted.has(e.source_id) && highlighted.has(e.target_id)));
          return <path key={e.id} d={`M${sx} ${sy} C${sx + bend} ${sy}, ${tx - bend} ${ty}, ${tx} ${ty}`} className={`topo-edge ${e.origin} ${active ? "active" : ""}`} markerEnd="url(#topo-arrow)"><title>{e.origin === "trace" ? "Observed in traces" : "Declared manually"}</title></path>;
        })}
        {nodes.map((n) => {
          const p = position[n.id];
          const dim = selected && n.id !== selected && !highlighted.has(n.id);
          return (
            <g key={n.id} transform={`translate(${p.x} ${p.y})`} className={`topo-node ${n.health} ${selected === n.id ? "selected" : ""} ${dim ? "dim" : ""}`} role="button" tabIndex={0}
              aria-label={`${n.name}, ${n.health}`} aria-pressed={selected === n.id} onClick={() => onSelect(n.id)} onKeyDown={(ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onSelect(n.id); } }}>
              <rect width={NODE_W} height={NODE_H} rx="12" />
              <circle cx="18" cy={NODE_H / 2} r="5" />
              <text x="32" y="22">{n.name.length > 20 ? `${n.name.slice(0, 19)}…` : n.name}</text>
              <text x="32" y="38" className="sub">{n.health}{n.device_id ? " · endpoint linked" : ""}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function TopologyPage({ api, devices, canWrite, onOpenDevice }) {
  const [graph, setGraph] = useState({ nodes: [], edges: [] });
  const [selected, setSelected] = useState(null);
  const [impact, setImpact] = useState(null);
  const [service, setService] = useState({ name: "", device_id: "" });
  const [dependency, setDependency] = useState({ source_id: "", target_id: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true); setError("");
    try { setGraph(await api("/v1/topology")); } catch (e) { setError(e.message); } finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);
  useEffect(() => {
    setImpact(null);
    if (!selected) return;
    let current = true;
    api(`/v1/topology/impact/${selected}`).then((r) => { if (current) setImpact(r); }).catch((e) => { if (current) setError(e.message); });
    return () => { current = false; };
  }, [selected, graph]);

  async function act(fn) { setError(""); try { await fn(); await load(); } catch (e) { setError(e.message); } }
  const node = graph.nodes.find((n) => n.id === selected);
  const highlighted = new Set([...(impact?.dependents || []), ...(impact?.dependencies || [])].map((n) => n.id));
  const attention = graph.nodes.filter((n) => n.health === "degraded" || n.health === "down");
  const device = node?.device_id ? devices.find((d) => d.id === node.device_id) : null;

  return (
    <div className="ops-page">
      <PageHead eyebrow="Service topology" title="See what depends on what." description="Dependencies are declared by your team or observed from distributed traces. Health is derived only from evidence.">
        <button className="ops-button" onClick={load} disabled={loading}>{loading ? "Refreshing…" : "Refresh map"}</button>
      </PageHead>
      {error && <p role="alert">{error}</p>}
      <Metrics items={[
        ["Services", graph.nodes.length, "Declared or discovered"],
        ["Dependencies", graph.edges.length, `${graph.edges.filter((e) => e.origin === "trace").length} observed in traces`],
        ["Needs attention", attention.length, attention.length ? attention.map((n) => n.name).slice(0, 3).join(", ") : "No degraded services"],
        ["No evidence", graph.nodes.filter((n) => n.health === "unknown").length, "Health unknown, not assumed"],
      ]} />

      {graph.nodes.length ? (
        <div className="topo-layout">
          <TopologyGraph nodes={graph.nodes} edges={graph.edges} selected={selected} highlighted={highlighted} onSelect={(id) => setSelected(id === selected ? null : id)} />
          <aside className="card topo-detail" aria-live="polite">
            {node ? <>
              <div className="ops-toolbar"><h2>{node.name}</h2><Status tone={tone(node.health)}>{node.health}</Status></div>
              <p className="ops-muted">Why: {node.evidence.join("; ")}.</p>
              {device && <button className="ops-link" onClick={() => onOpenDevice(device.id)}>Open endpoint {device.hostname} →</button>}
              <h3 className="ops-section-title mt-4">If this fails, these are affected</h3>
              {impact ? (impact.dependents.length ? <ul className="topo-list">{impact.dependents.map((d) => <li key={d.id}><button onClick={() => setSelected(d.id)}>{d.name}</button></li>)}</ul> : <p className="ops-muted">Nothing recorded depends on this service.</p>) : <p className="ops-muted">Calculating…</p>}
              <h3 className="ops-section-title mt-4">It depends on</h3>
              {impact ? (impact.dependencies.length ? <ul className="topo-list">{impact.dependencies.map((d) => <li key={d.id}><button onClick={() => setSelected(d.id)}>{d.name}</button></li>)}</ul> : <p className="ops-muted">No recorded dependencies.</p>) : null}
              {impact && <p className="ops-muted mt-3">{impact.scope}</p>}
              {node.health !== "healthy" && <ProbableCause api={api} nodeId={node.id} onSelect={setSelected} />}
              {canWrite && <button className="btn-danger rounded-lg px-3 py-2 text-xs mt-4" onClick={() => { if (window.confirm(`Remove ${node.name} and its dependencies from the map?`)) act(async () => { await api(`/v1/topology/services/${node.id}`, { method: "DELETE" }); setSelected(null); }); }}>Remove service</button>}
            </> : <><h2>Impact analysis</h2><p className="ops-muted">Select a service to see what it depends on and what breaks if it fails.</p><div className="topo-legend"><span><i className="trace" />Observed in traces</span><span><i className="manual" />Declared manually</span></div></>}
          </aside>
        </div>
      ) : !loading && <Empty title="Your service map starts here">Declare a service below, or send traces through an OpenTelemetry connection — services and their dependencies are added as soon as parent and child spans arrive.</Empty>}

      {canWrite && (
        <div className="evidence-forms">
          <form className="card ops-connect-form" onSubmit={(e) => { e.preventDefault(); act(async () => { await api("/v1/topology/services", { method: "POST", body: JSON.stringify({ name: service.name, device_id: service.device_id ? Number(service.device_id) : null }) }); setService({ name: "", device_id: "" }); }); }}>
            <div><h2>Declare a service</h2><p>Link it to an endpoint to include endpoint status in its health.</p></div>
            <label>Service name<input required minLength={2} maxLength={255} value={service.name} onChange={(e) => setService({ ...service, name: e.target.value })} placeholder="e.g. billing-api" /></label>
            <label>Runs on endpoint<select value={service.device_id} onChange={(e) => setService({ ...service, device_id: e.target.value })}><option value="">Not linked</option>{devices.map((d) => <option key={d.id} value={d.id}>{d.hostname}</option>)}</select></label>
            <button className="ops-button primary" type="submit">Add service</button>
          </form>
          <form className="card ops-connect-form" onSubmit={(e) => { e.preventDefault(); act(async () => { await api("/v1/topology/dependencies", { method: "POST", body: JSON.stringify({ source_id: Number(dependency.source_id), target_id: Number(dependency.target_id) }) }); setDependency({ source_id: "", target_id: "" }); }); }}>
            <div><h2>Declare a dependency</h2><p>The first service calls, and therefore depends on, the second.</p></div>
            <label>Service<select required value={dependency.source_id} onChange={(e) => setDependency({ ...dependency, source_id: e.target.value })}><option value="">Choose…</option>{graph.nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}</select></label>
            <label>Depends on<select required value={dependency.target_id} onChange={(e) => setDependency({ ...dependency, target_id: e.target.value })}><option value="">Choose…</option>{graph.nodes.filter((n) => String(n.id) !== dependency.source_id).map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}</select></label>
            <button className="ops-button primary" type="submit" disabled={graph.nodes.length < 2}>Add dependency</button>
          </form>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Telemetry                                                           */
/* ------------------------------------------------------------------ */

function TraceWaterfall({ trace, onClose }) {
  const spans = trace.spans;
  const start = Math.min(...spans.map((s) => new Date(s.observed_at).getTime()));
  const end = Math.max(...spans.map((s) => new Date(s.observed_at).getTime() + s.duration_ms));
  const total = Math.max(1, end - start);
  return (
    <section className="card ops-report-card" aria-label="Trace detail">
      <div className="ops-toolbar"><div><h2>Trace {trace.trace_id.slice(0, 12)}…</h2><p>{spans.length} spans · {new Set(spans.map((s) => s.service)).size} services · {total.toFixed(0)} ms end to end</p></div><button className="ops-button" onClick={onClose}>Close trace</button></div>
      <div className="trace-waterfall">
        {spans.map((s) => {
          const offset = ((new Date(s.observed_at).getTime() - start) / total) * 100;
          const width = Math.max(1.2, (s.duration_ms / total) * 100);
          return <div key={s.id} className="trace-row"><span className="trace-label"><strong>{s.service}</strong><small>{s.name || "span"}</small></span><span className="trace-track"><i className={s.severity === "ERROR" ? "bad" : ""} style={{ left: `${Math.min(offset, 98.8)}%`, width: `${Math.min(width, 100 - Math.min(offset, 98.8))}%` }} /></span><span className="trace-time">{s.duration_ms.toFixed(1)} ms</span></div>;
        })}
      </div>
      {trace.logs.length > 0 && <><h3 className="ops-section-title mt-4">Logs in this trace</h3>{trace.logs.map((l) => <p key={l.id} className="telemetry-line"><Status tone={severityTone(l.severity)}>{l.severity}</Status><span>{l.service}</span><code>{l.body}</code></p>)}</>}
    </section>
  );
}

export function TelemetryPage({ api, onNavigate }) {
  const [summary, setSummary] = useState({ services: [], window_minutes: 60 });
  const [events, setEvents] = useState([]);
  const [filter, setFilter] = useState("all");
  const [service, setService] = useState("");
  const [query, setQuery] = useState("");
  const [trace, setTrace] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true); setError("");
    const params = new URLSearchParams({ limit: "150" });
    if (filter === "log" || filter === "span") params.set("kind", filter);
    if (filter === "errors") params.set("severity", "errors");
    if (service) params.set("service", service);
    if (query.trim()) params.set("q", query.trim());
    try {
      const [s, e] = await Promise.all([api("/v1/telemetry/services"), api(`/v1/telemetry/events?${params}`)]);
      setSummary(s); setEvents(e);
    } catch (e) { setError(e.message); } finally { setLoading(false); }
  }
  useEffect(() => { const timer = setTimeout(load, query ? 220 : 0); return () => clearTimeout(timer); }, [filter, service, query]);

  const rows = summary.services;
  const spans = rows.reduce((n, r) => n + r.spans, 0);
  const spanErrors = rows.reduce((n, r) => n + r.span_errors, 0);
  const slowest = rows.filter((r) => r.p95_ms != null).sort((a, b) => b.p95_ms - a.p95_ms)[0];

  return (
    <div className="ops-page">
      <PageHead eyebrow="Logs & traces" title="Follow a request end to end." description="OpenTelemetry logs and spans, searchable in one place. Credentials are redacted before anything is stored.">
        <button className="ops-button" onClick={() => onNavigate("integrations")}>Connect a collector</button>
        <button className="ops-button" onClick={load} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button>
      </PageHead>
      {error && <p role="alert">{error}</p>}
      <Metrics items={[
        ["Services reporting", rows.length, `Last ${summary.window_minutes} minutes`],
        ["Spans", spans, `${spanErrors} failed`],
        ["Log records", rows.reduce((n, r) => n + r.logs, 0), `${rows.reduce((n, r) => n + r.log_errors, 0)} at error level`],
        ["Slowest p95", slowest ? `${slowest.p95_ms} ms` : "—", slowest ? slowest.service : "No spans yet"],
      ]} />

      {rows.length > 0 && <DataTable columns={["Service", "Spans", "Error rate", "p95 latency", "Logs", "Last received"]}>
        {rows.map((r) => <tr key={r.service}><td><button className="ops-link" onClick={() => setService(r.service)}>{r.service}</button></td><td>{r.spans}</td><td>{r.error_rate == null ? "—" : <Status tone={r.error_rate >= 0.1 ? "bad" : r.error_rate > 0 ? "warn" : "good"}>{(r.error_rate * 100).toFixed(1)}%</Status>}</td><td>{r.p95_ms == null ? "—" : `${r.p95_ms} ms`}</td><td>{r.logs}{r.log_errors ? <small>{r.log_errors} errors</small> : null}</td><td>{date(r.last_received_at)}</td></tr>)}
      </DataTable>}

      {trace && <TraceWaterfall trace={trace} onClose={() => setTrace(null)} />}

      <div className="ops-toolbar">
        <div className="segmented" role="group" aria-label="Telemetry filter">{[["all", "All"], ["log", "Logs"], ["span", "Spans"], ["errors", "Errors"]].map(([key, label]) => <button key={key} aria-pressed={filter === key} onClick={() => setFilter(key)}>{label}</button>)}</div>
        <div className="ops-head-actions">
          <select aria-label="Filter by service" value={service} onChange={(e) => setService(e.target.value)}><option value="">All services</option>{rows.map((r) => <option key={r.service} value={r.service}>{r.service}</option>)}</select>
          <input aria-label="Search telemetry" placeholder="Search messages and span names…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
      </div>

      {events.length ? <div className="card telemetry-stream">
        {events.map((ev) => <div key={ev.id} className="telemetry-line">
          <Status tone={severityTone(ev.severity)}>{ev.kind === "span" ? (ev.severity === "ERROR" ? "SPAN ERR" : "SPAN") : ev.severity}</Status>
          <time>{date(ev.observed_at)}</time>
          <span>{ev.service}</span>
          <code>{ev.kind === "span" ? `${ev.name} · ${ev.duration_ms.toFixed(1)} ms${ev.body ? ` · ${ev.body}` : ""}` : ev.body}</code>
          {ev.trace_id && <button className="ops-link" onClick={async () => { try { setTrace(await api(`/v1/telemetry/traces/${ev.trace_id}`)); window.scrollTo({ top: 0, behavior: "smooth" }); } catch (e) { setError(e.message); } }}>View trace</button>}
        </div>)}
      </div> : !loading && <Empty title={rows.length || query || service || filter !== "all" ? "No matching telemetry" : "Waiting for your first telemetry"}>{rows.length || query || service || filter !== "all" ? "Adjust the filter, service, or search text." : "Create an OpenTelemetry connection in Integrations, then point a collector's OTLP/HTTP JSON exporter at it. Logs and traces appear here, and service dependencies are added to Topology."}</Empty>}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Privileged access                                                   */
/* ------------------------------------------------------------------ */

function remaining(expires) {
  const ms = new Date(expires).getTime() - Date.now();
  if (ms <= 0) return "expired";
  const minutes = Math.floor(ms / 60000);
  return minutes >= 1 ? `${minutes} min left` : `${Math.ceil(ms / 1000)} s left`;
}

export function AccessPage({ api, orgId, devices, users, claims }) {
  const privileged = ["admin", "manager"].includes(claims.role);
  const me = Number(claims.sub);
  const [grants, setGrants] = useState([]);
  const [secrets, setSecrets] = useState([]);
  const [form, setForm] = useState({ capability: "device_command", target_id: "", command: "", reason: "", minutes: 15 });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [, tick] = useState(0);

  async function load() {
    try {
      const [g, s] = await Promise.all([api("/v1/access"), api(`/v1/secrets?org_id=${orgId}`).catch(() => [])]);
      setGrants(g); setSecrets(Array.isArray(s) ? s : []);
    } catch (e) { setError(e.message); }
  }
  useEffect(() => { load(); const timer = setInterval(() => tick((n) => n + 1), 15000); return () => clearInterval(timer); }, [orgId]);

  async function act(fn, message) { setError(""); setNotice(""); try { await fn(); if (message) setNotice(message); await load(); } catch (e) { setError(e.message); } }
  const targets = form.capability === "device_command" ? devices.map((d) => [d.id, d.hostname]) : secrets.map((s) => [s.id, s.name]);
  const targetName = (g) => (g.capability === "device_command" ? devices.find((d) => d.id === g.target_id)?.hostname : secrets.find((s) => s.id === g.target_id)?.name) || `#${g.target_id}`;
  const who = (id) => users.find((u) => u.id === id)?.email || (id === me ? "You" : `User #${id}`);
  const live = (g) => g.status === "approved" && new Date(g.expires_at).getTime() > Date.now();
  const pending = grants.filter((g) => g.status === "pending");

  return (
    <div className="ops-page">
      <PageHead eyebrow="Privileged access" title="Access that expires on its own." description="Engineers request one command on one endpoint, or one vault secret, for minutes at a time. A different privileged user approves, and every use is signed.">
        <button className="ops-button" onClick={load}>Refresh</button>
      </PageHead>
      {error && <p role="alert">{error}</p>}{notice && <p className="ops-note" role="status">{notice}</p>}
      <Metrics items={[
        ["Awaiting decision", pending.length, privileged ? "Requests you can review" : "Your open requests"],
        ["Active now", grants.filter(live).length, "Approved and unexpired"],
        ["Standing access", 0, "Grants never outlive their window"],
        ["Recorded", grants.length, privileged ? "All requests in this workspace" : "Your requests"],
      ]} />

      <form className="card ops-connect-form access-form" onSubmit={(e) => { e.preventDefault(); act(async () => { await api("/v1/access", { method: "POST", body: JSON.stringify({ capability: form.capability, target_id: Number(form.target_id), command: form.capability === "device_command" ? form.command : "", reason: form.reason, minutes: Number(form.minutes) }) }); setForm({ ...form, target_id: "", command: "", reason: "" }); }, "Request submitted. It grants nothing until a different admin or manager approves it."); }}>
        <div><h2>Request access</h2><p>{privileged ? "Admins and managers already hold these capabilities; a request is useful for a recorded, time-boxed exception." : "State exactly what you need and why. The approver sees this text."}</p></div>
        <label>Capability<select value={form.capability} onChange={(e) => setForm({ ...form, capability: e.target.value, target_id: "" })}><option value="device_command">Run one command on an endpoint</option><option value="vault_reveal">Reveal one vault secret</option></select></label>
        <label>{form.capability === "device_command" ? "Endpoint" : "Secret"}<select required value={form.target_id} onChange={(e) => setForm({ ...form, target_id: e.target.value })}><option value="">Choose…</option>{targets.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
        {form.capability === "device_command" && <label className="wide">Exact command<input required maxLength={10000} value={form.command} onChange={(e) => setForm({ ...form, command: e.target.value })} placeholder="e.g. systemctl status nginx" /></label>}
        <label className="wide">Reason<input required minLength={10} maxLength={1000} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} placeholder="Ticket or incident, and what you need to confirm" /></label>
        <label>Duration<select value={form.minutes} onChange={(e) => setForm({ ...form, minutes: e.target.value })}>{[5, 15, 30, 60].map((m) => <option key={m} value={m}>{m} minutes</option>)}</select></label>
        <button className="ops-button primary" type="submit">Submit request</button>
      </form>

      <div className="ops-toolbar"><h2 className="ops-section-title">Requests</h2><span className="ops-muted">{grants.length} recorded</span></div>
      {grants.length ? <DataTable columns={["Request", "Scope", "Reason", "Status", "Decision"]}>
        {grants.map((g) => <tr key={g.id}>
          <td><strong>#{g.id} · {who(g.requester_id)}</strong><small>{g.minutes} minute window</small></td>
          <td><strong>{g.capability === "device_command" ? "Command" : "Vault reveal"} · {targetName(g)}</strong>{g.command && <small><code>{g.command}</code></small>}</td>
          <td>{g.reason}</td>
          <td><Status tone={live(g) ? "good" : g.status === "pending" ? "warn" : g.status === "denied" || g.status === "revoked" ? "bad" : "neutral"}>{g.status}</Status>{live(g) && <small>{remaining(g.expires_at)}</small>}{g.approver_id && g.status !== "pending" && <small>by {who(g.approver_id)}</small>}</td>
          <td>{privileged && g.status === "pending" && <span className="ops-head-actions">
            <button className="ops-button primary" disabled={g.requester_id === me} title={g.requester_id === me ? "A different privileged user must approve your own request" : ""} onClick={() => act(() => api(`/v1/access/${g.id}/approve`, { method: "POST" }), `Request #${g.id} approved for ${g.minutes} minutes.`)}>Approve</button>
            <button className="ops-button" onClick={() => act(() => api(`/v1/access/${g.id}/deny`, { method: "POST" }), `Request #${g.id} denied.`)}>Deny</button></span>}
            {privileged && live(g) && <button className="btn-danger rounded-lg px-3 py-2 text-xs" onClick={() => act(() => api(`/v1/access/${g.id}/revoke`, { method: "POST" }), `Access #${g.id} revoked.`)}>Revoke now</button>}
            {!privileged && g.status === "pending" && <span className="ops-muted">Waiting for approval</span>}</td>
        </tr>)}
      </DataTable> : <Empty title="No access requests yet">Requests, approvals, uses, and revocations all appear here and in the proof ledger.</Empty>}
      <div className="ops-note">A grant covers one capability on one target. For commands, only the exact approved text can run. Expiry is checked every time the grant is used.</div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Recovery verification (shown beside a run's signed evidence)        */
/* ------------------------------------------------------------------ */

const RECOVERY_COPY = {
  unconfigured: ["neutral", "No recovery contract", "Define what healthy looks like for this run. Without it, ProofOS reports the execution result but never claims recovery."],
  awaiting_execution: ["neutral", "Waiting for execution", "The contract is recorded. Probing starts after the agent reports a result."],
  execution_unverified: ["bad", "Execution not verified", "The run failed or its signed result does not match, so recovery cannot be assessed."],
  pending: ["warn", "Collecting observations", "Recovery needs the required number of consecutive passing probes, taken after the run completed."],
  failed: ["bad", "Probe failing", "The most recent probe did not meet the contract."],
  stale: ["warn", "Observations are stale", "The latest probe is more than five minutes old. Probe again for a current answer."],
  evidence_invalid: ["bad", "Evidence does not verify", "A stored observation no longer matches its signed record."],
  healthy: ["good", "Recovery verified", "Consecutive fresh probes passed after execution, and each observation matches its signed record."],
};

export function RecoveryPanel({ api, runId, canWrite }) {
  const [state, setState] = useState(null);
  const [policy, setPolicy] = useState({ kind: "http", target: "", expected_status: 200, samples_required: 3 });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function call(path, options) {
    setBusy(true); setError("");
    try { setState(await api(path, options)); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  useEffect(() => { setState(null); call(`/v1/recovery/${runId}`); }, [runId]);
  if (!state) return error ? <p role="alert">{error}</p> : <p className="ops-muted">Loading recovery state…</p>;
  const [stateTone, title, detail] = RECOVERY_COPY[state.state] || ["neutral", state.state, ""];
  const canSample = canWrite && ["pending", "failed", "stale", "healthy"].includes(state.state);

  return (
    <section className="recovery-panel" aria-label="Recovery verification">
      <div className="ops-toolbar"><div><h3 className="ops-section-title">Recovery verification</h3><p className="ops-muted">{detail}</p></div><Status tone={stateTone}>{title}</Status></div>
      {error && <p role="alert">{error}</p>}
      {state.state === "unconfigured" ? (canWrite ? (
        <form className="recovery-form" onSubmit={(e) => { e.preventDefault(); call(`/v1/recovery/${runId}`, { method: "PUT", body: JSON.stringify({ kind: policy.kind, target: policy.target, expected_status: Number(policy.expected_status), samples_required: Number(policy.samples_required) }) }); }}>
          <label>Probe<select value={policy.kind} onChange={(e) => setPolicy({ ...policy, kind: e.target.value, target: "" })}><option value="http">HTTP status</option><option value="tcp">TCP port</option></select></label>
          <label className="wide">Target<input required minLength={5} value={policy.target} onChange={(e) => setPolicy({ ...policy, target: e.target.value })} placeholder={policy.kind === "http" ? "https://service.internal/health" : "tcp://db.internal:5432"} /></label>
          {policy.kind === "http" && <label>Expected status<input type="number" min={200} max={399} value={policy.expected_status} onChange={(e) => setPolicy({ ...policy, expected_status: e.target.value })} /></label>}
          <label>Passing probes<select value={policy.samples_required} onChange={(e) => setPolicy({ ...policy, samples_required: e.target.value })}>{[2, 3, 4, 5].map((n) => <option key={n} value={n}>{n} in a row</option>)}</select></label>
          <button className="ops-button primary" type="submit" disabled={busy}>Record contract</button>
          <p className="ops-muted wide">The contract cannot be changed after it is recorded, so the definition of healthy is fixed before the result is known.</p>
        </form>
      ) : <p className="ops-muted">An admin or manager can define the recovery contract.</p>) : <>
        <dl className="ops-facts"><div><dt>Probe</dt><dd>{state.policy.kind.toUpperCase()} · <code>{state.policy.target}</code></dd></div>{state.policy.kind === "http" && <div><dt>Expected status</dt><dd>{state.policy.expected_status}</dd></div>}<div><dt>Latency limit</dt><dd>{state.policy.max_latency_ms} ms</dd></div><div><dt>Required</dt><dd>{state.policy.samples_required} consecutive passes</dd></div></dl>
        {state.observations.length > 0 && <ol className="recovery-observations">{state.observations.map((o, i) => <li key={i}><Status tone={o.passed ? "good" : "bad"}>{o.passed ? "Passed" : "Failed"}</Status><span>{date(o.observed_at)}</span><span>{o.latency_ms} ms{o.http_status ? ` · HTTP ${o.http_status}` : ""}{o.error ? ` · ${o.error}` : ""}</span><Status tone={o.intact ? "good" : "bad"}>{o.intact ? "Signed record matches" : "Record mismatch"}</Status></li>)}</ol>}
        {canSample && <button className="ops-button primary" disabled={busy} onClick={() => call(`/v1/recovery/${runId}/sample`, { method: "POST" })}>{busy ? "Probing…" : "Probe now"}</button>}
      </>}
      <p className="ops-muted">{state.scope || "A probe checks one configured target. It does not assert whole-system recovery or endpoint integrity."}</p>
    </section>
  );
}
