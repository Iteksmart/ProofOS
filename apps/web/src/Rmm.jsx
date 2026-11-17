import React, { useEffect, useState } from "react";
import { DataTable, Empty, Metrics, Status } from "./Operations";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const SEVERITIES = ["critical", "important", "moderate", "low"];
const DEVICE_TYPES = ["workstation", "server", "access_point", "gateway", "switch", "node"];
const pad = (h) => `${String(h).padStart(2, "0")}:00`;
const sevTone = (s) => (s === "critical" ? "bad" : s === "important" ? "warn" : "neutral");
const approvalTone = { approved: "good", rejected: "bad", deferred: "warn", unreviewed: "neutral" };

function windowLabel(p) {
  const days = p.window_days.length === 7 ? "Every day" : p.window_days.map((d) => DAYS[d]).join(", ");
  return p.window_start_hour === p.window_end_hour ? `${days}, all day (UTC)` : `${days}, ${pad(p.window_start_hour)}–${pad(p.window_end_hour)} UTC`;
}

const BLANK_POLICY = { name: "", enabled: true, auto_approve: ["critical", "important"], categories: [], device_types: [], customer_id: "", window_days: [0, 1, 2, 3, 4], window_start_hour: 22, window_end_hour: 4, defer_days: 0, reboot: "if_required" };

function toggle(list, value) {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

function PolicyEditor({ initial, customers, onSave, onCancel }) {
  const [p, setP] = useState(initial);
  return (
    <form className="card policy-editor" onSubmit={(e) => { e.preventDefault(); onSave({ ...p, customer_id: p.customer_id ? Number(p.customer_id) : null, window_start_hour: Number(p.window_start_hour), window_end_hour: Number(p.window_end_hour), defer_days: Number(p.defer_days) }); }}>
      <div className="ops-toolbar"><h2>{initial.id ? "Edit patch policy" : "New patch policy"}</h2><label className="switch-label"><input type="checkbox" checked={p.enabled} onChange={(e) => setP({ ...p, enabled: e.target.checked })} /> Enabled</label></div>
      <label>Policy name<input required minLength={2} maxLength={255} value={p.name} onChange={(e) => setP({ ...p, name: e.target.value })} placeholder="e.g. Workstations — weeknights" /></label>
      <fieldset><legend>Approve automatically</legend><div className="chip-row">{SEVERITIES.map((s) => <button type="button" key={s} className={`chip-toggle ${p.auto_approve.includes(s) ? "on" : ""}`} aria-pressed={p.auto_approve.includes(s)} onClick={() => setP({ ...p, auto_approve: toggle(p.auto_approve, s) })}>{s}</button>)}</div><small>Other severities wait for a manual approval.</small></fieldset>
      <fieldset><legend>Device types</legend><div className="chip-row">{DEVICE_TYPES.map((t) => <button type="button" key={t} className={`chip-toggle ${p.device_types.includes(t) ? "on" : ""}`} aria-pressed={p.device_types.includes(t)} onClick={() => setP({ ...p, device_types: toggle(p.device_types, t) })}>{t.replace("_", " ")}</button>)}</div><small>{p.device_types.length ? "Only the selected types." : "All device types."}</small></fieldset>
      <label>Customer<select value={p.customer_id || ""} onChange={(e) => setP({ ...p, customer_id: e.target.value })}><option value="">All customers</option>{customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
      <fieldset><legend>Maintenance window (UTC)</legend><div className="chip-row">{DAYS.map((d, i) => <button type="button" key={d} className={`chip-toggle ${p.window_days.includes(i) ? "on" : ""}`} aria-pressed={p.window_days.includes(i)} onClick={() => setP({ ...p, window_days: toggle(p.window_days, i).sort() })}>{d}</button>)}</div>
        <div className="inline-fields"><label>From<select value={p.window_start_hour} onChange={(e) => setP({ ...p, window_start_hour: e.target.value })}>{Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{pad(h)}</option>)}</select></label><label>Until<select value={p.window_end_hour} onChange={(e) => setP({ ...p, window_end_hour: e.target.value })}>{Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{pad(h)}</option>)}</select></label></div>
        <small>{Number(p.window_start_hour) === Number(p.window_end_hour) ? "Same start and end means the whole day." : Number(p.window_start_hour) > Number(p.window_end_hour) ? "Runs overnight into the next day." : ""}</small></fieldset>
      <div className="inline-fields"><label>Wait before auto-approving<select value={p.defer_days} onChange={(e) => setP({ ...p, defer_days: e.target.value })}>{[0, 1, 3, 7, 14, 30].map((d) => <option key={d} value={d}>{d ? `${d} day${d > 1 ? "s" : ""}` : "No delay"}</option>)}</select></label>
        <label>Reboot<select value={p.reboot} onChange={(e) => setP({ ...p, reboot: e.target.value })}><option value="if_required">Only if the OS requires it</option><option value="always">Always, 5 minutes after patching</option><option value="never">Never</option></select></label></div>
      <div className="ops-head-actions"><button className="ops-button primary" type="submit" disabled={!p.window_days.length}>Save policy</button><button className="ops-button" type="button" onClick={onCancel}>Cancel</button></div>
    </form>
  );
}

