import React, { useEffect, useState } from "react";
import { DataTable, Empty, Metrics, PageHead, Status } from "./Operations";
import { PortalLinks } from "./Assurance";

const money = (v) => (v == null ? "—" : new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(v));
const contractLabel = (c) => !c ? "No contract" : c.kind === "hourly" ? `Hourly · ${money(c.hourly_rate)}/h` : c.kind === "retainer" ? `Retainer · ${money(c.monthly_fee)}/mo, ${c.included_hours} h included` : `Fixed · ${money(c.monthly_fee)}/mo`;
const thisMonth = () => new Date().toISOString().slice(0, 7);

function ContractForm({ contract, onSave }) {
  const [c, setC] = useState(contract || { kind: "hourly", hourly_rate: 120, monthly_fee: 0, included_hours: 0, per_device_fee: 0 });
  return (
    <form className="inline-fields" onSubmit={(e) => { e.preventDefault(); onSave({ kind: c.kind, hourly_rate: Number(c.hourly_rate), monthly_fee: Number(c.monthly_fee), included_hours: Number(c.included_hours), per_device_fee: Number(c.per_device_fee) }); }}>
      <label>Billing model<select value={c.kind} onChange={(e) => setC({ ...c, kind: e.target.value })}><option value="hourly">Hourly</option><option value="retainer">Monthly retainer</option><option value="fixed">Fixed monthly fee</option></select></label>
      {c.kind !== "fixed" && <label>Hourly rate<input type="number" min={0} step="0.01" value={c.hourly_rate} onChange={(e) => setC({ ...c, hourly_rate: e.target.value })} /></label>}
      {c.kind !== "hourly" && <label>Monthly fee<input type="number" min={0} step="0.01" value={c.monthly_fee} onChange={(e) => setC({ ...c, monthly_fee: e.target.value })} /></label>}
      {c.kind === "retainer" && <label>Included hours<input type="number" min={0} step="0.5" value={c.included_hours} onChange={(e) => setC({ ...c, included_hours: e.target.value })} /></label>}
      <label>Per endpoint / month<input type="number" min={0} step="0.01" value={c.per_device_fee} onChange={(e) => setC({ ...c, per_device_fee: e.target.value })} /></label>
      <button className="ops-button primary" type="submit">Save contract</button>
    </form>
  );
}

