import React, { useEffect, useState } from "react";
import { DataTable, Empty, Metrics, PageHead, Status } from "./Operations";

const date = (value) => (value ? new Date(value).toLocaleString() : "—");
const sevTone = (s) => ({ critical: "bad", high: "bad", medium: "warn", low: "neutral" }[s] || "neutral");
const CHECK_LABELS = {
  imprint_matches: "Token covers this chain head",
  signature_valid: "Authority signature valid",
  tsa_certificate_valid: "Authority certificate valid at signing time",
  root_trusted: "Authority root is pinned as trusted",
  head_still_in_ledger: "Anchored record unchanged in the ledger",
};

/* ------------------------------------------------------------------ */
/* Vulnerabilities                                                     */
/* ------------------------------------------------------------------ */

export function VulnerabilitiesPage({ api, canWrite, onOpenDevice }) {
  const [data, setData] = useState({ counts: {}, findings: [] });
  const [status, setStatus] = useState("open");
  const [severity, setSeverity] = useState("");
  const [scan, setScan] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try { setData(await api(`/v1/vulnerabilities?status=${status}${severity ? `&severity=${severity}` : ""}`)); } catch (e) { setError(e.message); }
  }
  useEffect(() => { load(); }, [status, severity]);

  async function runScan() {
    setBusy(true); setError("");
    try { setScan(await api("/v1/vulnerabilities/scan", { method: "POST" })); await load(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  const c = data.counts || {};
  const hosts = new Set(data.findings.map((f) => f.device_id)).size;
  return (
    <div className="ops-page">
      <PageHead eyebrow="Exposure" title="Know which endpoints are exploitable." description="Installed packages are matched against the OSV database of distribution security advisories. Covered today: Ubuntu, Debian, Alpine, Rocky Linux and AlmaLinux.">
        {canWrite && <button className="ops-button primary" onClick={runScan} disabled={busy}>{busy ? "Matching packages…" : "Scan now"}</button>}
      </PageHead>
      {error && <p role="alert">{error}</p>}
      {scan && <p role="status" className="ops-muted">Scanned {scan.devices_covered} endpoint{scan.devices_covered === 1 ? "" : "s"}; {scan.new_findings} new finding{scan.new_findings === 1 ? "" : "s"}.{scan.devices_not_covered.length ? ` Not covered (unsupported OS or no package inventory yet): ${scan.devices_not_covered.slice(0, 6).join(", ")}${scan.devices_not_covered.length > 6 ? "…" : ""}.` : ""}</p>}
      <Metrics items={[
        ["Critical", c.critical || 0, "Open advisories"],
        ["High", c.high || 0, "Open advisories"],
        ["Medium / low", (c.medium || 0) + (c.low || 0), `${c.unknown || 0} not yet rated`],
        ["Endpoints affected", hosts, status === "open" ? "With at least one open finding" : "In this view"],
      ]} />
      <div className="ops-toolbar">
        <div className="segmented" role="group" aria-label="Finding status">{[["open", "Open"], ["resolved", "Resolved"], ["all", "All"]].map(([k, l]) => <button key={k} aria-pressed={status === k} onClick={() => setStatus(k)}>{l}</button>)}</div>
        <label className="sr-only" htmlFor="vuln-sev">Severity</label>
        <select id="vuln-sev" value={severity} onChange={(e) => setSeverity(e.target.value)}><option value="">All severities</option>{["critical", "high", "medium", "low", "unknown"].map((s) => <option key={s} value={s}>{s}</option>)}</select>
      </div>
      {data.findings.length ? (
        <DataTable columns={["Severity", "Advisory", "Package", "Endpoint", "Remediation"]}>
          {data.findings.map((f) => (
            <tr key={f.id}>
              <td><Status tone={sevTone(f.severity)}>{f.severity}</Status></td>
              <td><strong><a className="ops-link" href={`https://osv.dev/vulnerability/${encodeURIComponent(f.vuln_id)}`} target="_blank" rel="noreferrer noopener">{f.vuln_id}</a></strong><small>{[f.aliases.slice(0, 2).join(", "), f.summary.slice(0, 140)].filter(Boolean).join(" · ")}</small></td>
              <td><strong>{f.package}</strong><small className="font-mono">{f.version}</small></td>
              <td><button className="ops-link" onClick={() => onOpenDevice(f.device_id)}>{f.hostname}</button></td>
              <td>{f.status === "resolved" ? <Status tone="good">resolved {date(f.last_seen)}</Status> : <>{f.fixed_version ? <small>Fixed in <span className="font-mono">{f.fixed_version}</span></small> : <small>No fix published yet</small>}{f.patch_pending && <Status tone="warn">patch pending</Status>}</>}</td>
            </tr>
          ))}
        </DataTable>
      ) : <Empty title={status === "open" ? "No open findings" : "Nothing to show"}>{status === "open" ? "Either nothing installed matches a known advisory, or no supported endpoint has reported its packages yet. Agents report packages with their inventory; scans run daily." : "Change the filter to see other findings."}</Empty>}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Service level objectives                                            */
/* ------------------------------------------------------------------ */

export function SloPanel({ api, canWrite }) {
  const [rows, setRows] = useState([]);
  const [form, setForm] = useState({ service: "", max_error_rate: "1", max_p95_ms: "", window_minutes: "15", min_requests: "20" });
  const [error, setError] = useState("");
  async function load() { try { setRows(await api("/v1/slos")); } catch (e) { setError(e.message); } }
  useEffect(() => { load(); }, []);
  const tone = (s) => ({ ok: "good", breaching: "bad" }[s] || "neutral");
  return (
    <section className="card ops-section" aria-label="Service level objectives">
      <div className="ops-toolbar"><div><h2>Service level objectives</h2><p className="ops-muted">Error-budget burn is checked every minute over a short and a 4× longer window; both must burn before an alert opens, and it closes itself on recovery.</p></div>
        <button className="ops-button" onClick={async () => { setError(""); try { setRows(await api("/v1/slos/check", { method: "POST" })); } catch (e) { setError(e.message); } }}>Evaluate now</button></div>
      {error && <p role="alert">{error}</p>}
      {rows.length ? <DataTable columns={["Service", "Objective", "Last window", "Status", ""]}>
        {rows.map((r) => <tr key={r.id}>
          <td><strong>{r.service}</strong></td>
          <td><small>≤ {(r.max_error_rate * 100).toFixed(2)}% errors{r.max_p95_ms ? ` · p95 ≤ ${r.max_p95_ms} ms` : ""} · {r.window_minutes} min</small></td>
          <td><small>{r.short.requests} requests · {r.short.error_rate == null ? "no spans" : `${(r.short.error_rate * 100).toFixed(2)}% errors`}{r.short.burn_rate != null ? ` · burn ${r.short.burn_rate}×` : ""}{r.short.p95_ms != null ? ` · p95 ${r.short.p95_ms} ms` : ""}</small></td>
          <td><Status tone={tone(r.status)}>{r.status.replace("_", " ")}</Status>{r.reasons.length > 0 && <small>{r.reasons.join("; ")}</small>}</td>
          <td>{canWrite && <button className="ops-link" onClick={async () => { if (window.confirm(`Delete the SLO for ${r.service}?`)) { await api(`/v1/slos/${r.id}`, { method: "DELETE" }); load(); } }}>Delete</button>}</td>
        </tr>)}
      </DataTable> : <p className="ops-muted">No objectives yet. Define one for any service that sends traces.</p>}
      {canWrite && <form className="inline-fields mt-3" onSubmit={async (e) => {
        e.preventDefault(); setError("");
        try {
          await api("/v1/slos", { method: "PUT", body: JSON.stringify({ service: form.service, max_error_rate: Number(form.max_error_rate) / 100, max_p95_ms: Number(form.max_p95_ms || 0), window_minutes: Number(form.window_minutes), min_requests: Number(form.min_requests) }) });
          setForm({ ...form, service: "" }); load();
        } catch (err) { setError(err.message); }
      }}>
        <label>Service<input required value={form.service} onChange={(e) => setForm({ ...form, service: e.target.value })} placeholder="checkout-api" /></label>
        <label>Max error %<input type="number" required min="0.01" max="100" step="0.01" value={form.max_error_rate} onChange={(e) => setForm({ ...form, max_error_rate: e.target.value })} /></label>
        <label>Max p95 ms<input type="number" min="0" value={form.max_p95_ms} onChange={(e) => setForm({ ...form, max_p95_ms: e.target.value })} placeholder="optional" /></label>
        <label>Window min<input type="number" min="5" max="360" value={form.window_minutes} onChange={(e) => setForm({ ...form, window_minutes: e.target.value })} /></label>
        <button className="ops-button primary" type="submit">Save objective</button>
      </form>}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Probable cause                                                      */
/* ------------------------------------------------------------------ */

export function ProbableCause({ api, nodeId, onSelect }) {
  const [result, setResult] = useState(null);
  useEffect(() => {
    let current = true;
    setResult(null);
    api(`/v1/topology/probable-cause/${nodeId}`).then((r) => { if (current) setResult(r); }).catch(() => {});
    return () => { current = false; };
  }, [nodeId]);
  if (!result) return null;
  return (
    <div className="mt-4" aria-label="Probable cause">
      <h3 className="ops-section-title">Probable cause</h3>
      {result.candidates.length ? <ol className="cause-list">{result.candidates.slice(0, 4).map((c) => (
        <li key={c.id}><button onClick={() => onSelect(c.id)}>{c.name}</button> <Status tone={c.health === "down" ? "bad" : "warn"}>{c.health}</Status>{c.origin && <Status tone="bad">likely origin</Status>}<small className="ops-muted block">{c.why}</small></li>
      ))}</ol> : <p className="ops-muted">Nothing on this path is failing.</p>}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Independent timestamps of the proof ledger                          */
/* ------------------------------------------------------------------ */

export function AnchorsPanel({ api, apiBase, canWrite, authToken }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function load() { try { setData(await api("/v1/anchors")); } catch (e) { setError(e.message); } }
  useEffect(() => { load(); }, []);
  async function download(id) {
    const r = await fetch(`${apiBase}/v1/anchors/${id}/token`, { headers: { Authorization: `Bearer ${authToken}` } });
    if (!r.ok) { setError(`Download failed (${r.status})`); return; }
    const url = URL.createObjectURL(await r.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: `proofos-anchor-${id}.tsr` });
    a.click();
    URL.revokeObjectURL(url);
  }
  const latest = data?.anchors?.[0];
  return (
    <section className="card ops-section" aria-label="Independent timestamps">
      <div className="ops-toolbar"><div><h2>Independent timestamps</h2><p className="ops-muted">The ledger head is timestamped by an outside RFC 3161 authority{data ? ` (${data.authorities.join(", ")})` : ""}. A rewrite of history after an anchor is detectable even by someone who holds ProofOS's signing key.</p></div>
        {canWrite && <button className="ops-button primary" disabled={busy} onClick={async () => { setBusy(true); setError(""); try { await api("/v1/anchors", { method: "POST" }); await load(); } catch (e) { setError(e.message); } finally { setBusy(false); } }}>{busy ? "Requesting…" : "Anchor now"}</button>}</div>
      {error && <p role="alert">{error}</p>}
      {latest?.verification && <ul className="check-list" aria-label="Latest anchor checks">{Object.entries(latest.verification.checks).map(([k, ok]) => <li key={k}><Status tone={ok ? "good" : "bad"}>{ok ? "pass" : "fail"}</Status> {CHECK_LABELS[k] || k}</li>)}</ul>}
      {data?.anchors?.length ? <DataTable columns={["Timestamped", "Records covered", "Chain head", "Verified", ""]}>
        {data.anchors.map((a) => <tr key={a.id}>
          <td>{date(a.gen_time)}<small>{a.tsa_url}</small></td>
          <td>{a.record_count}</td>
          <td className="font-mono text-xs">{a.chain_head.slice(0, 16)}…</td>
          <td>{a.verification ? <Status tone={a.verification.verified ? "good" : "bad"}>{a.verification.verified ? "verified" : "failed"}</Status> : <small>not rechecked</small>}</td>
          <td><button className="ops-link" onClick={() => download(a.id)}>Download .tsr</button></td>
        </tr>)}
      </DataTable> : data && <p className="ops-muted">No anchors yet. They are taken hourly while the ledger changes.</p>}
      <p className="ops-muted mt-2 text-xs">Check a token yourself: <code>openssl ts -reply -in proofos-anchor-N.tsr -text</code></p>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Customer portal links (staff side)                                  */
/* ------------------------------------------------------------------ */

export function PortalLinks({ api, customerId, contacts, canWrite }) {
  const [links, setLinks] = useState([]);
  const [email, setEmail] = useState("");
  const [days, setDays] = useState("30");
  const [created, setCreated] = useState(null);
  const [error, setError] = useState("");
  async function load() { try { setLinks(await api(`/v1/portal/links?customer_id=${customerId}`)); } catch (e) { setError(e.message); } }
  useEffect(() => { load(); setCreated(null); }, [customerId]);
  const url = created ? `${window.location.origin}${created.path}` : "";
  return (
    <div>
      <h3 className="ops-section-title">Customer portal</h3>
      <p className="ops-muted">A private link lets a contact see this customer's tickets and invoices, open tickets and reply. Internal notes stay hidden.</p>
      {error && <p role="alert">{error}</p>}
      {created && <div className="card portal-created" role="status"><p>Send this link to {created.contact_email}. It is shown once.</p><input readOnly aria-label="Portal link" value={url} onFocus={(e) => e.target.select()} /><button className="ops-button" onClick={() => navigator.clipboard?.writeText(url)}>Copy</button></div>}
      {links.length > 0 && <ul className="contact-list">{links.map((l) => <li key={l.id}><strong>{l.contact_email}</strong><small>{l.active ? `expires ${date(l.expires_at)}` : l.revoked ? "revoked" : "expired"}</small>{l.active && canWrite && <button className="ops-link" onClick={async () => { await api(`/v1/portal/links/${l.id}/revoke`, { method: "POST" }); load(); }}>Revoke</button>}</li>)}</ul>}
      <form className="inline-fields" onSubmit={async (e) => { e.preventDefault(); setError(""); try { setCreated(await api("/v1/portal/links", { method: "POST", body: JSON.stringify({ customer_id: customerId, contact_email: email, days: Number(days) }) })); setEmail(""); load(); } catch (err) { setError(err.message); } }}>
        <label>Contact email<input type="email" required list={`portal-contacts-${customerId}`} value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <datalist id={`portal-contacts-${customerId}`}>{contacts.filter((c) => c.email).map((c) => <option key={c.id} value={c.email}>{c.name}</option>)}</datalist>
        <label>Valid for<select value={days} onChange={(e) => setDays(e.target.value)}>{[["7", "7 days"], ["30", "30 days"], ["90", "90 days"], ["365", "1 year"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <button className="ops-button" type="submit">Create link</button>
      </form>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Customer portal (public page at /portal#<token>)                    */
/* ------------------------------------------------------------------ */

export function PortalApp({ apiBase }) {
  const [portalToken] = useState(() => window.location.hash.slice(1));
  const [me, setMe] = useState(null);
  const [open, setOpen] = useState(null);
  const [form, setForm] = useState({ title: "", body: "", priority: "normal" });
  const [reply, setReply] = useState("");
  const [error, setError] = useState("");

  async function call(path, opts = {}) {
    const r = await fetch(apiBase + path, { ...opts, headers: { "Content-Type": "application/json", "X-Portal-Token": portalToken } });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || `Request failed (${r.status})`);
    return data;
  }
  async function load() { try { setMe(await call("/v1/portal/me")); } catch (e) { setError(e.message); } }
  async function openTicket(id) { try { setOpen(await call(`/v1/portal/tickets/${id}`)); } catch (e) { setError(e.message); } }
  useEffect(() => {
    // Drop the token from the address bar so it is not left in history or shoulder-surfed.
    window.history.replaceState({}, document.title, window.location.pathname);
    if (portalToken) load(); else setError("This page needs the private link your service provider sent you.");
  }, []);

  if (!me) return <main className="portal-shell"><div className="card portal-card"><h1>Support portal</h1>{error ? <p role="alert">{error}</p> : <p className="ops-muted">Loading…</p>}</div></main>;
  const money = (n) => new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(n);
  return (
    <main className="portal-shell">
      <header className="portal-head"><div><p className="ops-eyebrow">Support portal</p><h1>{me.customer.name}</h1><p className="ops-muted">Signed in as {me.contact_email} · link valid until {date(me.expires_at)}</p></div></header>
      {error && <p role="alert">{error}</p>}
      <div className="portal-grid">
        <section className="card ops-section" aria-label="Your tickets">
          <h2>Tickets</h2>
          {me.tickets.length ? <ul className="contact-list">{me.tickets.map((t) => <li key={t.id}><button className="ops-link" onClick={() => openTicket(t.id)}><strong>#{t.id} · {t.title}</strong></button><small>{t.priority} · opened {date(t.created_at)}</small><Status tone={["closed", "resolved"].includes(t.status) ? "good" : "warn"}>{t.status.replace("_", " ")}</Status></li>)}</ul> : <p className="ops-muted">No tickets yet.</p>}
          <form className="ops-connect-form mt-3" onSubmit={async (e) => { e.preventDefault(); setError(""); try { const t = await call("/v1/portal/tickets", { method: "POST", body: JSON.stringify(form) }); setForm({ title: "", body: "", priority: "normal" }); await load(); openTicket(t.id); } catch (err) { setError(err.message); } }}>
            <h3>Open a ticket</h3>
            <label>Subject<input required minLength={3} maxLength={500} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
            <label>Details<textarea rows={4} maxLength={20000} value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} /></label>
            <label>Urgency<select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>{["low", "normal", "high", "urgent"].map((p) => <option key={p} value={p}>{p}</option>)}</select></label>
            <button className="ops-button primary" type="submit">Submit ticket</button>
          </form>
        </section>
        <section className="card ops-section" aria-label="Ticket conversation">
          {open ? <>
            <div className="ops-toolbar"><h2>#{open.id} · {open.title}</h2><Status tone={["closed", "resolved"].includes(open.status) ? "good" : "warn"}>{open.status.replace("_", " ")}</Status></div>
            {open.body && <p className="portal-body">{open.body}</p>}
            <ol className="portal-thread">{open.comments.map((c) => <li key={c.id}><strong>{c.author}</strong><small>{date(c.created_at)}</small><p>{c.body}</p></li>)}</ol>
            <form className="ops-connect-form" onSubmit={async (e) => { e.preventDefault(); setError(""); try { await call(`/v1/portal/tickets/${open.id}/comments`, { method: "POST", body: JSON.stringify({ body: reply }) }); setReply(""); openTicket(open.id); } catch (err) { setError(err.message); } }}>
              <label>Reply<textarea required rows={3} value={reply} onChange={(e) => setReply(e.target.value)} /></label>
              <button className="ops-button primary" type="submit">Send reply</button>
            </form>
          </> : <><h2>Conversation</h2><p className="ops-muted">Select a ticket to read updates and reply.</p></>}
        </section>
      </div>
      <section className="card ops-section" aria-label="Invoices">
        <h2>Invoices</h2>
        {me.invoices.length ? <DataTable columns={["Period", "Total", "Lines", "Signed record"]}>{me.invoices.map((i) => <tr key={i.id}><td>{i.period}</td><td>{money(i.total)}</td><td><small>{i.lines.map((l) => l.description).filter(Boolean).slice(0, 3).join(" · ")}</small></td><td className="font-mono text-xs">{i.proof_id ? `${i.proof_id.slice(0, 12)}…` : "—"}</td></tr>)}</DataTable> : <p className="ops-muted">No invoices issued yet.</p>}
      </section>
    </main>
  );
}