export function PatchCenter({ api, devices, customers, canWrite, patches, onChanged }) {
  const [compliance, setCompliance] = useState(null);
  const [policies, setPolicies] = useState([]);
  const [editing, setEditing] = useState(null);
  const [preview, setPreview] = useState(null);
  const [selected, setSelected] = useState(() => new Set());
  const [filter, setFilter] = useState("open");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function load() {
    try {
      const [c, p] = await Promise.all([api("/v1/patching/compliance"), api("/v1/patching/policies")]);
      setCompliance(c); setPolicies(p);
    } catch (e) { setError(e.message); }
  }
  useEffect(() => { load(); }, [patches]);
  async function act(fn, message) {
    setError(""); setNotice("");
    try { const r = await fn(); if (message) setNotice(typeof message === "function" ? message(r) : message); await load(); onChanged(); } catch (e) { setError(e.message); }
  }
  const host = (id) => devices.find((d) => d.id === id)?.hostname || `#${id}`;
  const shown = patches.filter((p) => filter === "all" || (filter === "open" ? ["pending", "failed", "deploying"].includes(p.status) : filter === "approval" ? p.approval === "unreviewed" && ["pending", "failed"].includes(p.status) : p.severity === "critical" && p.status !== "installed"));
  const rate = compliance?.compliance_rate;

  return (
    <div className="ops-section-stack">
      {error && <p role="alert">{error}</p>}{notice && <p className="ops-note" role="status">{notice}</p>}
      {compliance && <Metrics items={[
        ["Patch compliance", rate == null ? "—" : `${Math.round(rate * 100)}%`, `${compliance.compliant_devices} of ${compliance.total_devices} endpoints fully patched`],
        ["Critical outstanding", compliance.critical_patches, `${compliance.pending_patches} patches pending in total`],
        ["Awaiting approval", compliance.awaiting_approval, "Not covered by an auto-approve rule"],
        ["Reboot required", compliance.reboot_required, `${compliance.failed_patches} failed installs to review`],
      ]} />}

      <section className="card ops-report-card">
        <div className="ops-toolbar"><div><h2>Patch policies</h2><p>Approve by severity, deploy inside a maintenance window, and handle reboots automatically. Policies run every few minutes while their window is open.</p></div>{canWrite && !editing && <button className="ops-button primary" onClick={() => setEditing(BLANK_POLICY)}>New policy</button>}</div>
        {editing && <PolicyEditor initial={editing} customers={customers} onCancel={() => setEditing(null)} onSave={(body) => act(async () => { await api(editing.id ? `/v1/patching/policies/${editing.id}` : "/v1/patching/policies", { method: editing.id ? "PUT" : "POST", body: JSON.stringify(body) }); setEditing(null); }, "Policy saved.")} />}
        {policies.length ? <div className="policy-list">{policies.map((p) => <div key={p.id} className="policy-row">
          <div><strong>{p.name}</strong><small>{windowLabel(p)} · auto-approves {p.auto_approve.length ? p.auto_approve.join(", ") : "nothing"} · reboot {p.reboot.replace("_", " ")}{p.device_types.length ? ` · ${p.device_types.join(", ")}` : ""}{p.customer_id ? ` · ${customers.find((c) => c.id === p.customer_id)?.name || "customer"}` : ""}</small></div>
          <Status tone={!p.enabled ? "neutral" : p.window_open ? "good" : "neutral"}>{!p.enabled ? "Disabled" : p.window_open ? "Window open" : p.next_window ? `Next ${new Date(p.next_window).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" })}` : "No window"}</Status>
          <span className="ops-head-actions">
            <button className="ops-button" onClick={() => act(async () => setPreview(await api(`/v1/patching/policies/${p.id}/preview`)))}>Preview</button>
            {canWrite && <><button className="ops-button" onClick={() => setEditing({ ...p, customer_id: p.customer_id || "" })}>Edit</button>
              <button className="ops-button primary" onClick={() => { if (window.confirm(`Deploy "${p.name}" now, outside its maintenance window?`)) act(() => api(`/v1/patching/policies/${p.id}/run`, { method: "POST", body: JSON.stringify({ force: true }) }), (r) => r.ran ? `Queued ${r.runs.length} deployment${r.runs.length === 1 ? "" : "s"} covering ${r.runs.reduce((n, x) => n + x.patch_ids.length, 0)} patches.${r.skipped?.length ? ` Skipped ${r.skipped.length} with no exact package id or KB number; rescan those endpoints.` : ""}` : r.reason); }}>Run now</button></>}
          </span>
        </div>)}</div> : !editing && <Empty title="No patch policies yet">Create a policy to approve and deploy patches automatically inside a maintenance window. Until then, patches deploy only when you approve and run them.</Empty>}
        {preview && <div className="ops-note"><strong>{preview.name}: {preview.patch_count} patch{preview.patch_count === 1 ? "" : "es"} on {preview.devices.length} endpoint{preview.devices.length === 1 ? "" : "s"} would deploy {preview.window_open ? "now" : "in the next window"}.</strong>{preview.devices.map((d) => <p key={d.device_id}>{d.hostname}: {d.patches.map((x) => x.name).join(", ")}</p>)}<button className="ops-link" onClick={() => setPreview(null)}>Close preview</button></div>}
      </section>

      <div className="ops-toolbar">
        <div className="segmented" role="group" aria-label="Patch filter">{[["open", "Outstanding"], ["approval", "Awaiting approval"], ["critical", "Critical"], ["all", "All"]].map(([k, l]) => <button key={k} aria-pressed={filter === k} onClick={() => { setFilter(k); setSelected(new Set()); }}>{l}</button>)}</div>
        {canWrite && selected.size > 0 && <span className="ops-head-actions"><strong className="text-sm">{selected.size} selected</strong>{[["approve", "Approve"], ["defer", "Defer"], ["reject", "Reject"]].map(([d, l]) => <button key={d} className={`ops-button ${d === "approve" ? "primary" : ""}`} onClick={() => act(() => api("/v1/patching/approvals", { method: "POST", body: JSON.stringify({ patch_ids: [...selected], decision: d }) }), `${selected.size} patch${selected.size === 1 ? "" : "es"} ${d === "approve" ? "approved" : d === "defer" ? "deferred" : "rejected"}.`).then(() => setSelected(new Set()))}>{l}</button>)}</span>}
      </div>
      {shown.length ? <DataTable columns={[canWrite ? <input key="all" type="checkbox" aria-label="Select all shown patches" checked={shown.length > 0 && shown.every((p) => selected.has(p.id))} onChange={(e) => setSelected(e.target.checked ? new Set(shown.map((p) => p.id)) : new Set())} /> : "", "Patch", "Endpoint", "Severity", "Approval", "Status", ""]}>
        {shown.map((p) => <tr key={p.id} className={selected.has(p.id) ? "row-selected" : ""}>
          <td>{canWrite && <input type="checkbox" aria-label={`Select ${p.name}`} checked={selected.has(p.id)} onChange={(e) => { const n = new Set(selected); e.target.checked ? n.add(p.id) : n.delete(p.id); setSelected(n); }} />}</td>
          <td><strong>{p.name}</strong><small>{p.category.replace("_", " ")}{p.available_version ? ` · ${p.current_version || "?"} → ${p.available_version}` : ""}</small></td>
          <td>{host(p.device_id)}</td>
          <td><Status tone={sevTone(p.severity)}>{p.severity}</Status></td>
          <td><Status tone={approvalTone[p.approval] || "neutral"}>{p.approval}</Status></td>
          <td><Status tone={p.status === "installed" ? "good" : p.status === "failed" ? "bad" : p.status === "deploying" ? "warn" : "neutral"}>{p.status}</Status></td>
          <td>{canWrite && ["pending", "failed"].includes(p.status) && p.approval !== "rejected" && <button className="ops-link" onClick={() => act(() => api(`/v1/patches/${p.id}/deploy`, { method: "POST", body: "{}" }), (r) => `Deployment queued as run #${r.run_id}. Status changes when the agent reports back.`)}>Deploy now</button>}</td>
        </tr>)}
      </DataTable> : <Empty title={patches.length ? "Nothing in this view" : "No patches reported yet"}>{patches.length ? "Try another filter." : "Run a patch scan from a device's Patches tab, or register patches below."}</Empty>}
    </div>
  );
}