function CustomerDetail({ api, id, devices, canWrite, onOpenDevice, onChanged, onClose }) {
  const [c, setC] = useState(null);
  const [contact, setContact] = useState({ name: "", email: "", phone: "", role: "" });
  const [assign, setAssign] = useState("");
  const [error, setError] = useState("");
  async function load() { try { setC(await api(`/v1/customers/${id}`)); } catch (e) { setError(e.message); } }
  useEffect(() => { load(); }, [id]);
  async function act(fn) { setError(""); try { await fn(); await load(); onChanged(); } catch (e) { setError(e.message); } }
  if (!c) return error ? <p role="alert">{error}</p> : null;
  const unassigned = devices.filter((d) => !d.customer_id);
  return (
    <section className="card customer-detail" aria-label={`Customer ${c.name}`}>
      <div className="ops-toolbar"><div><p className="ops-eyebrow">Customer</p><h2 className="customer-name">{c.name}</h2><p className="ops-muted">{[c.domain, c.phone].filter(Boolean).join(" · ") || "No domain or phone recorded"}</p></div><button className="ops-button" onClick={onClose}>Close</button></div>
      {error && <p role="alert">{error}</p>}
      <div className="customer-grid">
        <div><h3 className="ops-section-title">Contract</h3><p className="ops-muted">{contractLabel(c.contract)}{c.contract?.per_device_fee ? ` · ${money(c.contract.per_device_fee)} per endpoint` : ""}</p>{canWrite && <ContractForm contract={c.contract} onSave={(body) => act(() => api(`/v1/customers/${c.id}/contract`, { method: "PUT", body: JSON.stringify(body) }))} />}</div>
        <div><h3 className="ops-section-title">Contacts</h3>{c.contacts.length ? <ul className="contact-list">{c.contacts.map((x) => <li key={x.id}><strong>{x.name}</strong><small>{[x.role, x.email, x.phone].filter(Boolean).join(" · ")}</small>{canWrite && <button className="ops-link" onClick={() => act(() => api(`/v1/customers/${c.id}/contacts/${x.id}`, { method: "DELETE" }))}>Remove</button>}</li>)}</ul> : <p className="ops-muted">No contacts yet.</p>}
          {canWrite && <form className="inline-fields" onSubmit={(e) => { e.preventDefault(); act(async () => { await api(`/v1/customers/${c.id}/contacts`, { method: "POST", body: JSON.stringify({ ...contact, email: contact.email || null }) }); setContact({ name: "", email: "", phone: "", role: "" }); }); }}>
            <label>Name<input required minLength={2} value={contact.name} onChange={(e) => setContact({ ...contact, name: e.target.value })} /></label>
            <label>Email<input type="email" value={contact.email} onChange={(e) => setContact({ ...contact, email: e.target.value })} /></label>
            <label>Role<input value={contact.role} onChange={(e) => setContact({ ...contact, role: e.target.value })} /></label>
            <button className="ops-button" type="submit">Add contact</button></form>}
        </div>
      </div>
      <h3 className="ops-section-title">Endpoints ({c.devices.length})</h3>
      {c.devices.length ? <div className="chip-row">{c.devices.map((d) => <button key={d.id} className="device-chip" onClick={() => onOpenDevice(d.id)}><i className={d.status} />{d.hostname}</button>)}</div> : <p className="ops-muted">No endpoints assigned.</p>}
      {canWrite && unassigned.length > 0 && <form className="inline-fields" onSubmit={(e) => { e.preventDefault(); if (assign) act(async () => { await api(`/v1/customers/${c.id}/devices`, { method: "POST", body: JSON.stringify({ device_ids: [Number(assign)] }) }); setAssign(""); }); }}><label>Assign an endpoint<select value={assign} onChange={(e) => setAssign(e.target.value)}><option value="">Choose…</option>{unassigned.map((d) => <option key={d.id} value={d.id}>{d.hostname}</option>)}</select></label><button className="ops-button" type="submit" disabled={!assign}>Assign</button></form>}
      <PortalLinks api={api} customerId={c.id} contacts={c.contacts} canWrite={canWrite} />
      <h3 className="ops-section-title">Recent tickets</h3>
      {c.tickets.length ? <ul className="contact-list">{c.tickets.slice(0, 8).map((t) => <li key={t.id}><strong>#{t.id} · {t.title}</strong><small>{t.priority} priority</small><Status tone={["closed", "resolved"].includes(t.status) ? "good" : "warn"}>{t.status.replace("_", " ")}</Status></li>)}</ul> : <p className="ops-muted">No tickets for this customer.</p>}
    </section>
  );
}

export function CustomersPage({ api, devices, canWrite, onOpenDevice, onChanged }) {
  const [rows, setRows] = useState([]);
  const [form, setForm] = useState({ name: "", domain: "", phone: "" });
  const [open, setOpen] = useState(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  async function load() { try { setRows(await api("/v1/customers")); } catch (e) { setError(e.message); } }
  useEffect(() => { load(); }, []);
  const shown = rows.filter((r) => `${r.name} ${r.domain}`.toLowerCase().includes(query.toLowerCase()));
  return (
    <div className="ops-page">
      <PageHead eyebrow="Service delivery" title="Every client, in one place." description="Customers group endpoints, tickets, contacts and the contract they are billed on.">
        <input aria-label="Search customers" placeholder="Search customers…" value={query} onChange={(e) => setQuery(e.target.value)} />
      </PageHead>
      {error && <p role="alert">{error}</p>}
      <Metrics items={[
        ["Customers", rows.length, `${rows.filter((r) => r.contract).length} with an active contract`],
        ["Managed endpoints", rows.reduce((n, r) => n + r.devices, 0), `${devices.filter((d) => !d.customer_id).length} not assigned to a customer`],
        ["Open tickets", rows.reduce((n, r) => n + r.open_tickets, 0), "Across all customers"],
        ["Endpoints offline", rows.reduce((n, r) => n + r.devices_offline, 0), "Offline or stale"],
      ]} />
      {open && <CustomerDetail api={api} id={open} devices={devices} canWrite={canWrite} onOpenDevice={onOpenDevice} onChanged={() => { load(); onChanged(); }} onClose={() => setOpen(null)} />}
      {shown.length ? <DataTable columns={["Customer", "Endpoints", "Open tickets", "Contract", ""]}>
        {shown.map((r) => <tr key={r.id}><td><strong>{r.name}</strong><small>{r.domain || "—"}</small></td><td>{r.devices}{r.devices_offline ? <small className="text-warn">{r.devices_offline} offline</small> : null}</td><td>{r.open_tickets}</td><td>{contractLabel(r.contract)}</td><td><button className="ops-link" onClick={() => setOpen(r.id)}>Open →</button></td></tr>)}
      </DataTable> : <Empty title={rows.length ? "No matching customers" : "Add your first customer"}>{rows.length ? "Try another search." : "Customers let you group endpoints and tickets by client and bill them from their contract."}</Empty>}
      {canWrite && <form className="card ops-connect-form" onSubmit={async (e) => { e.preventDefault(); setError(""); try { const c = await api("/v1/customers", { method: "POST", body: JSON.stringify(form) }); setForm({ name: "", domain: "", phone: "" }); await load(); onChanged(); setOpen(c.id); } catch (err) { setError(err.message); } }}>
        <div><h2>Add a customer</h2><p>You can add contacts, a contract and endpoints next.</p></div>
        <label>Company name<input required minLength={2} maxLength={255} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label>Domain<input value={form.domain} onChange={(e) => setForm({ ...form, domain: e.target.value })} placeholder="example.com" /></label>
        <label>Phone<input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></label>
        <button className="ops-button primary" type="submit">Add customer</button>
      </form>}
    </div>
  );
}

export function BillingPage({ api, apiBase, canWrite }) {
  const [period, setPeriod] = useState(thisMonth());
  const [data, setData] = useState(null);
  const [invoices, setInvoices] = useState([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function load() {
    setError("");
    try { const [p, i] = await Promise.all([api(`/v1/billing/preview?period=${period}`), api("/v1/billing/invoices")]); setData(p); setInvoices(i); }
    catch (e) { setError(e.message); }
  }
  useEffect(() => { load(); }, [period]);
  async function download(id, name) {
    try {
      const r = await fetch(`${apiBase}/v1/billing/invoices/${id}/csv`, { headers: { Authorization: `Bearer ${localStorage.getItem("proofos_token") || ""}` } });
      if (!r.ok) throw new Error(`Download failed (${r.status})`);
      const url = URL.createObjectURL(await r.blob());
      const a = document.createElement("a"); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError(e.message); }
  }
  return (
    <div className="ops-page">
      <PageHead eyebrow="Billing" title="Bill from the work you can prove." description="Charges come from each customer's contract and billable ticket time. Issued invoices are frozen and signed, so any later change is detected.">
        <input type="month" aria-label="Billing period" value={period} onChange={(e) => e.target.value && setPeriod(e.target.value)} />
      </PageHead>
      {error && <p role="alert">{error}</p>}{notice && <p className="ops-note" role="status">{notice}</p>}
      {data && <>
        <Metrics items={[
          ["Billable this period", money(data.total), `${data.customers.length} customers`],
          ["Invoiced", money(data.customers.filter((c) => c.invoice_id).reduce((n, c) => n + c.total, 0)), `${data.customers.filter((c) => c.invoice_id).length} invoices issued`],
          ["Ready to invoice", data.customers.filter((c) => !c.invoice_id && c.total > 0).length, "Customers with charges"],
          ["Unassigned time", `${data.unassigned_billable_hours} h`, data.unassigned_billable_hours ? "Billable time on tickets with no customer" : "All billable time is assigned"],
        ]} />
        {data.customers.length ? <div className="billing-list">{data.customers.map((c) => <section key={c.customer_id} className="card billing-card">
          <div className="ops-toolbar"><div><h2 className="customer-name">{c.customer}</h2><p className="ops-muted">{c.contract ? `${c.contract} contract` : "No contract"} · {c.billable_hours} billable h · {c.devices} endpoints</p></div><strong className="billing-total">{money(c.total)}</strong></div>
          {c.lines.length ? <table className="ops-table billing-lines"><tbody>{c.lines.map((l, i) => <tr key={i}><td>{l.description}</td><td>{l.quantity}</td><td>{money(l.unit_price)}</td><td><strong>{money(l.amount)}</strong></td></tr>)}</tbody></table> : <p className="ops-muted">Nothing billable this period.</p>}
          {c.note && <p className="text-warn text-xs">{c.note}</p>}
          <div className="ops-head-actions">{c.invoice_id ? <Status tone="good">Invoice #{c.invoice_id} issued</Status> : canWrite && <button className="ops-button primary" disabled={!c.total} onClick={async () => { if (!window.confirm(`Issue an invoice for ${c.customer} (${money(c.total)}) for ${period}? Issued invoices cannot be edited.`)) return; setError(""); try { const inv = await api("/v1/billing/invoices", { method: "POST", body: JSON.stringify({ customer_id: c.customer_id, period }) }); setNotice(`Invoice #${inv.id} issued for ${c.customer} and signed.`); load(); } catch (e) { setError(e.message); } }}>Issue invoice</button>}</div>
        </section>)}</div> : <Empty title="No customers to bill">Add customers and contracts in Customers, then log billable time on their tickets.</Empty>}
      </>}
      <h2 className="ops-section-title">Issued invoices</h2>
      {invoices.length ? <DataTable columns={["Invoice", "Customer", "Period", "Total", "Integrity", ""]}>
        {invoices.map((i) => <tr key={i.id}><td><strong>#{i.id}</strong><small>{new Date(i.created_at).toLocaleDateString()}</small></td><td>{i.customer}</td><td>{i.period}</td><td><strong>{money(i.total)}</strong></td><td><Status tone={i.verified ? "good" : "bad"}>{i.verified ? "Matches signed record" : "Altered after issue"}</Status></td><td><button className="ops-link" onClick={() => download(i.id, `proofos-invoice-${i.id}-${i.period}.csv`)}>Download CSV</button></td></tr>)}
      </DataTable> : <p className="ops-muted">No invoices issued yet.</p>}
    </div>
  );
}

export function TicketAssist({ api, ticketId, onUseReply }) {
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { setResult(null); setError(""); }, [ticketId]);
  return (
    <section className="ticket-assist" aria-label="AI ticket assistant">
      <div className="ops-toolbar"><div><h3 className="ops-section-title">AI assistant</h3><p className="ops-muted">Summarises the ticket with its device, alerts, patches and knowledge base. Nothing is sent or changed.</p></div>
        <button className="ops-button primary" disabled={busy} onClick={async () => { setBusy(true); setError(""); try { setResult(await api(`/v1/ai/tickets/${ticketId}/assist`, { method: "POST" })); } catch (e) { setError(e.message); } finally { setBusy(false); } }}>{busy ? "Analysing…" : result ? "Refresh" : "Summarise and suggest"}</button></div>
      {error && <p role="alert">{error}</p>}
      {result && <div className="assist-body">
        <p><strong>Summary.</strong> {result.summary}</p>
        <ol>{result.next_steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
        <div className="assist-reply"><p className="stat-label">Suggested reply</p><pre>{result.reply}</pre><button className="ops-button" onClick={() => onUseReply(result.reply)}>Use as comment</button></div>
        <p className="ops-muted">Generated by {result.engine} · recorded as proof {result.proof_id.slice(0, 10)}…</p>
      </div>}
    </section>
  );
}
