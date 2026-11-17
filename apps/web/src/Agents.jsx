import React, { useEffect, useMemo, useState } from "react";
import { DataTable, Empty, Metrics, PageHead, Status } from "./Operations";

const LIVE = new Set(["pending", "running", "cancelling"]);
const SHELLS = [["", "Default shell"], ["powershell", "PowerShell"], ["pwsh", "PowerShell 7"], ["bash", "bash"], ["python", "Python"]];
const HEALTH = { healthy: ["good", "healthy"], offline: ["bad", "offline"], restricted: ["warn", "restricted"], not_installed: ["neutral", "no agent"] };
const FILTERS = [["all", "All"], ["healthy", "Healthy"], ["offline", "Offline"], ["outdated", "Outdated"], ["restricted", "Restricted"], ["not_installed", "No agent"]];

function ago(value) {
  if (!value) return "never";
  const s = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
  return s < 60 ? `${Math.round(s)}s ago` : s < 3600 ? `${Math.round(s / 60)}m ago` : s < 86400 ? `${Math.round(s / 3600)}h ago` : `${Math.round(s / 86400)}d ago`;
}

function NodeRuns({ api, runs, setRuns, canWrite }) {
  const active = runs.filter((r) => LIVE.has(r.status)).map((r) => r.run_id).join(",");
  useEffect(() => {
    if (!active) return undefined;
    const timer = setInterval(async () => {
      const fresh = (await Promise.all(active.split(",").map((id) => api(`/v1/scripts/runs/${id}`).catch(() => null)))).filter(Boolean);
      setRuns((prev) => prev.map((r) => { const f = fresh.find((x) => x.id === r.run_id); return f ? { ...r, ...f, id: r.id } : r; }));
    }, 800);
    return () => clearInterval(timer);
  }, [active]);
  const cancel = async (r) => {
    try { const j = await api(`/v1/scripts/runs/${r.run_id}/cancel`, { method: "POST" }); setRuns((prev) => prev.map((x) => x.run_id === r.run_id ? { ...x, status: j.status } : x)); } catch { /* already finished */ }
  };
  const done = runs.filter((r) => r.status === "completed");
  return (
    <section className="card ops-section" aria-label="Multi-node results">
      <div className="ops-toolbar"><div><h2>Results by node</h2><p className="ops-muted">{done.length} of {runs.length} finished · {done.filter((r) => r.exit_code === 0).length} succeeded · {runs.filter((r) => r.error).length} not queued</p></div>
        <div className="ops-head-actions">{canWrite && runs.some((r) => ["pending", "running"].includes(r.status)) && <button className="ops-button" onClick={() => runs.filter((r) => ["pending", "running"].includes(r.status)).forEach(cancel)}>Cancel all</button>}<button className="ops-button" onClick={() => setRuns([])}>Clear</button></div></div>
      <div className="node-runs">
        {runs.map((r) => (
          <article key={r.device_id} className="command-run" aria-label={`Result ${r.hostname}`}>
            <header><code>{r.hostname}</code><span className="command-meta">
              {r.error ? <Status tone="bad">not queued</Status> : <Status tone={r.status === "completed" ? (r.exit_code === 0 ? "good" : "bad") : r.status === "cancelled" ? "warn" : "neutral"}>{r.status === "pending" ? "waiting for agent" : r.status === "completed" ? `exit ${r.exit_code}` : r.status}</Status>}
              {canWrite && ["pending", "running"].includes(r.status) && <button className="ops-link" onClick={() => cancel(r)}>Cancel</button>}</span></header>
            <pre aria-live="polite">{r.error || r.output || (r.status === "pending" ? "Queued." : "")}</pre>
          </article>
        ))}
      </div>
    </section>
  );
}