export function ThresholdsPanel({ api, canWrite }) {
  const [rows, setRows] = useState([]);
  const [form, setForm] = useState({ metric: "cpu", limit: 90, samples: 3, severity: "warning", device_type: "" });
  const [error, setError] = useState("");
  async function load() { try { setRows(await api("/v1/thresholds")); } catch (e) { setError(e.message); } }
  useEffect(() => { load(); }, []);
  async function act(fn) { setError(""); try { await fn(); await load(); } catch (e) { setError(e.message); } }
  const label = { cpu: "CPU", mem: "Memory", disk: "Disk" };
  return (
    <section className="card ops-report-card" aria-label="Alert thresholds">
      <div className="ops-toolbar"><div><h2>Alert thresholds</h2><p>Every agent heartbeat is checked against these limits. Alerts open after the limit is held for the set number of samples and resolve themselves when the value recovers.</p></div>
        {canWrite && !rows.length && <button className="ops-button primary" onClick={() => act(() => api("/v1/thresholds/recommended", { method: "POST" }))}>Apply recommended</button>}</div>
      {error && <p role="alert">{error}</p>}
      {rows.length ? <div className="policy-list">{rows.map((t) => <div key={t.id} className="policy-row">
        <div><strong>{label[t.metric]} ≥ {t.limit}%</strong><small>for {t.samples} consecutive sample{t.samples > 1 ? "s" : ""} · {t.device_type ? t.device_type.replace("_", " ") + "s" : "all device types"}</small></div>
        <Status tone={t.severity === "critical" ? "bad" : t.severity === "warning" ? "warn" : "neutral"}>{t.severity}</Status>
        {canWrite ? <span className="ops-head-actions"><label className="switch-label"><input type="checkbox" checked={t.enabled} onChange={(e) => act(() => api(`/v1/thresholds/${t.id}`, { method: "PUT", body: JSON.stringify({ ...t, enabled: e.target.checked }) }))} /> On</label><button className="ops-link" onClick={() => act(() => api(`/v1/thresholds/${t.id}`, { method: "DELETE" }))}>Remove</button></span> : <span />}
      </div>)}</div> : <p className="ops-muted">No thresholds yet, so heartbeats never raise metric alerts.</p>}
      {canWrite && <form className="inline-fields threshold-form" onSubmit={(e) => { e.preventDefault(); act(() => api("/v1/thresholds", { method: "POST", body: JSON.stringify({ ...form, limit: Number(form.limit), samples: Number(form.samples) }) })); }}>
        <label>Metric<select value={form.metric} onChange={(e) => setForm({ ...form, metric: e.target.value })}><option value="cpu">CPU</option><option value="mem">Memory</option><option value="disk">Disk</option></select></label>
        <label>Limit (%)<input type="number" min={1} max={100} value={form.limit} onChange={(e) => setForm({ ...form, limit: e.target.value })} /></label>
        <label>Samples<input type="number" min={1} max={20} value={form.samples} onChange={(e) => setForm({ ...form, samples: e.target.value })} /></label>
        <label>Severity<select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}><option>info</option><option>warning</option><option>critical</option></select></label>
        <label>Applies to<select value={form.device_type} onChange={(e) => setForm({ ...form, device_type: e.target.value })}><option value="">All types</option>{DEVICE_TYPES.map((t) => <option key={t} value={t}>{t.replace("_", " ")}</option>)}</select></label>
        <button className="ops-button" type="submit">Add threshold</button>
      </form>}
    </section>
  );
}

export function AgentInstall({ apiBase, device }) {
  const api = apiBase || window.location.origin;
  const download = `${window.location.origin}/downloads/proofos-agent.py`;
  const [os, setOs] = useState(/windows/i.test(device.os || "") ? "windows" : /mac/i.test(device.os || "") ? "macos" : "linux");
  const args = `--api ${api} --device-id ${device.id} --token ${device.device_secret}`;
  const commands = {
    linux: `curl -fsSL ${download} -o proofos-agent.py && python3 -m pip install --user httpx psutil && python3 proofos-agent.py ${args}`,
    macos: `curl -fsSL ${download} -o proofos-agent.py && python3 -m pip install --user httpx psutil && python3 proofos-agent.py ${args}`,
    windows: `Invoke-WebRequest ${download} -OutFile proofos-agent.py; py -m pip install --user httpx psutil; py proofos-agent.py ${args}`,
  };
  const [copied, setCopied] = useState(false);
  return (
    <div className="agent-install">
      <div className="segmented" role="group" aria-label="Operating system">{[["windows", "Windows (PowerShell)"], ["linux", "Linux"], ["macos", "macOS"]].map(([k, l]) => <button key={k} type="button" aria-pressed={os === k} onClick={() => { setOs(k); setCopied(false); }}>{l}</button>)}</div>
      <pre aria-label="Install command">{commands[os]}</pre>
      <div className="ops-head-actions"><button className="ops-button primary" type="button" onClick={() => { navigator.clipboard?.writeText(commands[os]); setCopied(true); }}>{copied ? "Copied" : "Copy command"}</button><span className="ops-muted">Requires Python 3.10+. The secret is shown once; rotate it from the device's Operations tab.</span></div>
    </div>
  );
}