export function AgentsPage({ api, canWrite, onOpenDevice, onInstall }) {
  const [data, setData] = useState({ agents: [], summary: {}, latest_version: "" });
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(new Set());
  const [body, setBody] = useState("");
  const [shell, setShell] = useState("");
  const [runs, setRuns] = useState([]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function load() { try { setData(await api("/v1/agent/fleet")); } catch (e) { setError(e.message); } }
  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t); }, []);

  const shown = useMemo(() => data.agents.filter((a) => (filter === "all" || (filter === "outdated" ? a.outdated : a.health === filter))
    && `${a.hostname} ${a.os}`.toLowerCase().includes(query.toLowerCase())), [data, filter, query]);
  const chosen = data.agents.filter((a) => selected.has(a.id));
  const ids = [...selected];
  const toggle = (id) => setSelected((prev) => { const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next; });
  const allShown = shown.length > 0 && shown.every((a) => selected.has(a.id));

  async function act(fn, message) {
    setError(""); setNotice("");
    try { const r = await fn(); setNotice(typeof message === "function" ? message(r) : message); await load(); } catch (e) { setError(e.message); }
  }
  async function runEverywhere(e) {
    e.preventDefault();
    if (!body.trim() || !ids.length) return;
    await act(async () => {
      const text = shell ? `#proofos:shell=${shell}\n${body}` : body;
      const r = await api("/v1/agent/fleet/exec", { method: "POST", body: JSON.stringify({ device_ids: ids, body: text }) });
      setRuns(r.results.map((x) => ({ ...x, status: x.ok ? "pending" : "error", output: "" })));
      return r;
    }, (r) => `Queued on ${r.results.filter((x) => x.ok).length} of ${r.results.length} endpoints.`);
  }

  const s = data.summary;
  return (
    <div className="ops-page">
      <PageHead eyebrow="Endpoint agents" title="Every agent, one place." description="Health, version, push connection and execution controls for the ProofOS agent on each node. Commands are signed per node and every action is proof-logged.">
        <input aria-label="Search agents" placeholder="Search hostname or OS…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <button className="ops-button" onClick={load}>Refresh</button>
      </PageHead>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status" className="ops-muted">{notice}</p>}
      <Metrics items={[
        ["Agents installed", s.installed ?? 0, `${s.not_installed ?? 0} endpoints without an agent`],
        ["Push connected", s.connected ?? 0, "Receive commands instantly"],
        ["Offline", s.offline ?? 0, "No check-in for 5 minutes"],
        ["Outdated", s.outdated ?? 0, data.latest_version ? `Latest signed build ${data.latest_version}` : "No build published"],
        ["Restricted", s.restricted ?? 0, "Locked locally or disabled by policy"],
      ]} />
      <div className="ops-toolbar">
        <div className="segmented" role="group" aria-label="Agent filter">{FILTERS.map(([k, l]) => <button key={k} aria-pressed={filter === k} onClick={() => setFilter(k)}>{l}</button>)}</div>
        <span className="ops-muted">{selected.size ? `${selected.size} selected` : "Select agents to act on them together"}</span>
      </div>

      {canWrite && selected.size > 0 && (
        <section className="card ops-section agent-bulk" aria-label="Bulk agent actions">
          <form className="command-input" onSubmit={runEverywhere}>
            <label className="sr-only" htmlFor="fleet-shell">Interpreter</label>
            <select id="fleet-shell" value={shell} onChange={(e) => setShell(e.target.value)}>{SHELLS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
            <textarea aria-label="Command for selected agents" rows={body.includes("\n") ? 4 : 1} value={body} placeholder="Command to run on every selected node" onChange={(e) => setBody(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) runEverywhere(e); }} />
            <button className="ops-button primary" type="submit" disabled={!body.trim()}>Run on {selected.size}</button>
          </form>
          <div className="ops-head-actions">
            <button className="ops-button" onClick={() => act(() => api("/v1/agent/fleet/update", { method: "POST", body: JSON.stringify({ device_ids: ids }) }), (r) => `Update check sent to ${r.notified.length} connected agent(s)${r.not_connected.length ? `; ${r.not_connected.length} not connected will update on their next check` : ""}.`)}>Update now</button>
            <button className="ops-button" onClick={() => act(() => api("/v1/agent/fleet/policy", { method: "POST", body: JSON.stringify({ device_ids: ids, exec_enabled: true }) }), (r) => `Remote execution allowed on ${r.updated} endpoint(s).`)}>Allow remote execution</button>
            <button className="btn-danger rounded-lg px-3 py-2 text-xs" onClick={() => { if (window.confirm(`Block remote execution on ${selected.size} endpoint(s)? Queued commands for them will be cancelled.`)) act(() => api("/v1/agent/fleet/policy", { method: "POST", body: JSON.stringify({ device_ids: ids, exec_enabled: false }) }), (r) => `Remote execution blocked on ${r.updated} endpoint(s).`); }}>Block remote execution</button>
            <button className="ops-link" onClick={() => setSelected(new Set())}>Clear selection</button>
          </div>
          <p className="ops-muted">Selected: {chosen.map((a) => a.hostname).slice(0, 8).join(", ")}{chosen.length > 8 ? ` and ${chosen.length - 8} more` : ""}.</p>
        </section>
      )}

      {runs.length > 0 && <NodeRuns api={api} runs={runs} setRuns={setRuns} canWrite={canWrite} />}

      {shown.length ? (
        <DataTable columns={[<input key="all" type="checkbox" aria-label="Select all shown agents" checked={allShown} onChange={() => setSelected((prev) => { const next = new Set(prev); shown.forEach((a) => (allShown ? next.delete(a.id) : next.add(a.id))); return next; })} />, "Node", "Health", "Agent", "Connection", "Remote execution", "Activity", ""]}>
          {shown.map((a) => {
            const [tone, label] = HEALTH[a.health] || ["neutral", a.health];
            return (
              <tr key={a.id}>
                <td><input type="checkbox" aria-label={`Select ${a.hostname}`} checked={selected.has(a.id)} onChange={() => toggle(a.id)} /></td>
                <td><strong>{a.hostname}</strong><small>{a.os || a.device_type}</small></td>
                <td><Status tone={tone}>{label}</Status>{a.reboot_required && <small className="text-warn">reboot pending</small>}</td>
                <td>{a.agent_version ? <><span className="font-mono">{a.agent_version}</span>{a.outdated && <Status tone="warn">update available</Status>}</> : <button className="ops-link" onClick={() => onInstall(a.id)}>Install agent →</button>}</td>
                <td>{a.push_connected ? <Status tone="good">push live</Status> : a.agent_version ? <small>polling · seen {ago(a.last_seen)}</small> : "—"}</td>
                <td>{!a.exec_enabled ? <Status tone="bad">blocked by policy</Status> : a.locked ? <Status tone="warn">locked on endpoint</Status> : a.agent_version ? <Status tone="good">allowed</Status> : "—"}</td>
                <td><small>{a.active_runs ? `${a.active_runs} running or queued` : "idle"}{a.spooled ? ` · ${a.spooled} results waiting to send` : ""}</small></td>
                <td><button className="ops-link" onClick={() => onOpenDevice(a.id)}>Console →</button></td>
              </tr>
            );
          })}
        </DataTable>
      ) : <Empty title={data.agents.length ? "No agents match" : "No endpoints yet"}>{data.agents.length ? "Try another filter or search." : "Register an endpoint under Devices, then install the agent with the command shown there."}</Empty>}
    </div>
  );
}