export function NetworkDiscovery({ api, devices, canWrite, onRegister }) {
  const [data, setData] = useState(null);
  const [scanner, setScanner] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  async function load() { try { setData(await api("/v1/fleet/discovered")); } catch (e) { setError(e.message); } }
  useEffect(() => { load(); }, []);
  const agents = devices.filter((d) => d.agent_version);
  return (
    <section className="card ops-report-card" aria-label="Network discovery">
      <div className="ops-toolbar"><div><h2>Network discovery</h2><p>An agent reports the devices it can see on its local network. Anything without a matching managed endpoint is listed as unmanaged.</p></div>
        <span className="ops-head-actions">{canWrite && <><select aria-label="Agent to scan from" value={scanner} onChange={(e) => setScanner(e.target.value)}><option value="">Scan from…</option>{(agents.length ? agents : devices).map((d) => <option key={d.id} value={d.id}>{d.hostname}</option>)}</select>
          <button className="ops-button primary" disabled={!scanner} onClick={async () => { setError(""); try { const r = await api("/v1/fleet/discover", { method: "POST", body: JSON.stringify({ device_id: Number(scanner) }) }); setNotice(`Discovery queued as run #${r.run_id}. Results appear when the agent reports back.`); } catch (e) { setError(e.message); } }}>Scan network</button></>}
          <button className="ops-button" onClick={load}>Refresh</button></span></div>
      {error && <p role="alert">{error}</p>}{notice && <p className="ops-note" role="status">{notice}</p>}
      {data && data.devices.length ? <>
        <p className="ops-muted">{data.unmanaged} unmanaged of {data.devices.length} devices seen by {data.scans} agent{data.scans === 1 ? "" : "s"}.</p>
        <DataTable columns={["Address", "MAC", "Seen by", "Status", ""]}>{data.devices.map((r) => <tr key={r.ip}><td><strong>{r.ip}</strong></td><td><code>{r.mac}</code></td><td>{r.seen_by.join(", ")}</td><td>{r.managed_device_id ? <Status tone="good">Managed · {r.managed_hostname}</Status> : <Status tone="warn">Unmanaged</Status>}</td><td>{!r.managed_device_id && canWrite && <button className="ops-link" onClick={() => onRegister(r)}>Register →</button>}</td></tr>)}</DataTable>
      </> : <p className="ops-muted">No discovery results yet. Choose an endpoint with an agent and scan its network.</p>}
    </section>
  );
}
