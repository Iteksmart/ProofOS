import React, { useCallback, useEffect, useState } from "react";
import { HealthPill, ProofBadge } from "@proofos/ui";

// Production nginx proxies /v1 to the API, so an empty build value keeps all
// browser traffic on the current origin. Local Vite dev keeps localhost:8000.
const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

function token() {
  return localStorage.getItem("proofos_token") || "";
}

// FastAPI validation errors return `detail` as a list of {msg, loc, ...}
// objects rather than a string; rendering that directly as a React child
// crashes the app, so always reduce it to displayable text first.
function errorText(detail, fallback) {
  if (!detail) return fallback;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => (typeof d === "string" ? d : d?.msg || JSON.stringify(d))).join("; ") || fallback;
  }
  return typeof detail === "object" ? detail.msg || JSON.stringify(detail) : String(detail);
}

function tokenClaims(value) {
  try {
    const encoded = value.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = encoded + "=".repeat((4 - (encoded.length % 4)) % 4);
    return JSON.parse(atob(padded));
  } catch {
    return {};
  }
}

async function api(path, opts = {}) {
  const r = await fetch(API + path, {
    ...opts,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token()}`, ...(opts.headers || {}) },
  });
  const text = await r.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  if (r.status === 401) {
    localStorage.removeItem("proofos_token");
    localStorage.removeItem("proofos_org");
    if (!window.__proofos_unauthorized) {
      window.__proofos_unauthorized = true;
      window.location.reload();
    }
  }
  if (!r.ok) throw new Error(`${r.status} ${path}: ${JSON.stringify(data).slice(0, 300)}`);
  return data;
}

function Stat({ label, value, sub }) {
  return (
    <div className="card hover p-4">
      <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">{label}</p>
      <p className="text-2xl font-bold mt-2 text-slate-100 tabular-nums">{value}</p>
      {sub && <p className="text-[11px] text-slate-500 mt-1">{sub}</p>}
    </div>
  );
}

function Table({ head, children }) {
  return (
    <div className="overflow-x-auto card">
      <table className="w-full text-sm">
        <thead className="text-slate-400 text-left border-b border-slate-800">
          <tr>{head.map((h, i) => <th key={i} className="px-4 py-3 font-medium">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-slate-800">{children}</tbody>
      </table>
    </div>
  );
}

function Panel({ title, onClose, children }) {
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-semibold">{title}</h2>
        {onClose && <button onClick={onClose} className="text-slate-500 hover:text-slate-300 text-sm btn-ghost px-2 py-1 rounded-lg">✕ close</button>}
      </div>
      {children}
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label className="block text-xs text-slate-400 mb-1">
      {label}
      <div className="mt-1">{children}</div>
    </label>
  );
}

const inputCls = "w-full input px-3 py-2 text-sm text-slate-100";

function Bars({ data, color = "bg-violet-500" }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <div className="space-y-2">
      {data.map((d) => (
        <div key={d.label} className="flex items-center gap-2 text-xs">
          <span className="w-24 text-slate-400 truncate">{d.label}</span>
          <div className="flex-1 bg-slate-800 rounded h-3 overflow-hidden">
            <div className={`h-3 rounded transition-all ${d.color || color}`} style={{ width: `${Math.round((d.value / max) * 100)}%` }} />
          </div>
          <span className="w-8 text-right text-slate-500">{d.value}</span>
        </div>
      ))}
    </div>
  );
}

export default function App() {
  const [view, setView] = useState("dash");
  const [authToken, setAuthToken] = useState(token());
  const [orgId, setOrgId] = useState(Number(localStorage.getItem("proofos_org") || 1));
  const [orgName, setOrgName] = useState(localStorage.getItem("proofos_orgname") || "ProofOS Demo");
  const [devices, setDevices] = useState([]);
  const [tickets, setTickets] = useState([]);
  const [proofs, setProofs] = useState([]);
  const [automations, setAutomations] = useState([]);
  const [monitor, setMonitor] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [scripts, setScripts] = useState([]);
  const [runs, setRuns] = useState([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const [authBusy, setAuthBusy] = useState(false);
  const [setupCredentials, setSetupCredentials] = useState(null);
  const [search, setSearch] = useState("");
  const [verifyResult, setVerifyResult] = useState("");
  const [aiQuery, setAiQuery] = useState("Summarise offline devices");
  const [aiResult, setAiResult] = useState("");
  const [newTicket, setNewTicket] = useState({ title: "", body: "", priority: "normal" });
  const [newScript, setNewScript] = useState({ name: "", body: "echo ok", version: "1.0.0" });
  const [newDevice, setNewDevice] = useState({ hostname: "", os: "", ip: "", device_type: "workstation" });
  const [enrolled, setEnrolled] = useState(null);
  const [newAutomation, setNewAutomation] = useState({ name: "", trigger: "ticket.opened", action: "notify", condition: "", remediation_script_id: "" });
  const [newCheck, setNewCheck] = useState({ device_id: "", kind: "port", target: "", threshold_ms: "" });
  const [login, setLogin] = useState({ email: "", password: "" });

  const [selDevice, setSelDevice] = useState(null);
  const [deviceMetrics, setDeviceMetrics] = useState([]);
  const [selTicket, setSelTicket] = useState(null);
  const [comments, setComments] = useState([]);
  const [commentText, setCommentText] = useState("");
  const [selScript, setSelScript] = useState(null);
  const [runOutput, setRunOutput] = useState("");
  const [editAuto, setEditAuto] = useState(null);
  const [approvals, setApprovals] = useState([]);
  const [users, setUsers] = useState([]);
  const [deviceTypeFilter, setDeviceTypeFilter] = useState("");
  const [cmdBody, setCmdBody] = useState("");
  const [newUser, setNewUser] = useState({ email: "", password: "", role: "engineer" });
  const [passwordForm, setPasswordForm] = useState({ current_password: "", new_password: "", confirm_password: "" });
  const [passwordNotice, setPasswordNotice] = useState("");
  const [forgotOpen, setForgotOpen] = useState(false);
  const [resetEmail, setResetEmail] = useState("");
  const [resetBusy, setResetBusy] = useState(false);
  const [resetNotice, setResetNotice] = useState("");
  const [resetError, setResetError] = useState("");
  const [resetToken, setResetToken] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get("password_reset") || "");
  const [resetPassword, setResetPassword] = useState("");
  const [resetPasswordConfirm, setResetPasswordConfirm] = useState("");
  const [workspaceAdmin, setWorkspaceAdmin] = useState({ email: "", password: "" });
  const [proposeQuery, setProposeQuery] = useState("disk cleanup");
  const [audits, setAudits] = useState([]);
  const [auditKind, setAuditKind] = useState("full");
  const [auditResult, setAuditResult] = useState(null);
  const [steps, setSteps] = useState([]);
  const [clientProfile, setClientProfile] = useState(null);
  const [profileForm, setProfileForm] = useState({ contact_name: "", contact_email: "", phone: "", industry: "", status: "active", notes: "" });
  const [projects, setProjects] = useState([]);
  const [newProject, setNewProject] = useState({ name: "", description: "", status: "planning" });
  const [theme, setTheme] = useState(localStorage.getItem("proofos_theme") || "dark");
  const [cis, setCis] = useState([]);
  const [newCi, setNewCi] = useState({ name: "", ci_type: "server", status: "operational", description: "", attributes: "{}" });
  const [articles, setArticles] = useState([]);
  const [newArticle, setNewArticle] = useState({ title: "", body: "", category: "general", tags: "" });
  const [kbSearch, setKbSearch] = useState("");
  const [secrets, setSecrets] = useState([]);
  const [newSecret, setNewSecret] = useState({ name: "", value: "", category: "general", notes: "" });
  const [revealed, setRevealed] = useState(null);
  const [entries, setEntries] = useState([]);
  const [timeSummary, setTimeSummary] = useState(null);
  const [newEntry, setNewEntry] = useState({ minutes: "", notes: "", billable: true });
  const [changes, setChanges] = useState([]);
  const [newChange, setNewChange] = useState({ title: "", description: "", risk: "medium", impact: "medium", plan: "" });
  const [anomalies, setAnomalies] = useState([]);
  const [dashMode, setDashMode] = useState("operations");
  const [itsStatus, setItsStatus] = useState(null);
  const [itsTools, setItsTools] = useState(null);
  const [itsChain, setItsChain] = useState([]);
  const [vms, setVms] = useState([]);
  const [newVm, setNewVm] = useState({ name: "", host_id: "", hypervisor: "hyper-v", vcpu: "", memory_mb: "" });
  const [remoteSession, setRemoteSession] = useState(null);
  const [patches, setPatches] = useState([]);
  const [newPatch, setNewPatch] = useState({ name: "", device_id: "", category: "security", severity: "moderate", available_version: "" });
  const [apmSummary, setApmSummary] = useState(null);
  const [pushTokens, setPushTokens] = useState([]);
  const [pushToken, setPushToken] = useState("");
  const [pushResult, setPushResult] = useState(null);
  const [enclaves, setEnclaves] = useState([]);
  const [enclavePolicies, setEnclavePolicies] = useState([]);
  const [newEnclave, setNewEnclave] = useState({ name: "Secure Workspace", device_id: "", policy_id: "" });
  const [enclaveKey, setEnclaveKey] = useState(null);
  const [dlpScan, setDlpScan] = useState({ text: "", result: null });
  const [newPolicy, setNewPolicy] = useState({ name: "", blocked_apps: "", network_allowlist: "" });
  const [killSwitch, setKillSwitch] = useState(null);

  const load = useCallback(async () => {
    if (!authToken) return;
    setLoading(true);
    setErr("");
    try {
      const [d, t, p, a, m, al, s, ap, u, au, k, an] = await Promise.all([
        api(`/v1/devices?org_id=${orgId}`),
        api(`/v1/tickets?org_id=${orgId}`),
        api(`/v1/proof`),
        api(`/v1/automations?org_id=${orgId}`),
        api(`/v1/monitor?org_id=${orgId}`),
        api(`/v1/monitor/alerts?org_id=${orgId}`),
        api(`/v1/scripts?org_id=${orgId}`).catch(() => []),
        api(`/v1/approvals?org_id=${orgId}`).catch(() => []),
        api(`/v1/auth/users?org_id=${orgId}`).catch(() => []),
        api(`/v1/audits?org_id=${orgId}`).catch(() => []),
        api(`/v1/ops/kill-switch`).catch(() => ({ engaged: false })),
        api(`/v1/analytics/anomalies?org_id=${orgId}`).catch(() => []),
      ]);
      setDevices(Array.isArray(d) ? d : []);
      setTickets(Array.isArray(t) ? t : []);
      setProofs(Array.isArray(p) ? p : []);
      setAutomations(Array.isArray(a) ? a : []);
      setMonitor(Array.isArray(m) ? m : []);
      setAlerts(Array.isArray(al) ? al : []);
      setScripts(Array.isArray(s) ? s : []);
      setApprovals(Array.isArray(ap) ? ap : []);
      setUsers(Array.isArray(u) ? u : []);
      setAudits(Array.isArray(au) ? au : []);
      setKillSwitch(k);
      setAnomalies(Array.isArray(an) ? an : []);
    } catch (e) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, [authToken, orgId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    document.documentElement.classList.toggle("light", theme === "light");
    localStorage.setItem("proofos_theme", theme);
  }, [theme]);

  // Google SSO returns the token in the URL fragment so it is not sent in HTTP requests.
  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    const ssoToken = params.get("sso_token");
    if (ssoToken) {
      window.history.replaceState({}, document.title, window.location.pathname + window.location.search);
      activateSession(ssoToken);
    }
  }, []);

  // Live sync via WebSocket events.
  useEffect(() => {
    if (!authToken) return;
    let ws;
    let timer;
    try {
      const wsUrl = new URL("/v1/ws/events", API || window.location.origin);
      wsUrl.protocol = wsUrl.protocol === "https:" ? "wss:" : "ws:";
      wsUrl.searchParams.set("token", authToken);
      ws = new WebSocket(wsUrl);
      ws.onmessage = () => {
        clearTimeout(timer);
        timer = setTimeout(load, 300);
      };
    } catch {
      /* WS unavailable — polling still works via Refresh */
    }
    return () => {
      clearTimeout(timer);
      if (ws) ws.close();
    };
  }, [authToken, orgId, load]);

  async function activateSession(accessToken) {
    const claims = tokenClaims(accessToken);
    const sessionOrgId = Number(claims.org_id);
    localStorage.setItem("proofos_token", accessToken);
    if (Number.isInteger(sessionOrgId) && sessionOrgId > 0) {
      localStorage.setItem("proofos_org", String(sessionOrgId));
      setOrgId(sessionOrgId);
      try {
        const response = await fetch(`${API}/v1/auth/orgs/${sessionOrgId}`, {
          headers: { Authorization: `Bearer ${accessToken}` },
        });
        if (response.ok) {
          const org = await response.json();
          localStorage.setItem("proofos_orgname", org.name);
          setOrgName(org.name);
        }
      } catch {
        // Session remains usable when the optional org-name lookup is unavailable.
      }
    }
    setAuthToken(accessToken);
  }

  async function doLogin(event) {
    event?.preventDefault();
    setErr("");
    setAuthBusy(true);
    try {
      const response = await fetch(`${API}/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(login),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.access_token) {
        setErr(response.status === 401 ? "Email or password is incorrect." : errorText(result.detail, "Sign-in failed. Please try again."));
        return;
      }
      await activateSession(result.access_token);
    } catch {
      setErr("Could not reach the ProofOS server. Check that the API is running, then try again.");
    } finally {
      setAuthBusy(false);
    }
  }

  async function requestPasswordReset(event) {
    event?.preventDefault();
    setResetError("");
    setResetNotice("");
    setResetBusy(true);
    try {
      const response = await fetch(`${API}/v1/auth/password/reset-request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: resetEmail.trim() }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(errorText(result.detail, "Could not request a password reset."));
      setResetNotice(errorText(result.detail, "If an account matches that email, a password reset link will be sent."));
    } catch (e) {
      setResetError(e.message || "Could not reach the ProofOS server. Try again later.");
    } finally {
      setResetBusy(false);
    }
  }

  async function completePasswordReset(event) {
    event?.preventDefault();
    setResetError("");
    setResetNotice("");
    if (resetPassword.length < 12) {
      setResetError("Choose a new password with at least 12 characters.");
      return;
    }
    if (resetPassword !== resetPasswordConfirm) {
      setResetError("The passwords do not match.");
      return;
    }
    setResetBusy(true);
    try {
      const response = await fetch(`${API}/v1/auth/password/reset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: resetToken, new_password: resetPassword }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(errorText(result.detail, "This reset link is invalid or expired."));
      setResetNotice(errorText(result.detail, "Password updated. You can now sign in."));
      setLogin((current) => ({ ...current, password: "" }));
      setResetPassword("");
      setResetPasswordConfirm("");
      setResetToken("");
      window.history.replaceState({}, document.title, window.location.pathname + window.location.search);
    } catch (e) {
      setResetError(e.message || "Could not reset the password. Request a new link and try again.");
    } finally {
      setResetBusy(false);
    }
  }

  async function doBootstrap() {
    const workspaceName = orgName.trim();
    if (workspaceName.length < 2) {
      setErr("Enter a workspace name with at least 2 characters.");
      return;
    }
    if (!workspaceAdmin.email.trim() || workspaceAdmin.password.length < 12) {
      setErr("Enter an administrator email and a password with at least 12 characters.");
      return;
    }
    setErr("");
    setAuthBusy(true);
    try {
      const response = await fetch(`${API}/v1/auth/bootstrap`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: workspaceName, email: workspaceAdmin.email.trim(), password: workspaceAdmin.password }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.access_token) {
        setErr(errorText(result.detail, "Workspace setup failed. Please try another name or sign in."));
        return;
      }
      setOrgName(result.org.name);
      setLogin({ email: result.user.email, password: result.initial_password || "" });
      setSetupCredentials(result.initial_password ? { email: result.user.email, password: result.initial_password } : null);
      await activateSession(result.access_token);
    } catch {
      setErr("Could not reach the ProofOS server. Check that the API is running, then try again.");
    } finally {
      setAuthBusy(false);
      setWorkspaceAdmin((current) => ({ ...current, password: "" }));
    }
  }

  async function changePassword() {
    setErr("");
    setPasswordNotice("");
    if (passwordForm.new_password.length < 12) {
      setErr("Choose a new password with at least 12 characters.");
      return;
    }
    if (passwordForm.new_password !== passwordForm.confirm_password) {
      setErr("The new passwords do not match.");
      return;
    }
    try {
      await api("/v1/auth/password", {
        method: "POST",
        body: JSON.stringify({ current_password: passwordForm.current_password || null, new_password: passwordForm.new_password }),
      });
      setPasswordForm({ current_password: "", new_password: "", confirm_password: "" });
      setPasswordNotice("Password updated. Use it next time you sign in with email and password.");
    } catch (error) {
      setErr(error.message);
    }
  }

  async function verify(id) {
    setVerifyResult("");
    try {
      const j = await api(`/v1/proof/verify/${id}`);
      setVerifyResult(`${id}: verified=${j.verified} checks=${JSON.stringify(j.checks)}`);
    } catch (e) {
      setVerifyResult(e.message);
    }
  }

  async function downloadPdf(id) {
    try {
      const r = await fetch(`${API}/v1/audits/${id}/report.pdf`, { headers: { Authorization: `Bearer ${token()}` } });
      if (!r.ok) throw new Error(String(r.status));
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `proofos-audit-${id}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setErr(e.message);
    }
  }

  async function askAi() {
    setAiResult({ thinking: true });
    try {
      const j = await api(`/v1/ai/ask`, { method: "POST", body: JSON.stringify({ org_id: orgId, query: aiQuery }) });
      setAiResult(j);
    } catch (e) {
      setAiResult({ error: e.message });
    }
  }

  async function openDevice(id) {
    setErr("");
    try {
      const [dev, m] = await Promise.all([
        api(`/v1/devices/${id}`),
        api(`/v1/devices/${id}/metrics`).catch(() => []),
      ]);
      setSelDevice(dev);
      setDeviceMetrics(Array.isArray(m) ? m : []);
    } catch (e) {
      setErr(e.message);
    }
  }

  async function openTicket(id) {
    setErr("");
    try {
      const [t, c] = await Promise.all([
        api(`/v1/tickets/${id}`),
        api(`/v1/tickets/${id}/comments`),
      ]);
      setSelTicket(t);
      setComments(Array.isArray(c) ? c : []);
      setCommentText("");
    } catch (e) {
      setErr(e.message);
    }
  }

  async function addComment() {
    if (!selTicket || !commentText.trim()) return;
    try {
      await api(`/v1/tickets/${selTicket.id}/comments`, { method: "POST", body: JSON.stringify({ body: commentText }) });
      setCommentText("");
      openTicket(selTicket.id);
    } catch (e) {
      setErr(e.message);
    }
  }

  async function updateTicket(patch) {
    if (!selTicket) return;
    try {
      await api(`/v1/tickets/${selTicket.id}`, { method: "PATCH", body: JSON.stringify(patch) });
      openTicket(selTicket.id);
      load();
    } catch (e) {
      setErr(e.message);
    }
  }

  async function openScript(id) {
    setErr("");
    setRunOutput("");
    try {
      const [s, rs] = await Promise.all([
        api(`/v1/scripts/${id}`),
        api(`/v1/scripts/runs?org_id=${orgId}`).catch(() => []),
      ]);
      setSelScript(s);
      setRuns((Array.isArray(rs) ? rs : []).filter((r) => r.script_id === id));
    } catch (e) {
      setErr(e.message);
    }
  }

  async function viewRun(id) {
    try {
      const r = await api(`/v1/scripts/runs/${id}`);
      setRunOutput(r.output || "(no output)");
    } catch (e) {
      setErr(e.message);
    }
  }

  async function queueRun(scriptId, deviceId) {
    try {
      const j = await api(`/v1/scripts/${scriptId}/runs?device_id=${deviceId}`, { method: "POST", body: "{}" });
      alert(`queued run ${j.id}`);
      openScript(scriptId);
    } catch (e) {
      setErr(e.message);
    }
  }

  async function runChecks() {
    setErr("");
    try {
      const j = await api(`/v1/monitor/run?org_id=${orgId}`, { method: "POST", body: "{}" });
      setErr(`Ran checks: ${j.checked} device(s). See Monitor list.`);
      load();
    } catch (e) {
      setErr(e.message);
    }
  }

  async function loadAudits() {
    try { setAudits(await api(`/v1/audits?org_id=${orgId}`)); } catch { setAudits([]); }
  }
  async function loadOnboarding() {
    try { setSteps(await api(`/v1/onboarding?org_id=${orgId}`)); } catch { setSteps([]); }
  }
  async function loadConsulting() {
    try {
      const [p, pr] = await Promise.all([
        api(`/v1/consulting/profile?org_id=${orgId}`),
        api(`/v1/consulting/projects?org_id=${orgId}`),
      ]);
      setClientProfile(p);
      setProfileForm({ contact_name: p.contact_name || "", contact_email: p.contact_email || "", phone: p.phone || "", industry: p.industry || "", status: p.status || "active", notes: p.notes || "" });
      setProjects(Array.isArray(pr) ? pr : []);
    } catch { setClientProfile(null); setProjects([]); }
  }

  async function loadCmdb() { try { setCis(await api(`/v1/cmdb?org_id=${orgId}`)); } catch { setCis([]); } }
  async function loadKb() { try { setArticles(await api(`/v1/knowledge?org_id=${orgId}${kbSearch ? `&q=${encodeURIComponent(kbSearch)}` : ""}`)); } catch { setArticles([]); } }
  async function loadVault() { try { setSecrets(await api(`/v1/secrets?org_id=${orgId}`)); } catch { setSecrets([]); } }
  async function loadTime() {
    try {
      const [e, s] = await Promise.all([api(`/v1/time?org_id=${orgId}`), api(`/v1/time/summary?org_id=${orgId}`)]);
      setEntries(Array.isArray(e) ? e : []);
      setTimeSummary(s);
    } catch { setEntries([]); setTimeSummary(null); }
  }
  async function loadChanges() { try { setChanges(await api(`/v1/changes?org_id=${orgId}`)); } catch { setChanges([]); } }
  async function loadAnomalies() {
    try {
      const [a, apm] = await Promise.all([
        api(`/v1/analytics/anomalies?org_id=${orgId}`),
        api(`/v1/analytics/apm?org_id=${orgId}`),
      ]);
      setAnomalies(a);
      setApmSummary(apm);
    } catch { setAnomalies([]); setApmSummary(null); }
  }
  async function loadPatches() { try { setPatches(await api(`/v1/patches?org_id=${orgId}`)); } catch { setPatches([]); } }
  async function loadPush() { try { setPushTokens(await api(`/v1/push?org_id=${orgId}`)); } catch { setPushTokens([]); } }
  async function loadEnclaves() {
    try {
      const [e, p] = await Promise.all([api(`/v1/enclaves?org_id=${orgId}`), api(`/v1/enclaves/policies?org_id=${orgId}`)]);
      setEnclaves(e); setEnclavePolicies(p);
    } catch { setEnclaves([]); setEnclavePolicies([]); }
  }
  async function loadIts() {
    try {
      const [s, t, c] = await Promise.all([
        api(`/v1/itechsmart/status`),
        api(`/v1/itechsmart/tools`),
        api(`/v1/itechsmart/chain`),
      ]);
      setItsStatus(s);
      setItsTools(t);
      setItsChain(Array.isArray(c.receipts) ? c.receipts : []);
    } catch { setItsStatus(null); setItsTools(null); setItsChain([]); }
  }
  async function loadVms() { try { setVms(await api(`/v1/vms?org_id=${orgId}`)); } catch { setVms([]); } }

  useEffect(() => {
    if (view === "audit") loadAudits();
    if (view === "onboarding") loadOnboarding();
    if (view === "consulting") loadConsulting();
    if (view === "cmdb") loadCmdb();
    if (view === "knowledge") loadKb();
    if (view === "vault") loadVault();
    if (view === "time") loadTime();
    if (view === "changes") loadChanges();
    if (view === "analytics") loadAnomalies();
    if (view === "itechsmart") loadIts();
    if (view === "vms") loadVms();
    if (view === "patches") loadPatches();
    if (view === "admin") loadPush();
    if (view === "enclaves") loadEnclaves();
  }, [view]);

  if (!authToken && resetToken) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center p-6">
        <section className="bg-slate-900 border border-slate-800 p-7 rounded-2xl w-full max-w-md shadow-2xl shadow-black/30" aria-labelledby="reset-title">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 rounded-xl gradient-bar flex items-center justify-center text-white font-black">P</div>
            <div><h1 id="reset-title" className="text-2xl font-bold">Choose a new password</h1><p className="text-xs text-slate-400 mt-1">Your reset link expires after 20 minutes.</p></div>
          </div>
          <form onSubmit={completePasswordReset} className="space-y-4">
            <Field label="New password"><input type="password" autoComplete="new-password" minLength={12} className={inputCls} value={resetPassword} onChange={(e) => setResetPassword(e.target.value)} required /></Field>
            <Field label="Confirm new password"><input type="password" autoComplete="new-password" minLength={12} className={inputCls} value={resetPasswordConfirm} onChange={(e) => setResetPasswordConfirm(e.target.value)} required /></Field>
            {resetError && <p role="alert" className="text-sm text-red-300 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">{resetError}</p>}
            <button type="submit" disabled={resetBusy} className="w-full bg-violet-600 hover:bg-violet-500 disabled:opacity-60 py-2.5 rounded-lg font-semibold">{resetBusy ? "Updating password…" : "Update password"}</button>
          </form>
          {resetNotice && <p role="status" className="text-sm text-emerald-300 mt-4">{resetNotice} <button type="button" className="underline underline-offset-4" onClick={() => { setResetNotice(""); window.history.replaceState({}, document.title, window.location.pathname + window.location.search); }}>Return to sign in</button></p>}
        </section>
      </div>
    );
  }

  if (!authToken) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center p-6">
        <div className="bg-slate-900 border border-slate-800 p-7 rounded-2xl w-full max-w-md shadow-2xl shadow-black/30">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 rounded-xl gradient-bar flex items-center justify-center text-white font-black">P</div>
            <div><h1 className="text-2xl font-bold">Proof<span className="gradient-text">OS</span></h1><p className="text-xs text-slate-500 mt-1">Operations with an audit trail</p></div>
          </div>
          <form onSubmit={doLogin}>
            <div className="space-y-3">
              <Field label="Email"><input type="email" autoComplete="username" className={inputCls} value={login.email} onChange={(e) => setLogin({ ...login, email: e.target.value })} required /></Field>
              <div>
                <div className="flex items-center justify-between mb-1"><label htmlFor="login-password" className="text-xs text-slate-400">Password</label><button type="button" onClick={() => { setResetEmail(login.email); setResetError(""); setResetNotice(""); setForgotOpen(true); }} className="text-xs text-violet-300 hover:text-violet-200 underline underline-offset-4">Forgot password?</button></div>
                <input id="login-password" type="password" autoComplete="current-password" className={inputCls} value={login.password} onChange={(e) => setLogin({ ...login, password: e.target.value })} required />
              </div>
            </div>
            {err && <p role="alert" className="text-sm text-red-300 mt-4 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">{err}</p>}
            <button type="submit" disabled={authBusy} className="w-full mt-5 bg-violet-600 hover:bg-violet-500 disabled:opacity-60 py-2.5 rounded-lg font-semibold">{authBusy ? "Signing in…" : "Sign in"}</button>
          </form>
          {resetNotice && !forgotOpen && <p role="status" className="text-sm text-emerald-300 mt-4">{resetNotice}</p>}
          <div className="relative my-4 text-center"><span className="bg-slate-900 px-2 text-xs text-slate-500">or continue with</span><div className="absolute inset-x-0 top-1/2 -z-0 border-t border-slate-800" /></div>
          <a href={`${API}/v1/sso/google/login`} className="flex items-center justify-center gap-2.5 w-full py-2.5 rounded-lg font-semibold bg-slate-800 hover:bg-slate-700 text-sm border border-slate-700/70" aria-label="Continue with Google">
            <svg aria-hidden="true" viewBox="0 0 48 48" className="w-5 h-5"><path fill="#4285F4" d="M43.6 24.5c0-1.4-.1-2.8-.4-4.1H24v7.8h11a9.4 9.4 0 0 1-4.1 6.2v5.1h6.6c3.9-3.6 6.1-8.8 6.1-15Z"/><path fill="#34A853" d="M24 44c5.5 0 10.1-1.8 13.5-4.9l-6.6-5.1c-1.8 1.2-4 2-6.9 2-5.3 0-9.8-3.6-11.4-8.4H5.8v5.3A20 20 0 0 0 24 44Z"/><path fill="#FBBC05" d="M12.6 27.6a12 12 0 0 1 0-7.2v-5.3H5.8a20 20 0 0 0 0 17.8l6.8-5.3Z"/><path fill="#EA4335" d="M24 12c3 0 5.7 1 7.8 3.1l5.8-5.8C34.1 6 29.5 4 24 4A20 20 0 0 0 5.8 15.1l6.8 5.3C14.2 15.6 18.7 12 24 12Z"/></svg>
            Continue with Google
          </a>
          <details className="mt-5 border-t border-slate-800 pt-4">
            <summary className="list-none cursor-pointer rounded-xl border border-slate-700 bg-slate-800/70 hover:bg-slate-800 px-4 py-3.5 flex items-center justify-between gap-3 transition-colors">
              <span><span className="block text-sm font-semibold text-slate-100">New to ProofOS?</span><span className="block text-xs text-slate-400 mt-1">Create a company workspace and administrator account</span></span>
              <span className="shrink-0 rounded-lg bg-violet-600 hover:bg-violet-500 px-3 py-2 text-xs font-semibold text-white">Create workspace</span>
            </summary>
            <div className="mt-3">
              <Field label="Workspace name"><input className={inputCls} value={orgName} onChange={(e) => setOrgName(e.target.value)} placeholder="Your company name" minLength={2} maxLength={255} /></Field>
              <Field label="Administrator email"><input type="email" autoComplete="email" className={inputCls} value={workspaceAdmin.email} onChange={(e) => setWorkspaceAdmin({ ...workspaceAdmin, email: e.target.value })} placeholder="you@company.com" required /></Field>
              <Field label="Administrator password"><input type="password" autoComplete="new-password" minLength={12} className={inputCls} value={workspaceAdmin.password} onChange={(e) => setWorkspaceAdmin({ ...workspaceAdmin, password: e.target.value })} placeholder="At least 12 characters" required /></Field>
              <p className="text-xs text-slate-400 mt-2">Creates an isolated workspace with the administrator login you choose. Existing workspaces cannot be claimed through setup.</p>
              <button type="button" onClick={doBootstrap} disabled={authBusy} className="w-full mt-3 bg-violet-600 hover:bg-violet-500 disabled:opacity-60 py-2.5 rounded-lg font-semibold">{authBusy ? "Creating workspace…" : "Create workspace and sign in"}</button>
            </div>
          </details>
          {forgotOpen && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) setForgotOpen(false); }}>
            <section role="dialog" aria-modal="true" aria-labelledby="forgot-title" className="w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl">
              <div className="flex items-start justify-between gap-4"><div><h2 id="forgot-title" className="text-lg font-semibold text-slate-100">Reset your password</h2><p className="text-sm text-slate-400 mt-1">We’ll email a secure, short-lived reset link if the account exists.</p></div><button type="button" aria-label="Close" onClick={() => setForgotOpen(false)} className="text-slate-400 hover:text-white">✕</button></div>
              <form onSubmit={requestPasswordReset} className="mt-5">
                <Field label="Account email"><input type="email" autoComplete="email" className={inputCls} value={resetEmail} onChange={(e) => setResetEmail(e.target.value)} required /></Field>
                {resetError && <p role="alert" className="text-sm text-red-300 mt-3 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">{resetError}</p>}
                {resetNotice && <p role="status" className="text-sm text-emerald-300 mt-3">{resetNotice}</p>}
                <div className="flex gap-3 mt-5"><button type="button" onClick={() => setForgotOpen(false)} className="flex-1 btn-ghost rounded-lg py-2.5 font-medium">Back to sign in</button><button type="submit" disabled={resetBusy} className="flex-1 bg-violet-600 hover:bg-violet-500 disabled:opacity-60 rounded-lg py-2.5 font-semibold">{resetBusy ? "Sending…" : "Send reset link"}</button></div>
              </form>
            </section>
          </div>}
        </div>
      </div>
    );
  }

  const offline = devices.filter((d) => d.status !== "online");
  const openTickets = tickets.filter((t) => t.status === "open");
  const filteredDevices = devices.filter((d) => d.hostname.toLowerCase().includes(search.toLowerCase()) && (!deviceTypeFilter || d.device_type === deviceTypeFilter));
  const isBreached = (t) => t.due_at && new Date(t.due_at) < Date.now() && !["closed", "cancelled"].includes(t.status);

  const deviceHealth = [
    { label: "Online", value: devices.filter((d) => d.status === "online").length, color: "bg-violet-500" },
    { label: "Offline", value: devices.filter((d) => d.status === "offline").length, color: "bg-red-500" },
    { label: "Stale", value: devices.filter((d) => d.status === "stale").length, color: "bg-amber-500" },
    { label: "Other", value: devices.filter((d) => !["online", "offline", "stale"].includes(d.status)).length, color: "bg-slate-500" },
  ];
  const ticketStatus = ["open", "in_progress", "pending", "resolved", "closed", "cancelled"].map((s) => ({ label: s.replace("_", " "), value: tickets.filter((t) => t.status === s).length }));
  const alertSev = [
    { label: "Critical", value: alerts.filter((a) => a.severity === "critical" && !a.acked).length, color: "bg-red-500" },
    { label: "Warning", value: alerts.filter((a) => a.severity === "warning" && !a.acked).length, color: "bg-amber-500" },
  ];
  const deviceTypes = ["workstation", "server", "access_point", "gateway", "switch", "node"].map((t) => ({ label: t.replace("_", " "), value: devices.filter((d) => d.device_type === t).length }));
  const auditScores = audits.slice(0, 8).reverse().map((a) => ({ label: `#${a.id} ${a.kind}`, value: Math.round(a.score) }));
  const recentActivity = proofs.slice(0, 8);

  const nav = [
    ["dash", "Overview"], ["analytics", "Analytics"], ["devices", "Devices"], ["tickets", "Tickets"],
    ["monitor", "Monitor"], ["scripts", "Scripts"], ["automations", "Automations"],
    ["proof", "Proof"], ["ai", "AI Copilot"], ["admin", "Admin"],
    ["cmdb", "CMDB"], ["knowledge", "Knowledge"], ["vault", "Vault"], ["changes", "Changes"], ["time", "Time"],
    ["vms", "VMs"], ["patches", "Patches"], ["enclaves", "Workspaces"], ["itechsmart", "iTechSmart"],
    ["audit", "Audit"], ["onboarding", "Onboarding"], ["consulting", "Consulting"],
  ];
  const navGroups = [
    { label: "Workspace", ids: ["dash", "analytics"] },
    { label: "Operations", ids: ["devices", "monitor", "tickets", "scripts", "automations", "vms", "patches"] },
    { label: "Governance", ids: ["proof", "audit", "changes", "vault"] },
    { label: "Service delivery", ids: ["knowledge", "cmdb", "time", "onboarding", "consulting"] },
    { label: "Platform", ids: ["ai", "admin", "itechsmart"] },
  ].map((group) => ({ ...group, items: group.ids.map((id) => nav.find(([key]) => key === id)).filter(Boolean) }));
  const emptyWorkspace = devices.length === 0 && tickets.length === 0;

  return (
    <div className="min-h-screen app-bg text-slate-100">
      <header className="sticky top-0 z-20 border-b border-slate-800/60 px-4 md:px-6 py-3 flex flex-wrap items-center gap-3 backdrop-blur-xl bg-slate-950/90">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl gradient-bar flex items-center justify-center font-black text-white shadow-lg shadow-violet-500/25">P</div>
          <h1 className="text-lg font-extrabold tracking-tight">Proof<span className="gradient-text">OS</span></h1>
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold truncate">{orgName}</p>
          <p className="text-[11px] text-slate-500">Operations workspace · org {orgId}</p>
        </div>
        <div className="ml-auto flex items-center gap-1">
          <button onClick={() => setTheme(theme === "dark" ? "light" : "dark")} className="nav-pill px-3 py-2 text-xs text-slate-400" title="Toggle theme">{theme === "dark" ? "☀ Light" : "🌙 Dark"}</button>
          <button onClick={load} className="nav-pill px-3 py-2 text-xs text-slate-400">Refresh</button>
          <button onClick={() => { localStorage.removeItem("proofos_token"); setAuthToken(""); setSetupCredentials(null); }} className="nav-pill px-3 py-2 text-xs text-red-400">Logout</button>
        </div>
      </header>

      {setupCredentials && <section role="status" className="mx-4 md:mx-6 mt-4 rounded-xl border border-amber-400/30 bg-amber-400/10 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><h2 className="text-sm font-semibold text-amber-200">Save your one-time administrator login</h2><p className="text-xs text-slate-300 mt-1">This generated password is shown only now. Store it in your password manager.</p></div>
          <button onClick={() => setSetupCredentials(null)} className="text-xs text-slate-400 hover:text-white">Dismiss</button>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 text-sm">
          <div><span className="text-xs text-slate-500 block">Email</span><code>{setupCredentials.email}</code></div>
          <div><span className="text-xs text-slate-500 block">One-time password</span><code className="select-all break-all">{setupCredentials.password}</code></div>
        </div>
        <button onClick={() => navigator.clipboard?.writeText(`${setupCredentials.email}\n${setupCredentials.password}`)} className="mt-3 btn-ghost rounded-lg px-3 py-1.5 text-xs">Copy login details</button>
      </section>}
      {err && <div role="alert" className="mx-4 md:mx-6 mt-3 text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">{err}</div>}
      {loading && <div role="status" className="mx-4 md:mx-6 mt-3 text-xs text-slate-500">Loading workspace…</div>}

      <div className="lg:flex lg:items-start">
        <aside aria-label="Main navigation" className="hidden lg:flex lg:sticky lg:top-[65px] lg:h-[calc(100vh-65px)] lg:w-60 lg:shrink-0 lg:flex-col lg:overflow-y-auto border-r border-slate-800/60 bg-slate-950/30 px-3 py-5">
          {navGroups.map((group) => <section key={group.label} className="mb-5">
            <h2 className="px-3 mb-2 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">{group.label}</h2>
            <div className="grid gap-1">{group.items.map(([id, label]) => <button key={id} aria-current={view === id ? "page" : undefined} onClick={() => setView(id)} className={`nav-pill w-full px-3 py-2 text-left text-sm font-medium ${view === id ? "active" : "text-slate-400"}`}>{label}</button>)}</div>
          </section>)}
          <p className="mt-auto px-3 pt-4 text-[10px] leading-relaxed text-slate-600">ProofOS · audited operations</p>
        </aside>
        <div className="min-w-0 flex-1">
          <nav aria-label="Mobile navigation" className="lg:hidden border-b border-slate-800/60 px-4 py-2 overflow-x-auto">
            <div className="flex w-max gap-1">{nav.map(([id, label]) => <button key={id} aria-current={view === id ? "page" : undefined} onClick={() => setView(id)} className={`nav-pill whitespace-nowrap px-3 py-2 text-xs font-medium ${view === id ? "active" : "text-slate-400"}`}>{label}</button>)}</div>
          </nav>
          <main className="p-4 md:p-6 grid gap-6">
        {view === "dash" && (
          <>
            <section className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
              <Stat label="Devices" value={devices.length} sub={`${offline.length} offline`} />
              <Stat label="Open tickets" value={openTickets.length} sub={`${tickets.length} total`} />
              <Stat label="Proof records" value={proofs.length} sub="hash-chained" />
              <Stat label="Alerts" value={alerts.filter((a) => !a.acked).length} sub="unacked" />
              <Stat label="Approvals" value={approvals.filter((a) => a.status === "pending").length} sub="human-gated" />
              <Stat label="Audit score" value={audits[0] ? audits[0].score : "—"} sub={audits[0] ? `#${audits[0].id} ${audits[0].kind}` : "run an audit"} />
            </section>

            <div className="flex gap-2">
              <button onClick={() => setDashMode("operations")} className={`px-3 py-1.5 rounded-lg text-xs ${dashMode === "operations" ? "bg-slate-700" : "bg-slate-900 hover:bg-slate-800"}`}>⚙ Operations view</button>
              <button onClick={() => setDashMode("executive")} className={`px-3 py-1.5 rounded-lg text-xs ${dashMode === "executive" ? "bg-slate-700" : "bg-slate-900 hover:bg-slate-800"}`}>📊 Executive view</button>
            </div>
            {emptyWorkspace && <section className="card p-5 md:p-6 flex flex-wrap items-center justify-between gap-5 border-violet-500/20">
              <div className="max-w-2xl">
                <p className="text-[10px] uppercase tracking-[0.16em] font-bold text-violet-300">Your workspace is ready</p>
                <p className="mt-2 text-lg font-semibold text-slate-100">Start with the work you need to manage</p>
                <p className="mt-2 text-sm text-slate-400">Register a device to begin monitoring, create a ticket for a service request, or run an audit to see the current governance baseline.</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button onClick={() => setView("devices")} className="bg-violet-600 px-4 py-2 rounded-lg text-sm font-semibold">Add first device</button>
                <button onClick={() => setView("tickets")} className="btn-ghost px-4 py-2 rounded-lg text-sm">Create ticket</button>
                <button onClick={() => setView("audit")} className="btn-ghost px-4 py-2 rounded-lg text-sm">Run audit</button>
              </div>
            </section>}
            {dashMode === "executive" && (
              <div className="card p-4">
                <h2 className="font-semibold mb-2">Executive summary</h2>
                <p className="text-sm text-slate-300">
                  {devices.length} managed devices · {tickets.length} tickets · {proofs.length} proof records · {users.length} users.
                  Latest audit: {audits[0] ? `${audits[0].kind} score ${audits[0].score}/100` : "not run yet"}.
                  {alerts.filter((a) => !a.acked).length} open alerts · {approvals.filter((a) => a.status === "pending").length} pending approvals.
                </p>
                <p className="text-xs text-slate-500 mt-1">Proof-verified activity: every action above is hash-chained and exportable for compliance.</p>
              </div>
            )}

            <section className="grid md:grid-cols-2 xl:grid-cols-4 gap-4">
              <div className="card p-4">
                <h2 className="font-semibold mb-3">Device health</h2>
                <Bars data={deviceHealth} />
              </div>
              <div className="card p-4">
                <h2 className="font-semibold mb-3">Tickets by status</h2>
                <Bars data={ticketStatus} />
              </div>
              <div className="card p-4">
                <h2 className="font-semibold mb-3">Open alerts</h2>
                <Bars data={alertSev} />
                <button className="text-xs text-sky-400 hover:underline mt-2" onClick={() => setView("monitor")}>View monitor →</button>
              </div>
              <div className="card p-4">
                <h2 className="font-semibold mb-3">Devices by type</h2>
                <Bars data={deviceTypes} />
              </div>
            </section>

            <section className="grid md:grid-cols-2 gap-4">
              <div className="card p-4">
                <h2 className="font-semibold mb-2">Live activity</h2>
                {recentActivity.length === 0 ? <p className="text-sm text-slate-500">No activity yet.</p> : (
                  <ul className="text-xs divide-y divide-slate-800">
                    {recentActivity.map((p) => (
                      <li key={p.id} className="py-1 flex justify-between gap-2">
                        <span className="truncate">{p.what}</span>
                        <button onClick={() => verify(p.id)} className="text-violet-400 hover:underline whitespace-nowrap">verify</button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="card p-4">
                <h2 className="font-semibold mb-3">Quick actions</h2>
                <div className="grid grid-cols-2 gap-2">
                  <button className="bg-slate-800 border border-slate-700 rounded-lg py-2 text-sm hover:bg-slate-700" onClick={() => setView("audit")}>Run audit</button>
                  <button className="bg-slate-800 border border-slate-700 rounded-lg py-2 text-sm hover:bg-slate-700" onClick={() => setView("ai")}>AI copilot</button>
                  <button className="bg-slate-800 border border-slate-700 rounded-lg py-2 text-sm hover:bg-slate-700" onClick={() => setView("devices")}>Add device</button>
                  <button className="bg-slate-800 border border-slate-700 rounded-lg py-2 text-sm hover:bg-slate-700" onClick={() => setView("admin")}>Approvals</button>
                </div>
                {offline.length > 0 && (
                  <div className="mt-3">
                    <h3 className="text-xs text-slate-400 mb-1">Offline devices</h3>
                    <ul className="text-sm">{offline.map((d) => <li key={d.id} className="py-1">⚠ {d.hostname} · {d.status}</li>)}</ul>
                  </div>
                )}
                {verifyResult && <p className="text-xs text-violet-300 mt-2 break-all">{verifyResult}</p>}
              </div>
            </section>
          </>
        )}

        {view === "analytics" && (
          <section className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
            <div className="card p-4">
              <h2 className="font-semibold mb-3">Device health</h2>
              <Bars data={deviceHealth} />
            </div>
            <div className="card p-4">
              <h2 className="font-semibold mb-3">Tickets by status</h2>
              <Bars data={ticketStatus} />
            </div>
            <div className="card p-4">
              <h2 className="font-semibold mb-3">Devices by type</h2>
              <Bars data={deviceTypes} />
            </div>
            <div className="card p-4">
              <h2 className="font-semibold mb-3">Audit scores (recent)</h2>
              {auditScores.length === 0 ? <p className="text-sm text-slate-500">No audits yet — run one in Audit.</p> : <Bars data={auditScores} />}
            </div>
            <div className="card p-4">
              <h2 className="font-semibold mb-3">Open alerts</h2>
              <Bars data={alertSev} />
            </div>
            <div className="card p-4">
              <h2 className="font-semibold mb-3">Inventory totals</h2>
              <div className="grid grid-cols-2 gap-3 text-center">
                <div className="bg-slate-950 border border-slate-800 rounded-lg p-3"><div className="text-2xl font-bold">{devices.length}</div><div className="text-xs text-slate-500">devices</div></div>
                <div className="bg-slate-950 border border-slate-800 rounded-lg p-3"><div className="text-2xl font-bold">{tickets.length}</div><div className="text-xs text-slate-500">tickets</div></div>
                <div className="bg-slate-950 border border-slate-800 rounded-lg p-3"><div className="text-2xl font-bold">{scripts.length}</div><div className="text-xs text-slate-500">scripts</div></div>
                <div className="bg-slate-950 border border-slate-800 rounded-lg p-3"><div className="text-2xl font-bold">{automations.length}</div><div className="text-xs text-slate-500">automations</div></div>
              </div>
            </div>
            <div className="card p-4">
              <h2 className="font-semibold mb-3">Metric anomalies (AIOps)</h2>
              {anomalies.length === 0 ? <p className="text-sm text-slate-500">No anomalies detected in recent telemetry.</p> : (
                <ul className="text-xs divide-y divide-slate-800">
                  {anomalies.map((a, i) => (
                    <li key={i} className="py-1 flex justify-between gap-2">
                      <span>{a.hostname} · {a.metric} = {a.value} (z {a.robust_z})</span>
                      <HealthPill status={a.severity} />
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="card p-4">
              <h2 className="font-semibold mb-3">APM (request tracing)</h2>
              {apmSummary?.spans > 0 ? (
                <div className="text-xs text-slate-300 space-y-1">
                  <div>{apmSummary.spans} spans · avg {apmSummary.avg_ms}ms · p95 {apmSummary.p95_ms}ms · max {apmSummary.max_ms}ms</div>
                  {apmSummary.slowest_paths?.slice(0, 5).map((p) => <div key={p.path} className="text-slate-500">{p.path} · {p.avg_ms}ms · ×{p.count}</div>)}
                </div>
              ) : <p className="text-sm text-slate-500">{apmSummary?.enabled_note || "No spans."}</p>}
            </div>
          </section>
        )}

        {view === "devices" && (
          <>
            <div className="flex flex-wrap gap-2">
              <input className="bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm" placeholder="Search hostname…" value={search} onChange={(e) => setSearch(e.target.value)} />
              <select className="bg-slate-900 border border-slate-800 rounded px-2 py-2 text-sm" value={deviceTypeFilter} onChange={(e) => setDeviceTypeFilter(e.target.value)}>
                <option value="">all types</option>
                {["workstation", "server", "access_point", "gateway", "switch", "node"].map((t) => <option key={t} value={t}>{t.replace("_", " ")}</option>)}
              </select>
              <input className="bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm" placeholder="hostname" value={newDevice.hostname} onChange={(e) => setNewDevice({ ...newDevice, hostname: e.target.value })} />
              <input className="bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm" placeholder="os" value={newDevice.os} onChange={(e) => setNewDevice({ ...newDevice, os: e.target.value })} />
              <input className="bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm" placeholder="ip" value={newDevice.ip} onChange={(e) => setNewDevice({ ...newDevice, ip: e.target.value })} />
              <select className="bg-slate-900 border border-slate-800 rounded px-2 py-2 text-sm" value={newDevice.device_type} onChange={(e) => setNewDevice({ ...newDevice, device_type: e.target.value })}>
                {["workstation", "server", "access_point", "gateway", "switch", "node"].map((t) => <option key={t} value={t}>{t.replace("_", " ")}</option>)}
              </select>
              <button className="bg-violet-600 px-3 py-2 rounded text-sm" onClick={async () => {
                const j = await api(`/v1/devices`, { method: "POST", body: JSON.stringify({ org_id: orgId, ...newDevice }) });
                setNewDevice({ hostname: "", os: "", ip: "", device_type: "workstation" });
                setEnrolled(j);
                load();
              }}>Register</button>
              <button className="bg-sky-600 px-3 py-2 rounded text-sm" onClick={async () => { const j = await api(`/v1/devices/refresh-status?org_id=${orgId}`, { method: "POST", body: "{}" }); setErr(`Status sync: ${j.changed} changed, ${j.alerts} alert(s).`); load(); }}>Refresh statuses</button>
            </div>
            {enrolled && (
              <Panel title={`Device enrolled · ${enrolled.hostname}`} onClose={() => setEnrolled(null)}>
                <p className="text-sm text-slate-300 mb-2">Install the agent with this one-time secret (copy it now):</p>
                <pre className="text-xs bg-slate-950 border border-slate-800 rounded p-3 overflow-auto mb-2">{`python agent.py --api ${API || window.location.origin} --device-id ${enrolled.id} --token ${enrolled.device_secret}`}</pre>
                <p className="text-xs text-slate-500">The secret is shown once; rotate it anytime from the device detail.</p>
              </Panel>
            )}
            {selDevice && (
              <Panel title={`Device · ${selDevice.hostname}`} onClose={() => setSelDevice(null)}>
                <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-sm mb-3">
                  <div><span className="text-slate-500">Type</span><div>{selDevice.device_type || "—"}</div></div>
                  <div><span className="text-slate-500">OS</span><div>{selDevice.os || "—"}</div></div>
                  <div><span className="text-slate-500">IP</span><div>{selDevice.ip || "—"}</div></div>
                  <div><span className="text-slate-500">Status</span><div><HealthPill status={selDevice.status} /></div></div>
                  <div><span className="text-slate-500">Last seen</span><div className="text-xs">{selDevice.last_seen || "—"}</div></div>
                </div>
                <div className="mb-3">
                  <h3 className="text-xs text-slate-400 mb-1">Telemetry history (CPU/Disk/Mem %)</h3>
                  {deviceMetrics.length === 0 ? <p className="text-sm text-slate-500">No heartbeats yet.</p> : (
                    <ul className="text-xs divide-y divide-slate-800 max-h-48 overflow-auto">
                      {deviceMetrics.slice(0, 20).map((m) => <li key={m.id} className="py-1 flex justify-between"><span>{m.created_at}</span><span>CPU {Number(m.cpu).toFixed(0)} · Disk {Number(m.disk).toFixed(0)} · Mem {Number(m.mem).toFixed(0)}</span></li>)}
                    </ul>
                  )}
                </div>
                <div className="mb-3">
                  <h3 className="text-xs text-slate-400 mb-1">Remote command (via agent)</h3>
                  <div className="flex gap-2">
                    <input className={inputCls} placeholder="e.g. df -h / ipconfig / show version" value={cmdBody} onChange={(e) => setCmdBody(e.target.value)} />
                    <button className="bg-sky-600 px-3 py-2 rounded text-sm whitespace-nowrap" onClick={async () => {
                      if (!cmdBody.trim()) return;
                      await api(`/v1/devices/${selDevice.id}/command`, { method: "POST", body: JSON.stringify({ body: cmdBody, description: "console" }) });
                      setCmdBody("");
                      setErr("Command queued — agent will execute and log output under Scripts → run history.");
                    }}>Run</button>
                  </div>
                </div>
                <div className="flex gap-4 mb-2 flex-wrap">
                  <button className="text-xs text-sky-400 hover:underline" onClick={async () => { const j = await api(`/v1/remote/devices/${selDevice.id}/remote-session`, { method: "POST", body: JSON.stringify({ kind: "console" }) }); setRemoteSession(j); }}>Open console session</button>
                  <button className="text-xs text-sky-400 hover:underline" onClick={async () => { const j = await api(`/v1/remote/devices/${selDevice.id}/remote-session`, { method: "POST", body: JSON.stringify({ kind: "kvm", provider: "vnc" }) }); setRemoteSession(j); }}>Open KVM (VNC)</button>
                  <button className="text-xs text-sky-400 hover:underline" onClick={async () => { const j = await api(`/v1/devices/${selDevice.id}/rotate-secret`, { method: "POST", body: "{}" }); setEnrolled({ id: selDevice.id, hostname: selDevice.hostname, device_secret: j.device_secret }); }}>Rotate agent secret</button>
                  <button className="text-xs text-red-400 hover:underline" onClick={async () => { await api(`/v1/devices/${selDevice.id}`, { method: "DELETE" }); setSelDevice(null); load(); }}>Delete device</button>
                </div>
                {remoteSession && (
                  <div className="text-xs bg-slate-950 border border-slate-800 rounded p-2 mb-2 break-all">
                    Session #{remoteSession.session_id} ({remoteSession.kind}/{remoteSession.provider}) · token <code>{remoteSession.token}</code>
                    {remoteSession.ws_url && <div>WS: <code>{remoteSession.ws_url}</code></div>}
                    {remoteSession.connect_url && <div>Connect: <a className="text-sky-400 underline" href={remoteSession.connect_url} target="_blank" rel="noreferrer">{remoteSession.connect_url}</a></div>}
                    {remoteSession.note && <div className="text-slate-500 mt-1">{remoteSession.note}</div>}
                  </div>
                )}
              </Panel>
            )}
            <Table head={["Hostname", "Type", "OS / IP", "Status", "CPU", "Disk", "Mem"]}>
              {filteredDevices.map((d) => (
                <tr key={d.id} className="cursor-pointer hover:bg-slate-800/50" onClick={() => openDevice(d.id)}>
                  <td className="px-4 py-3">{d.hostname}</td>
                  <td className="px-4 py-3 text-xs text-slate-400">{(d.device_type || "workstation").replace("_", " ")}</td>
                  <td className="px-4 py-3 text-slate-400">{d.os} · {d.ip}</td>
                  <td className="px-4 py-3"><HealthPill status={d.status} /></td>
                  <td className="px-4 py-3">{Number(d.cpu || 0).toFixed(0)}%</td>
                  <td className="px-4 py-3">{Number(d.disk || 0).toFixed(0)}%</td>
                  <td className="px-4 py-3">{Number(d.mem || 0).toFixed(0)}%</td>
                </tr>
              ))}
            </Table>
          </>
        )}

        {view === "tickets" && (
          <>
            <div className="grid md:grid-cols-3 gap-2">
              <input className="bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm" placeholder="Title e.g. printer offline" value={newTicket.title} onChange={(e) => setNewTicket({ ...newTicket, title: e.target.value })} />
              <input className="bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm" placeholder="Details" value={newTicket.body} onChange={(e) => setNewTicket({ ...newTicket, body: e.target.value })} />
              <div className="flex gap-2">
                <select className="bg-slate-900 border border-slate-800 rounded px-2 py-2 text-sm" value={newTicket.priority} onChange={(e) => setNewTicket({ ...newTicket, priority: e.target.value })}>
                  <option value="low">low</option><option value="normal">normal</option><option value="high">high</option><option value="urgent">urgent</option>
                </select>
                <button className="bg-violet-600 px-3 py-2 rounded text-sm" onClick={async () => { await api(`/v1/tickets`, { method: "POST", body: JSON.stringify({ org_id: orgId, ...newTicket }) }); setNewTicket({ title: "", body: "", priority: "normal" }); load(); }}>Create ticket</button>
              </div>
            </div>
            {selTicket && (
              <Panel title={`#${selTicket.id} · ${selTicket.title}`} onClose={() => setSelTicket(null)}>
                <p className="text-sm text-slate-300 mb-3">{selTicket.body || "(no description)"}</p>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm mb-3">
                  <Field label="Status">
                    <select className={inputCls} value={selTicket.status} onChange={(e) => updateTicket({ status: e.target.value })}>
                      {["open", "in_progress", "pending", "resolved", "closed", "cancelled"].map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </Field>
                  <Field label="Priority">
                    <select className={inputCls} value={selTicket.priority} onChange={(e) => updateTicket({ priority: e.target.value })}>
                      {["low", "normal", "high", "urgent"].map((p) => <option key={p} value={p}>{p}</option>)}
                    </select>
                  </Field>
                  <Field label="Assignee">
                    <input className={inputCls} value={selTicket.assignee} onBlur={(e) => updateTicket({ assignee: e.target.value })} onChange={() => {}} />
                  </Field>
                  <div><span className="text-slate-500">SLA due</span><div className="text-sm">{isBreached(selTicket) ? <span className="text-red-400">breached · {selTicket.due_at}</span> : (selTicket.due_at || "—")}</div></div>
                </div>
                <div className="mb-3">
                  <h3 className="text-xs text-slate-400 mb-1">Comments</h3>
                  <div className="space-y-2 max-h-48 overflow-auto">
                    {comments.length === 0 && <p className="text-xs text-slate-500">No comments.</p>}
                    {comments.map((c) => (
                      <div key={c.id} className="text-sm bg-slate-950 border border-slate-800 rounded p-2">
                        <div className="text-xs text-slate-500">{c.author || "unknown"} · {c.created_at}</div>
                        <div>{c.body}</div>
                      </div>
                    ))}
                  </div>
                  <div className="flex gap-2 mt-2">
                    <input className={inputCls} placeholder="Add a comment…" value={commentText} onChange={(e) => setCommentText(e.target.value)} />
                    <button className="bg-violet-600 px-3 py-2 rounded text-sm" onClick={addComment}>Post</button>
                  </div>
                </div>
                {["open", "in_progress", "pending"].includes(selTicket.status) && (
                  <button className="text-xs text-violet-400 hover:underline" onClick={async () => { await api(`/v1/tickets/${selTicket.id}/close`, { method: "POST", body: "{}" }); openTicket(selTicket.id); load(); }}>Close ticket</button>
                )}
              </Panel>
            )}
            <Table head={["ID", "Title", "Status", "Sev", "Priority", "SLA due", "Actions"]}>
              {tickets.map((t) => (
                <tr key={t.id}>
                  <td className="px-4 py-3 text-slate-500">#{t.id}</td>
                  <td className="px-4 py-3 cursor-pointer hover:text-violet-300" onClick={() => openTicket(t.id)}>
                    <div className="font-medium">{t.title}</div><div className="text-xs text-slate-500">{t.body}</div>
                  </td>
                  <td className="px-4 py-3">{t.status}</td>
                  <td className="px-4 py-3"><HealthPill status={t.severity} /></td>
                  <td className="px-4 py-3">{t.priority}</td>
                  <td className="px-4 py-3 text-xs">{t.due_at ? (isBreached(t) ? <span className="text-red-400">breached · {t.due_at}</span> : <span className="text-slate-500">{t.due_at}</span>) : "—"}</td>
                  <td className="px-4 py-3 flex gap-2 text-xs">
                    {t.status === "open" && <button className="text-sky-400 hover:underline" onClick={async () => { await api(`/v1/tickets/${t.id}`, { method: "PATCH", body: JSON.stringify({ status: "in_progress" }) }); load(); }}>Start</button>}
                    {["open", "in_progress", "pending"].includes(t.status) && <button className="text-violet-400 hover:underline" onClick={async () => { await api(`/v1/tickets/${t.id}/close`, { method: "POST", body: "{}" }); load(); }}>Close</button>}
                  </td>
                </tr>
              ))}
            </Table>
          </>
        )}

        {view === "monitor" && (
          <>
            <div className="flex flex-wrap gap-2 items-end">
              <Field label="Device">
                <select className={inputCls} value={newCheck.device_id} onChange={(e) => setNewCheck({ ...newCheck, device_id: e.target.value })}>
                  <option value="">— select device —</option>
                  {devices.map((d) => <option key={d.id} value={d.id}>{d.hostname}</option>)}
                </select>
              </Field>
              <Field label="Kind">
                <select className={inputCls} value={newCheck.kind} onChange={(e) => setNewCheck({ ...newCheck, kind: e.target.value })}>
                  <option value="port">port</option><option value="http">http</option><option value="ping">ping</option><option value="snmp">snmp</option>
                </select>
              </Field>
              <Field label="Target (host:port or URL)">
                <input className={inputCls} placeholder="10.0.0.1:443" value={newCheck.target} onChange={(e) => setNewCheck({ ...newCheck, target: e.target.value })} />
              </Field>
              <Field label="Threshold (ms)">
                <input className={inputCls} placeholder="2000" value={newCheck.threshold_ms} onChange={(e) => setNewCheck({ ...newCheck, threshold_ms: e.target.value })} />
              </Field>
              <button className="bg-violet-600 px-3 py-2 rounded text-sm" onClick={async () => {
                await api(`/v1/monitor`, { method: "POST", body: JSON.stringify({ org_id: orgId, device_id: Number(newCheck.device_id), kind: newCheck.kind, target: newCheck.target, status: "ok", latency_ms: 0, threshold_ms: Number(newCheck.threshold_ms || 0) }) });
                load();
              }}>Add check</button>
              <button className="bg-sky-600 px-3 py-2 rounded text-sm" onClick={runChecks}>Run checks for all devices</button>
            </div>
            <div className="grid md:grid-cols-2 gap-4">
              <div className="card p-4">
                <h2 className="font-semibold mb-2">Checks</h2>
                {monitor.slice(0, 20).map((m) => <p key={m.id} className="text-xs py-1">{m.kind} · device {m.device_id} · {m.target || "—"} · <HealthPill status={m.status} /> · {Number(m.latency_ms).toFixed(1)}ms{Number(m.threshold_ms) > 0 ? ` / ${Number(m.threshold_ms)}ms` : ""}</p>)}
                {monitor.length === 0 && <p className="text-sm text-slate-500">No checks yet.</p>}
              </div>
              <div className="card p-4">
                <h2 className="font-semibold mb-2">Alerts</h2>
                {alerts.map((a) => (
                  <div key={a.id} className="text-xs py-1 flex justify-between">
                    <span><HealthPill status={a.severity} /> · {a.kind} · {a.message?.slice(0, 80)}</span>
                    {!a.acked && <button className="text-sky-400" onClick={async () => { await api(`/v1/monitor/alerts/${a.id}/ack`, { method: "POST", body: "{}" }); load(); }}>ACK</button>}
                  </div>
                ))}
                {alerts.length === 0 && <p className="text-sm text-slate-500">No alerts.</p>}
              </div>
              <div className="card p-4">
                <h2 className="font-semibold mb-2">Anomalies</h2>
                {anomalies.map((a) => (
                  <div key={a.id} className="text-xs py-1 border-b border-slate-800 flex justify-between items-center gap-2">
                    <span><HealthPill status={a.severity || "elevated"} /> · {a.kind || "anomaly"} · {a.target || a.device_id || "system"}</span>
                    <span className="text-slate-500">{a.score || 0}/100</span>
                  </div>
                ))}
                {anomalies.length === 0 && <p className="text-sm text-slate-500">No anomalies detected.</p>}
              </div>
            </div>
          </>
        )}

        {view === "scripts" && (
          <>
            <div className="grid md:grid-cols-3 gap-2">
              <input className="bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm" placeholder="name e.g. disk-check" value={newScript.name} onChange={(e) => setNewScript({ ...newScript, name: e.target.value })} />
              <input className="bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm" placeholder="body e.g. echo ok" value={newScript.body} onChange={(e) => setNewScript({ ...newScript, body: e.target.value })} />
              <button className="bg-violet-600 px-3 py-2 rounded text-sm" onClick={async () => { await api(`/v1/scripts`, { method: "POST", body: JSON.stringify({ org_id: orgId, ...newScript }) }); setNewScript({ name: "", body: "echo ok", version: "1.0.0" }); load(); }}>Create script</button>
            </div>
            {selScript && (
              <Panel title={`Script · ${selScript.name} (v${selScript.version})`} onClose={() => setSelScript(null)}>
                <pre className="text-xs bg-slate-950 border border-slate-800 rounded p-3 mb-3 overflow-auto max-h-40">{selScript.body}</pre>
                <div className="mb-2 flex gap-2">
                  <span className="text-xs text-slate-400">Run on:</span>
                  <select className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs" onChange={(e) => e.target.value && queueRun(selScript.id, Number(e.target.value))} defaultValue="">
                    <option value="">choose device…</option>
                    {devices.map((d) => <option key={d.id} value={d.id}>{d.hostname}</option>)}
                  </select>
                </div>
                <h3 className="text-xs text-slate-400 mb-1">Run history</h3>
                {runs.length === 0 ? <p className="text-xs text-slate-500">No runs yet.</p> : (
                  <ul className="text-xs divide-y divide-slate-800">
                    {runs.slice(0, 20).map((r) => (
                      <li key={r.id} className="py-1 flex justify-between">
                        <span>run #{r.id} · device {r.device_id} · {r.status} {r.exit_code != null ? `exit ${r.exit_code}` : ""}</span>
                        <button className="text-sky-400 hover:underline" onClick={() => viewRun(r.id)}>view output</button>
                      </li>
                    ))}
                  </ul>
                )}
                {runOutput && <pre className="text-xs bg-slate-950 border border-slate-800 rounded p-3 mt-2 overflow-auto max-h-40">{runOutput}</pre>}
              </Panel>
            )}
            <Table head={["ID", "Name", "Version", "Actions"]}>
              {scripts.map((s) => (
                <tr key={s.id}>
                  <td className="px-4 py-3 text-slate-500">#{s.id}</td>
                  <td className="px-4 py-3 cursor-pointer hover:text-violet-300" onClick={() => openScript(s.id)}>{s.name}</td>
                  <td className="px-4 py-3">{s.version}</td>
                  <td className="px-4 py-3">
                    {devices[0] ? <button className="text-violet-400 text-xs hover:underline" onClick={() => queueRun(s.id, devices[0].id)}>Queue → {devices[0].hostname}</button> : <span className="text-xs text-slate-500">register a device first</span>}
                  </td>
                </tr>
              ))}
            </Table>
            <p className="text-xs text-slate-500">Agent (`apps/agent`) polls <code>/v1/scripts/runs/pending</code> every 15s and completes runs — every exec is proof-logged.</p>
          </>
        )}

        {view === "automations" && (
          <>
            <div className="grid md:grid-cols-5 gap-2">
              <input className="bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm" placeholder="name" value={newAutomation.name} onChange={(e) => setNewAutomation({ ...newAutomation, name: e.target.value })} />
              <select className="bg-slate-900 border border-slate-800 rounded px-2 py-2 text-sm" value={newAutomation.trigger} onChange={(e) => setNewAutomation({ ...newAutomation, trigger: e.target.value })}>
                <option value="ticket.opened">ticket.opened</option><option value="ticket.closed">ticket.closed</option><option value="device.offline">device.offline</option>
              </select>
              <select className="bg-slate-900 border border-slate-800 rounded px-2 py-2 text-sm" value={newAutomation.action} onChange={(e) => setNewAutomation({ ...newAutomation, action: e.target.value })}>
                <option value="notify">notify</option><option value="alert">alert</option><option value="remediate">remediate</option>
              </select>
              {newAutomation.action === "remediate" && (
                <>
                  <select className="bg-slate-900 border border-slate-800 rounded px-2 py-2 text-sm" value={newAutomation.autonomy} onChange={(e) => setNewAutomation({ ...newAutomation, autonomy: e.target.value })}>
                    <option value="manual">manual (escalate)</option><option value="semi">semi (approve)</option><option value="auto">auto</option>
                  </select>
                  <select className="bg-slate-900 border border-slate-800 rounded px-2 py-2 text-sm" value={newAutomation.remediation_script_id} onChange={(e) => setNewAutomation({ ...newAutomation, remediation_script_id: e.target.value })}>
                    <option value="">— remediation script —</option>
                    {scripts.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                </>
              )}
              <input className="bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm" placeholder='condition JSON {"field":"priority","op":"eq","value":"urgent"}' value={newAutomation.condition} onChange={(e) => setNewAutomation({ ...newAutomation, condition: e.target.value })} />
              <button className="bg-violet-600 px-3 py-2 rounded text-sm" onClick={async () => {
                await api(`/v1/automations`, { method: "POST", body: JSON.stringify({ org_id: orgId, ...newAutomation, remediation_script_id: newAutomation.remediation_script_id ? Number(newAutomation.remediation_script_id) : null }) });
                setNewAutomation({ name: "", trigger: "ticket.opened", action: "notify", condition: "", autonomy: "semi", remediation_script_id: "" });
                load();
              }}>Create rule</button>
              <button className="bg-sky-600 px-3 py-2 rounded text-sm" onClick={async () => {
                const j = await api(`/v1/automations/simulate`, { method: "POST", body: JSON.stringify({ org_id: orgId, trigger: newAutomation.trigger || "ticket.opened", context: { priority: "urgent" } }) });
                setErr("Simulation: " + j.map((p) => `${p.name} → ${p.would_fire ? `${p.planned} (blast ${p.blast_radius}, safe path: ${p.safe_path})` : "not fired"}`).join(" | "));
              }}>Simulate</button>
            </div>
            <Table head={["ID", "Name", "Trigger", "Action", "Condition", "Enabled"]}>
              {automations.map((a) => (
                <tr key={a.id}>
                  <td className="px-4 py-3 text-slate-500">#{a.id}</td>
                  <td className="px-4 py-3 cursor-pointer hover:text-violet-300" onClick={() => setEditAuto(editAuto?.id === a.id ? null : a)}>{a.name}</td>
                  <td className="px-4 py-3">{a.trigger}</td>
                  <td className="px-4 py-3">{a.action}</td>
                  <td className="px-4 py-3 text-xs text-slate-400">{a.condition || "—"}</td>
                  <td className="px-4 py-3">
                    <button className="text-sky-400 text-xs" onClick={async () => { await api(`/v1/automations/${a.id}/toggle`, { method: "PATCH", body: "{}" }); load(); }}>{a.enabled ? "ON (disable)" : "OFF (enable)"}</button>
                  </td>
                </tr>
              ))}
            </Table>
            {editAuto && (
              <Panel title={`Edit automation #${editAuto.id}`} onClose={() => setEditAuto(null)}>
                <div className="grid md:grid-cols-4 gap-2">
                  <input className={inputCls} placeholder="name" value={editAuto.name} onChange={(e) => setEditAuto({ ...editAuto, name: e.target.value })} />
                  <input className={inputCls} placeholder="trigger" value={editAuto.trigger} onChange={(e) => setEditAuto({ ...editAuto, trigger: e.target.value })} />
                  <input className={inputCls} placeholder="action" value={editAuto.action} onChange={(e) => setEditAuto({ ...editAuto, action: e.target.value })} />
                  <input className={inputCls} placeholder="condition" value={editAuto.condition || ""} onChange={(e) => setEditAuto({ ...editAuto, condition: e.target.value })} />
                </div>
                <button className="mt-2 bg-violet-600 px-3 py-2 rounded text-sm" onClick={async () => { await api(`/v1/automations/${editAuto.id}`, { method: "PATCH", body: JSON.stringify(editAuto) }); setEditAuto(null); load(); }}>Save</button>
              </Panel>
            )}
          </>
        )}

        {view === "proof" && (
          <>
            {verifyResult && <p className="text-xs bg-slate-900 border border-slate-800 rounded p-3 break-all">{verifyResult}</p>}
            <Table head={["ID", "What", "Digest", "Actions"]}>
              {proofs.map((p) => (
                <tr key={p.id}>
                  <td className="px-4 py-3 font-mono text-xs">{p.id.slice(0, 12)}…</td>
                  <td className="px-4 py-3">{p.what}</td>
                  <td className="px-4 py-3 font-mono text-xs">{p.payload_digest.slice(0, 16)}…</td>
                  <td className="px-4 py-3 flex items-center gap-2">
                    <ProofBadge verified={null} />
                    <button onClick={() => verify(p.id)} className="text-violet-400 text-xs hover:underline">VERIFY</button>
                  </td>
                </tr>
              ))}
            </Table>
          </>
        )}

        {view === "ai" && (
          <div className="card p-4">
            <p className="text-sm text-slate-400">Copilot — device risk + ticket triage over live state (heuristic or OpenRouter/OmniRoute). Every query is proof-logged.</p>
            <div className="flex gap-2 mt-3">
              <input className="flex-1 bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm" value={aiQuery} onChange={(e) => setAiQuery(e.target.value)} placeholder="e.g. offline devices" />
              <button onClick={askAi} className="bg-violet-600 px-4 py-2 rounded text-sm font-semibold">Ask</button>
            </div>
            {aiResult?.thinking && <p className="mt-3 text-sm text-slate-500">thinking…</p>}
            {aiResult?.error && <p className="mt-3 text-sm text-red-400">{aiResult.error}</p>}
            {aiResult && !aiResult.thinking && !aiResult.error && (
              <div className="mt-3 space-y-3">
                <div className="bg-slate-950 border border-slate-800 rounded-lg p-3 text-sm whitespace-pre-wrap">{aiResult.answer || aiResult.summary || JSON.stringify(aiResult)}</div>
                <div className="text-xs text-slate-500">engine: {aiResult.engine || "?"} · model: {aiResult.model || "—"}</div>
                <details className="text-xs text-slate-500">
                  <summary className="cursor-pointer">View raw response</summary>
                  <pre className="mt-2 overflow-auto max-h-64 bg-slate-950 rounded p-3">{JSON.stringify(aiResult, null, 2)}</pre>
                </details>
              </div>
            )}
            <div className="border-t border-slate-800 mt-4 pt-4">
              <p className="text-sm text-slate-400">AI remediation — proposes an action; a human approves it in <button className="text-sky-400 underline" onClick={() => setView("admin")}>Admin → Approvals</button>.</p>
              <div className="flex gap-2 mt-2">
                <input className="flex-1 bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm" value={proposeQuery} onChange={(e) => setProposeQuery(e.target.value)} placeholder="e.g. disk cleanup / offline devices / apply updates" />
                <button className="bg-sky-600 px-4 py-2 rounded text-sm font-semibold" onClick={async () => {
                  try {
                    const j = await api(`/v1/ai/propose`, { method: "POST", body: JSON.stringify({ org_id: orgId, query: proposeQuery }) });
                    if (j.requires_approval) setErr(`AI proposed: ${j.proposed?.reason} — approval #${j.approval_id} awaiting human approval.`);
                    else setErr(j.reason || "No action proposed.");
                  } catch (e) { setErr(e.message); }
                }}>Propose</button>
              </div>
            </div>
          </div>
        )}

        {view === "admin" && (
          <>
            <section className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Stat label="Devices" value={devices.length} sub={`${devices.filter((d) => d.status !== "online").length} offline`} />
              <Stat label="Pending approvals" value={approvals.filter((a) => a.status === "pending").length} sub="human-gated" />
              <Stat label="Users" value={users.length} sub="org members" />
              <Stat label="Tickets" value={tickets.length} sub="total" />
              <Stat label="Kill switch" value={killSwitch ? (killSwitch.engaged ? "ENGAGED" : "off") : "—"} sub={killSwitch?.engaged ? "all automations frozen" : "normal ops"} />
            </section>
            <div className="grid md:grid-cols-2 gap-4">
              <div className="card p-4">
                <h2 className="font-semibold mb-2">Kill switch (global automation freeze)</h2>
                <p className="text-xs text-slate-500 mb-3">When engaged, all script runs and automation remediations are blocked. Engagement is proof-logged.</p>
                <button
                  onClick={async () => {
                    try {
                      await api("/v1/ops/kill-switch", { method: "POST", body: "{}" });
                      const ks = await api("/v1/ops/kill-switch");
                      setKillSwitch(ks);
                      setErr(ks.engaged ? "Kill switch ENGAGED — all automations frozen" : "Kill switch disengaged");
                    } catch (e) { setErr(e.message); }
                  }}
                  className={`w-full px-4 py-2 rounded-lg text-sm font-semibold ${killSwitch?.engaged ? "bg-red-600 hover:bg-red-500" : "bg-violet-600 hover:bg-violet-500"}`}
                >
                  {killSwitch?.engaged ? "Disengage kill switch" : "Engage kill switch"}
                </button>
                {killSwitch?.reason && <p className="text-xs text-slate-400 mt-2">Reason: {killSwitch.reason}</p>}
              </div>
              <div className="card p-4">
                <h2 className="font-semibold mb-2">Approvals (human-gated)</h2>
                {approvals.length === 0 && <p className="text-sm text-slate-500">No approvals yet — AI/automation proposals appear here.</p>}
                {approvals.map((a) => (
                  <div key={a.id} className="text-xs py-2 border-b border-slate-800 flex justify-between items-center gap-2">
                    <div>
                      <div className="font-medium">#{a.id} · {a.kind} · by {a.requester_kind}</div>
                      <div className="text-slate-500">{a.description}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`text-xs ${a.status === "pending" ? "text-amber-400" : a.status === "approved" ? "text-violet-400" : "text-red-400"}`}>{a.status}</span>
                      {a.status === "pending" && (<>
                        <button className="text-violet-400 hover:underline" onClick={async () => { await api(`/v1/approvals/${a.id}/approve`, { method: "POST", body: "{}" }); load(); }}>Approve</button>
                        <button className="text-red-400 hover:underline" onClick={async () => { await api(`/v1/approvals/${a.id}/deny`, { method: "POST", body: "{}" }); load(); }}>Deny</button>
                      </>)}
                    </div>
                  </div>
                ))}
              </div>
              <div className="card p-4">
                <h2 className="font-semibold mb-2">Users</h2>
                <div className="flex flex-wrap gap-2 mb-3">
                  <input className={inputCls} placeholder="email" value={newUser.email} onChange={(e) => setNewUser({ ...newUser, email: e.target.value })} />
                  <input className={inputCls} placeholder="password (min 8)" value={newUser.password} onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} />
                  <select className={inputCls} value={newUser.role} onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}>
                    {["admin", "manager", "engineer", "auditor", "viewer"].map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                  <button className="bg-violet-600 px-3 py-2 rounded text-sm" onClick={async () => { await api(`/v1/auth/users`, { method: "POST", body: JSON.stringify({ org_id: orgId, ...newUser }) }); setNewUser({ email: "", password: "", role: "engineer" }); load(); }}>Add user</button>
                </div>
                {users.map((u) => <div key={u.id} className="text-xs py-1 flex justify-between"><span>{u.email}</span><span className="text-slate-500">{u.role}</span></div>)}
                {users.length === 0 && <p className="text-sm text-slate-500">No users.</p>}
              </div>
            </div>
            <div className="card p-4">
              <h2 className="font-semibold mb-2">My sign-in password</h2>
              <p className="text-xs text-slate-500 mb-3">Set a local password after Google sign-in or workspace setup. Password sign-ins must provide the current password.</p>
              <div className="grid md:grid-cols-3 gap-2">
                <input type="password" autoComplete="current-password" className={inputCls} placeholder="Current password (if signing in with password)" value={passwordForm.current_password} onChange={(e) => setPasswordForm({ ...passwordForm, current_password: e.target.value })} />
                <input type="password" autoComplete="new-password" className={inputCls} placeholder="New password (12+ characters)" value={passwordForm.new_password} onChange={(e) => setPasswordForm({ ...passwordForm, new_password: e.target.value })} />
                <input type="password" autoComplete="new-password" className={inputCls} placeholder="Confirm new password" value={passwordForm.confirm_password} onChange={(e) => setPasswordForm({ ...passwordForm, confirm_password: e.target.value })} />
              </div>
              <button onClick={changePassword} className="mt-3 bg-violet-600 px-4 py-2 rounded-lg text-sm font-semibold">Update password</button>
              {passwordNotice && <p role="status" className="text-sm text-emerald-400 mt-2">{passwordNotice}</p>}
            </div>
            <div className="card p-4">
              <h2 className="font-semibold mb-2">Inventory by device type</h2>
              <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
                {["workstation", "server", "access_point", "gateway", "switch", "node"].map((t) => (
                  <div key={t} className="bg-slate-950 border border-slate-800 rounded-lg p-3 text-center">
                    <div className="text-2xl font-bold">{devices.filter((d) => d.device_type === t).length}</div>
                    <div className="text-xs text-slate-500">{t.replace("_", " ")}</div>
                  </div>
                ))}
              </div>
            </div>
            <div className="card p-4">
              <h2 className="font-semibold mb-2">Push notifications (Firebase FCM)</h2>
              <div className="flex flex-wrap gap-2 mb-3">
                <input className={inputCls} placeholder="FCM device token" value={pushToken} onChange={(e) => setPushToken(e.target.value)} />
                <button className="bg-violet-600 px-3 py-2 rounded text-sm" onClick={async () => {
                  if (!pushToken.trim()) return;
                  await api(`/v1/push/register`, { method: "POST", body: JSON.stringify({ org_id: orgId, user_id: users[0]?.id, fcm_token: pushToken.trim(), platform: "web" }) });
                  setPushToken("");
                  loadPush();
                }}>Register token</button>
                <button className="bg-slate-700 px-3 py-2 rounded text-sm" onClick={async () => { try { setPushResult(await api(`/v1/push/test?org_id=${orgId}`, { method: "POST", body: "{}" })); } catch (e) { setPushResult({ error: e.message }); } }}>Send test push</button>
              </div>
              {pushTokens.map((t) => <div key={t.id} className="text-xs py-1 flex justify-between"><span className="break-all">{t.fcm_token.slice(0, 60)}…</span><span className="text-slate-500">{t.platform}</span></div>)}
              {pushTokens.length === 0 && <p className="text-sm text-slate-500">No device tokens registered. Register an FCM token to receive push alerts.</p>}
              {pushResult && <pre className="text-xs text-slate-400 mt-2 break-all">{JSON.stringify(pushResult, null, 2)}</pre>}
            </div>
          </>
        )}
        {view === "audit" && (
          <>
            <div className="flex flex-wrap gap-2 items-end">
              <Field label="Audit kind">
                <select className={inputCls} value={auditKind} onChange={(e) => setAuditKind(e.target.value)}>
                  {["security", "compliance", "governance", "full"].map((k) => <option key={k} value={k}>{k}</option>)}
                </select>
              </Field>
              <button className="bg-violet-600 px-4 py-2 rounded text-sm" onClick={async () => {
                try {
                  const j = await api(`/v1/audits/run?org_id=${orgId}&kind=${auditKind}`, { method: "POST", body: "{}" });
                  setAuditResult(j);
                  loadAudits();
                } catch (e) { setErr(e.message); }
              }}>Run audit</button>
            </div>
            {auditResult && (
              <Panel title={`Audit #${auditResult.audit.id} · score ${auditResult.score}/100`} onClose={() => setAuditResult(null)}>
                <p className="text-sm text-slate-300 mb-2">{auditResult.audit.summary}</p>
                <button className="text-xs text-sky-400 hover:underline mb-2" onClick={() => downloadPdf(auditResult.audit.id)}>Download PDF report</button>
                <Table head={["Category", "Severity", "Finding", "Detail"]}>
                  {auditResult.findings.map((f) => (
                    <tr key={f.id}>
                      <td className="px-4 py-2">{f.category}</td>
                      <td className="px-4 py-2"><HealthPill status={f.severity} /></td>
                      <td className="px-4 py-2">{f.title}</td>
                      <td className="px-4 py-2 text-xs text-slate-400">{f.detail}</td>
                    </tr>
                  ))}
                </Table>
              </Panel>
            )}
            <Table head={["ID", "Kind", "Score", "Date", "Report"]}>
              {audits.map((a) => (
                <tr key={a.id}>
                  <td className="px-4 py-3 text-slate-500">#{a.id}</td>
                  <td className="px-4 py-3">{a.kind}</td>
                  <td className="px-4 py-3">{a.score}</td>
                  <td className="px-4 py-3 text-xs text-slate-500">{a.created_at}</td>
                  <td className="px-4 py-3"><button className="text-sky-400 text-xs hover:underline" onClick={() => downloadPdf(a.id)}>PDF</button></td>
                </tr>
              ))}
            </Table>
          </>
        )}

        {view === "onboarding" && (
          <>
            <div className="flex items-center gap-3">
              <h2 className="font-semibold">Client onboarding</h2>
              <button className="bg-violet-600 px-3 py-2 rounded text-sm" onClick={async () => { await api(`/v1/onboarding/init?org_id=${orgId}`, { method: "POST", body: "{}" }); loadOnboarding(); }}>Init checklist</button>
            </div>
            <div className="bg-slate-900 border border-slate-800 rounded-xl divide-y divide-slate-800">
              {steps.map((s, i) => (
                <div key={s.id} className="px-4 py-3 flex items-start gap-3">
                  <button className={`mt-0.5 w-5 h-5 rounded border ${s.done ? "bg-violet-600 border-violet-500" : "border-slate-600"}`} onClick={async () => { await api(`/v1/onboarding/${s.id}/toggle`, { method: "POST", body: "{}" }); loadOnboarding(); }}>{s.done ? "✓" : ""}</button>
                  <div className="flex-1">
                    <div className={`text-sm font-medium ${s.done ? "line-through text-slate-500" : ""}`}>{i + 1}. {s.title}</div>
                    <div className="text-xs text-slate-500">{s.detail}</div>
                  </div>
                </div>
              ))}
              {steps.length === 0 && <p className="px-4 py-3 text-sm text-slate-500">No checklist yet — click "Init checklist".</p>}
            </div>
          </>
        )}

        {view === "consulting" && (
          <>
            <div className="grid md:grid-cols-2 gap-4">
              <div className="card p-4">
                <h2 className="font-semibold mb-3">Client profile</h2>
                <div className="grid grid-cols-2 gap-2">
                  <Field label="Contact name"><input className={inputCls} value={profileForm.contact_name} onChange={(e) => setProfileForm({ ...profileForm, contact_name: e.target.value })} /></Field>
                  <Field label="Email"><input className={inputCls} value={profileForm.contact_email} onChange={(e) => setProfileForm({ ...profileForm, contact_email: e.target.value })} /></Field>
                  <Field label="Phone"><input className={inputCls} value={profileForm.phone} onChange={(e) => setProfileForm({ ...profileForm, phone: e.target.value })} /></Field>
                  <Field label="Industry"><input className={inputCls} value={profileForm.industry} onChange={(e) => setProfileForm({ ...profileForm, industry: e.target.value })} /></Field>
                  <Field label="Status">
                    <select className={inputCls} value={profileForm.status} onChange={(e) => setProfileForm({ ...profileForm, status: e.target.value })}>
                      {["prospect", "active", "onboarded", "churned"].map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </Field>
                  <Field label="Notes"><input className={inputCls} value={profileForm.notes} onChange={(e) => setProfileForm({ ...profileForm, notes: e.target.value })} /></Field>
                </div>
                <button className="mt-2 bg-violet-600 px-3 py-2 rounded text-sm" onClick={async () => { await api(`/v1/consulting/profile?org_id=${orgId}`, { method: "POST", body: JSON.stringify(profileForm) }); setErr("Profile saved."); }}>Save profile</button>
              </div>
              <div className="card p-4">
                <h2 className="font-semibold mb-3">New project</h2>
                <Field label="Name"><input className={inputCls} value={newProject.name} onChange={(e) => setNewProject({ ...newProject, name: e.target.value })} /></Field>
                <Field label="Description"><input className={inputCls} value={newProject.description} onChange={(e) => setNewProject({ ...newProject, description: e.target.value })} /></Field>
                <Field label="Status">
                  <select className={inputCls} value={newProject.status} onChange={(e) => setNewProject({ ...newProject, status: e.target.value })}>
                    {["planning", "active", "on_hold", "done"].map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
                  </select>
                </Field>
                <button className="mt-2 bg-violet-600 px-3 py-2 rounded text-sm" onClick={async () => { await api(`/v1/consulting/projects`, { method: "POST", body: JSON.stringify({ org_id: orgId, ...newProject }) }); setNewProject({ name: "", description: "", status: "planning" }); loadConsulting(); }}>Create project</button>
              </div>
            </div>
            <Table head={["ID", "Project", "Status", "Description"]}>
              {projects.map((p) => (
                <tr key={p.id}>
                  <td className="px-4 py-3 text-slate-500">#{p.id}</td>
                  <td className="px-4 py-3">{p.name}</td>
                  <td className="px-4 py-3"><HealthPill status={p.status} /></td>
                  <td className="px-4 py-3 text-xs text-slate-400">{p.description}</td>
                </tr>
              ))}
            </Table>
          </>
        )}
        {view === "cmdb" && (
          <>
            <div className="grid md:grid-cols-4 gap-2">
              <input className={inputCls} placeholder="name" value={newCi.name} onChange={(e) => setNewCi({ ...newCi, name: e.target.value })} />
              <select className={inputCls} value={newCi.ci_type} onChange={(e) => setNewCi({ ...newCi, ci_type: e.target.value })}>
                {["server", "switch", "application", "service", "database", "network", "other"].map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <input className={inputCls} placeholder='attributes JSON e.g. {"location":"DC1"}' value={newCi.attributes} onChange={(e) => setNewCi({ ...newCi, attributes: e.target.value })} />
              <button className="bg-violet-600 px-3 py-2 rounded text-sm" onClick={async () => { await api(`/v1/cmdb`, { method: "POST", body: JSON.stringify({ org_id: orgId, ...newCi }) }); setNewCi({ name: "", ci_type: "server", status: "operational", description: "", attributes: "{}" }); loadCmdb(); }}>Add CI</button>
            </div>
            <Table head={["ID", "Name", "Type", "Status", "Description"]}>
              {cis.map((c) => (
                <tr key={c.id}>
                  <td className="px-4 py-3 text-slate-500">#{c.id}</td>
                  <td className="px-4 py-3">{c.name}</td>
                  <td className="px-4 py-3">{c.ci_type}</td>
                  <td className="px-4 py-3"><HealthPill status={c.status} /></td>
                  <td className="px-4 py-3 text-xs text-slate-400">{c.description}</td>
                </tr>
              ))}
            </Table>
          </>
        )}

        {view === "knowledge" && (
          <>
            <div className="grid md:grid-cols-4 gap-2">
              <input className={inputCls} placeholder="Search title/body/tags" value={kbSearch} onChange={(e) => setKbSearch(e.target.value)} onKeyDown={(e) => e.key === "Enter" && loadKb()} />
              <input className={inputCls} placeholder="title" value={newArticle.title} onChange={(e) => setNewArticle({ ...newArticle, title: e.target.value })} />
              <input className={inputCls} placeholder="category" value={newArticle.category} onChange={(e) => setNewArticle({ ...newArticle, category: e.target.value })} />
              <button className="bg-violet-600 px-3 py-2 rounded text-sm" onClick={async () => { await api(`/v1/knowledge`, { method: "POST", body: JSON.stringify({ org_id: orgId, ...newArticle }) }); setNewArticle({ title: "", body: "", category: "general", tags: "" }); loadKb(); }}>Add article</button>
            </div>
            {articles.map((a) => (
              <details key={a.id} className="card p-4">
                <summary className="cursor-pointer font-medium">{a.title} <span className="text-xs text-slate-500">· {a.category}</span></summary>
                <p className="text-sm text-slate-300 mt-2 whitespace-pre-wrap">{a.body}</p>
                {a.tags && <p className="text-xs text-slate-500 mt-1">{a.tags}</p>}
              </details>
            ))}
          </>
        )}

        {view === "vault" && (
          <>
            <div className="grid md:grid-cols-4 gap-2">
              <input className={inputCls} placeholder="name" value={newSecret.name} onChange={(e) => setNewSecret({ ...newSecret, name: e.target.value })} />
              <input className={inputCls} placeholder="value" value={newSecret.value} onChange={(e) => setNewSecret({ ...newSecret, value: e.target.value })} />
              <input className={inputCls} placeholder="category" value={newSecret.category} onChange={(e) => setNewSecret({ ...newSecret, category: e.target.value })} />
              <button className="bg-violet-600 px-3 py-2 rounded text-sm" onClick={async () => { await api(`/v1/secrets`, { method: "POST", body: JSON.stringify({ org_id: orgId, ...newSecret }) }); setNewSecret({ name: "", value: "", category: "general", notes: "" }); loadVault(); }}>Store secret</button>
            </div>
            {revealed && (
              <Panel title={`Revealed · ${revealed.name}`} onClose={() => setRevealed(null)}>
                <pre className="text-xs bg-slate-950 border border-slate-800 rounded p-3 overflow-auto">{revealed.value}</pre>
                <p className="text-xs text-slate-500 mt-1">Reveal is audited (proof-logged).</p>
              </Panel>
            )}
            <Table head={["ID", "Name", "Category", "Notes", "Action"]}>
              {secrets.map((s) => (
                <tr key={s.id}>
                  <td className="px-4 py-3 text-slate-500">#{s.id}</td>
                  <td className="px-4 py-3">{s.name}</td>
                  <td className="px-4 py-3">{s.category}</td>
                  <td className="px-4 py-3 text-xs text-slate-400">{s.notes}</td>
                  <td className="px-4 py-3"><button className="text-sky-400 text-xs hover:underline" onClick={async () => { const j = await api(`/v1/secrets/${s.id}/reveal`, { method: "POST", body: "{}" }); setRevealed(j); }}>Reveal</button></td>
                </tr>
              ))}
            </Table>
          </>
        )}

        {view === "changes" && (
          <>
            <div className="grid md:grid-cols-5 gap-2">
              <input className={inputCls} placeholder="title" value={newChange.title} onChange={(e) => setNewChange({ ...newChange, title: e.target.value })} />
              <select className={inputCls} value={newChange.risk} onChange={(e) => setNewChange({ ...newChange, risk: e.target.value })}>{["low", "medium", "high"].map((r) => <option key={r} value={r}>{r}</option>)}</select>
              <select className={inputCls} value={newChange.impact} onChange={(e) => setNewChange({ ...newChange, impact: e.target.value })}>{["low", "medium", "high"].map((r) => <option key={r} value={r}>{r}</option>)}</select>
              <input className={inputCls} placeholder="plan" value={newChange.plan} onChange={(e) => setNewChange({ ...newChange, plan: e.target.value })} />
              <button className="bg-violet-600 px-3 py-2 rounded text-sm" onClick={async () => { await api(`/v1/changes`, { method: "POST", body: JSON.stringify({ org_id: orgId, ...newChange }) }); setNewChange({ title: "", description: "", risk: "medium", impact: "medium", plan: "" }); loadChanges(); }}>Create change</button>
            </div>
            <Table head={["ID", "Title", "Risk", "Impact", "Status", "Actions"]}>
              {changes.map((c) => (
                <tr key={c.id}>
                  <td className="px-4 py-3 text-slate-500">#{c.id}</td>
                  <td className="px-4 py-3">{c.title}</td>
                  <td className="px-4 py-3">{c.risk}</td>
                  <td className="px-4 py-3">{c.impact}</td>
                  <td className="px-4 py-3"><HealthPill status={c.status} /></td>
                  <td className="px-4 py-3 flex gap-2 text-xs">
                    {c.status === "draft" && <button className="text-sky-400 hover:underline" onClick={async () => { await api(`/v1/changes/${c.id}`, { method: "PATCH", body: JSON.stringify({ status: "submitted" }) }); loadChanges(); }}>Submit</button>}
                    {c.status === "submitted" && <button className="text-violet-400 hover:underline" onClick={async () => { await api(`/v1/changes/${c.id}`, { method: "PATCH", body: JSON.stringify({ status: "approved" }) }); loadChanges(); }}>Approve</button>}
                    {c.status === "approved" && <button className="text-violet-400 hover:underline" onClick={async () => { await api(`/v1/changes/${c.id}`, { method: "PATCH", body: JSON.stringify({ status: "implemented" }) }); loadChanges(); }}>Mark implemented</button>}
                  </td>
                </tr>
              ))}
            </Table>
          </>
        )}

        {view === "time" && (
          <>
            <div className="flex flex-wrap gap-2 items-end">
              <Field label="Minutes"><input className={inputCls} value={newEntry.minutes} onChange={(e) => setNewEntry({ ...newEntry, minutes: e.target.value })} /></Field>
              <Field label="Notes"><input className={inputCls} value={newEntry.notes} onChange={(e) => setNewEntry({ ...newEntry, notes: e.target.value })} /></Field>
              <label className="text-xs text-slate-400 mb-2"><input type="checkbox" checked={newEntry.billable} onChange={(e) => setNewEntry({ ...newEntry, billable: e.target.checked })} /> Billable</label>
              <button className="bg-violet-600 px-3 py-2 rounded text-sm mb-2" onClick={async () => { await api(`/v1/time`, { method: "POST", body: JSON.stringify({ org_id: orgId, minutes: Number(newEntry.minutes), notes: newEntry.notes, billable: newEntry.billable }) }); setNewEntry({ minutes: "", notes: "", billable: true }); loadTime(); }}>Log time</button>
            </div>
            {timeSummary && <p className="text-sm text-slate-400">Total {timeSummary.total_hours}h · Billable {timeSummary.billable_hours}h · {timeSummary.entries} entries</p>}
            <Table head={["ID", "Minutes", "Notes", "Billable", "Date"]}>
              {entries.map((e) => (
                <tr key={e.id}>
                  <td className="px-4 py-3 text-slate-500">#{e.id}</td>
                  <td className="px-4 py-3">{e.minutes}</td>
                  <td className="px-4 py-3">{e.notes}</td>
                  <td className="px-4 py-3">{e.billable ? "yes" : "no"}</td>
                  <td className="px-4 py-3 text-xs text-slate-500">{e.created_at}</td>
                </tr>
              ))}
            </Table>
          </>
        )}
        {view === "itechsmart" && (
          <>
            <section className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {itsStatus && Object.entries(itsStatus).map(([k, v]) => (
                <div key={k} className="card p-4">
                  <p className="text-xs uppercase tracking-wide text-slate-400">{k.replace("_", " ")}</p>
                  <div className="mt-1"><HealthPill status={v.ok ? "online" : "offline"} /></div>
                  {v.body && v.body.service && <p className="text-xs text-slate-500 mt-1">{v.body.service}</p>}
                </div>
              ))}
            </section>
            {itsStatus === null && <p className="text-sm text-slate-500">iTechSmart services not reachable — check ITECHSMART_* URLs in .env.</p>}

            <div className="grid md:grid-cols-2 gap-4">
              <div className="card p-4">
                <h2 className="font-semibold mb-2">MCP tools ({itsTools?.count || 0})</h2>
                {itsTools?.tools?.slice(0, 12).map((t) => <div key={t} className="text-xs py-0.5 font-mono">{t}</div>)}
                {(!itsTools || !itsTools.tools?.length) && <p className="text-sm text-slate-500">No tools loaded.</p>}
              </div>
              <div className="card p-4">
                <h2 className="font-semibold mb-2">ProofLink Plus receipt chain</h2>
                {itsChain.map((r) => (
                  <div key={r.id} className="text-xs py-1 border-b border-slate-800">
                    <span className="font-mono">{r.id?.slice(0, 12)}…</span> · {r.category} · {r.action} → {r.outcome}
                  </div>
                ))}
                {itsChain.length === 0 && <p className="text-sm text-slate-500">No receipts.</p>}
              </div>
            </div>

            <div className="card p-4">
              <h2 className="font-semibold mb-2">Seal a ProofOS receipt on ProofLink Plus</h2>
              <p className="text-xs text-slate-500 mb-2">Bridges ProofOS → iTechSmart ProofLink Plus (write requires ITECHSMART_API_KEY).</p>
              <button className="bg-violet-600 px-3 py-2 rounded text-sm" onClick={async () => {
                if (!proofs[0]) { setErr("No ProofOS receipts yet."); return; }
                const j = await api(`/v1/itechsmart/seal`, { method: "POST", body: JSON.stringify({ proof_id: proofs[0].id }) });
                setErr("Seal result: " + JSON.stringify(j.result || j));
              }}>Seal latest proof</button>
            </div>
          </>
        )}
        {view === "vms" && (
          <>
            <div className="grid md:grid-cols-6 gap-2">
              <input className={inputCls} placeholder="VM name" value={newVm.name} onChange={(e) => setNewVm({ ...newVm, name: e.target.value })} />
              <select className={inputCls} value={newVm.host_id} onChange={(e) => setNewVm({ ...newVm, host_id: e.target.value })}>
                <option value="">— host —</option>
                {devices.map((d) => <option key={d.id} value={d.id}>{d.hostname}</option>)}
              </select>
              <select className={inputCls} value={newVm.hypervisor} onChange={(e) => setNewVm({ ...newVm, hypervisor: e.target.value })}>
                {["hyper-v", "libvirt", "vmware", "qemu", "other"].map((h) => <option key={h} value={h}>{h}</option>)}
              </select>
              <input className={inputCls} placeholder="vCPU" value={newVm.vcpu} onChange={(e) => setNewVm({ ...newVm, vcpu: e.target.value })} />
              <input className={inputCls} placeholder="memory MB" value={newVm.memory_mb} onChange={(e) => setNewVm({ ...newVm, memory_mb: e.target.value })} />
              <button className="bg-violet-600 px-3 py-2 rounded text-sm" onClick={async () => {
                await api(`/v1/vms`, { method: "POST", body: JSON.stringify({ org_id: orgId, ...newVm, host_id: Number(newVm.host_id), vcpu: Number(newVm.vcpu || 0), memory_mb: Number(newVm.memory_mb || 0) }) });
                setNewVm({ name: "", host_id: "", hypervisor: "hyper-v", vcpu: "", memory_mb: "" });
                loadVms();
              }}>Register VM</button>
            </div>
            <Table head={["ID", "Name", "Hypervisor", "State", "vCPU", "Mem", "Actions"]}>
              {vms.map((v) => (
                <tr key={v.id}>
                  <td className="px-4 py-3 text-slate-500">#{v.id}</td>
                  <td className="px-4 py-3">{v.name}</td>
                  <td className="px-4 py-3">{v.hypervisor}</td>
                  <td className="px-4 py-3"><HealthPill status={v.state} /></td>
                  <td className="px-4 py-3">{v.vcpu}</td>
                  <td className="px-4 py-3">{v.memory_mb}</td>
                  <td className="px-4 py-3 flex gap-2 text-xs">
                    <button className="text-violet-400 hover:underline" onClick={async () => { await api(`/v1/vms/${v.id}/start`, { method: "POST", body: "{}" }); loadVms(); }}>Start</button>
                    <button className="text-amber-400 hover:underline" onClick={async () => { await api(`/v1/vms/${v.id}/stop`, { method: "POST", body: "{}" }); loadVms(); }}>Stop</button>
                    <button className="text-sky-400 hover:underline" onClick={async () => { await api(`/v1/vms/${v.id}/restart`, { method: "POST", body: "{}" }); loadVms(); }}>Restart</button>
                  </td>
                </tr>
              ))}
            </Table>
          </>
        )}
        {view === "patches" && (
          <>
            <div className="grid md:grid-cols-5 gap-2">
              <input className={inputCls} placeholder="name e.g. openssl" value={newPatch.name} onChange={(e) => setNewPatch({ ...newPatch, name: e.target.value })} />
              <select className={inputCls} value={newPatch.device_id} onChange={(e) => setNewPatch({ ...newPatch, device_id: e.target.value })}>
                <option value="">— device —</option>
                {devices.map((d) => <option key={d.id} value={d.id}>{d.hostname}</option>)}
              </select>
              <select className={inputCls} value={newPatch.category} onChange={(e) => setNewPatch({ ...newPatch, category: e.target.value })}>
                {["os", "third_party", "security", "other"].map((c) => <option key={c} value={c}>{c.replace("_", " ")}</option>)}
              </select>
              <select className={inputCls} value={newPatch.severity} onChange={(e) => setNewPatch({ ...newPatch, severity: e.target.value })}>
                {["critical", "important", "moderate", "low"].map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <button className="bg-violet-600 px-3 py-2 rounded text-sm" onClick={async () => {
                await api(`/v1/patches`, { method: "POST", body: JSON.stringify({ org_id: orgId, ...newPatch, device_id: Number(newPatch.device_id) }) });
                setNewPatch({ name: "", device_id: "", category: "security", severity: "moderate", available_version: "" });
                loadPatches();
              }}>Register patch</button>
            </div>
            <Table head={["ID", "Name", "Category", "Severity", "Status", "Device", "Actions"]}>
              {patches.map((p) => (
                <tr key={p.id}>
                  <td className="px-4 py-3 text-slate-500">#{p.id}</td>
                  <td className="px-4 py-3">{p.name}</td>
                  <td className="px-4 py-3">{p.category}</td>
                  <td className="px-4 py-3"><HealthPill status={p.severity} /></td>
                  <td className="px-4 py-3">{p.status}</td>
                  <td className="px-4 py-3">{p.device_id}</td>
                  <td className="px-4 py-3"><button className="text-violet-400 text-xs hover:underline" onClick={async () => { await api(`/v1/patches/${p.id}/deploy`, { method: "POST", body: "{}" }); loadPatches(); }}>Deploy</button></td>
                </tr>
              ))}
            </Table>
          </>
        )}
            {view === "enclaves" && (
          <>
            <div className="grid md:grid-cols-2 gap-4">
              <div className="card p-4">
                <h2 className="font-semibold mb-3">Provision secure workspace</h2>
                <p className="text-xs text-slate-500 mb-3">Company-controlled encrypted enclave on any Mac/PC. Work data runs under IT policy + DLP; personal apps stay private (BYOD, no VDI).</p>
                <div className="grid gap-2">
                  <input className={inputCls} placeholder="Workspace name" value={newEnclave.name} onChange={(e) => setNewEnclave({ ...newEnclave, name: e.target.value })} />
                  <select className={inputCls} value={newEnclave.device_id} onChange={(e) => setNewEnclave({ ...newEnclave, device_id: e.target.value })}>
                    <option value="">— device —</option>
                    {devices.map((d) => <option key={d.id} value={d.id}>{d.hostname}</option>)}
                  </select>
                  <select className={inputCls} value={newEnclave.policy_id} onChange={(e) => setNewEnclave({ ...newEnclave, policy_id: e.target.value })}>
                    <option value="">— policy (optional) —</option>
                    {enclavePolicies.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select>
                  <button className="btn-primary px-3 py-2 rounded text-sm font-semibold" onClick={async () => {
                    const j = await api(`/v1/enclaves`, { method: "POST", body: JSON.stringify({ org_id: orgId, name: newEnclave.name, device_id: Number(newEnclave.device_id), policy_id: Number(newEnclave.policy_id) || null }) });
                    setEnclaveKey(j.enclave_key);
                    loadEnclaves();
                  }}>Provision workspace</button>
                  {enclaveKey && <div className="text-xs bg-slate-950 border border-slate-800 rounded p-2 break-all">Enclave key (shown once — store it with the agent): <code>{enclaveKey}</code></div>}
                </div>
              </div>
              <div className="card p-4">
                <h2 className="font-semibold mb-3">DLP scan</h2>
                <p className="text-xs text-slate-500 mb-3">Paste content to detect sensitive data (SSN, cards, API keys) before it leaves the enclave.</p>
                <input className={inputCls} placeholder="Paste content to scan…" value={dlpScan.text} onChange={(e) => setDlpScan({ ...dlpScan, text: e.target.value })} />
                <button className="btn-ghost px-3 py-2 rounded text-sm mt-2" onClick={async () => { setDlpScan({ ...dlpScan, result: await api(`/v1/enclaves/scan`, { method: "POST", body: JSON.stringify({ text: dlpScan.text }) }) }); }}>Scan</button>
                {dlpScan.result && <pre className="text-xs text-slate-400 mt-2 bg-slate-950 rounded p-2 break-all">{JSON.stringify(dlpScan.result, null, 2)}</pre>}
              </div>
            </div>
            <div className="card p-4">
              <h2 className="font-semibold mb-3">IT policies (DLP)</h2>
              <div className="grid md:grid-cols-4 gap-2">
                <input className={inputCls} placeholder="Policy name" value={newPolicy.name} onChange={(e) => setNewPolicy({ ...newPolicy, name: e.target.value })} />
                <input className={inputCls} placeholder='blocked apps JSON ["dropbox"]' value={newPolicy.blocked_apps} onChange={(e) => setNewPolicy({ ...newPolicy, blocked_apps: e.target.value })} />
                <input className={inputCls} placeholder='network allowlist JSON ["acme.com"]' value={newPolicy.network_allowlist} onChange={(e) => setNewPolicy({ ...newPolicy, network_allowlist: e.target.value })} />
                <button className="btn-primary px-3 py-2 rounded text-sm" onClick={async () => {
                  await api(`/v1/enclaves/policies`, { method: "POST", body: JSON.stringify({ ...newPolicy, allowed_apps: "[]", blocked_apps: newPolicy.blocked_apps || "[]", network_allowlist: newPolicy.network_allowlist || "[]", dlp_rules: "{}", clipboard_enabled: false, watermark_enabled: true, ai_governed: true }) });
                  setNewPolicy({ name: "", blocked_apps: "", network_allowlist: "" });
                  loadEnclaves();
                }}>Create policy</button>
              </div>
              <div className="mt-3 text-xs text-slate-400">
                {enclavePolicies.map((p) => <div key={p.id} className="py-1 flex justify-between"><span>{p.name}</span><span className="text-slate-500">apps {JSON.parse(p.blocked_apps || "[]").length} blocked · network {JSON.parse(p.network_allowlist || "[]").length} allow · AI {p.ai_governed ? "governed" : "open"}</span></div>)}
                {enclavePolicies.length === 0 && <p className="text-slate-500">No policies yet.</p>}
              </div>
            </div>
            <Table head={["ID", "Workspace", "Device", "Policy", "Status", "Actions"]}>
              {enclaves.map((e) => (
                <tr key={e.id}>
                  <td className="px-4 py-3 text-slate-500">#{e.id}</td>
                  <td className="px-4 py-3">{e.name}</td>
                  <td className="px-4 py-3">{e.device_id}</td>
                  <td className="px-4 py-3">{e.policy_id || "—"}</td>
                  <td className="px-4 py-3"><HealthPill status={e.status} /></td>
                  <td className="px-4 py-3 flex gap-2 text-xs">
                    {e.status !== "suspended" && <button className="text-amber-400 hover:underline" onClick={async () => { await api(`/v1/enclaves/${e.id}`, { method: "PATCH", body: JSON.stringify({ status: "suspended" }) }); loadEnclaves(); }}>Suspend</button>}
                    {e.status === "suspended" && <button className="text-emerald-400 hover:underline" onClick={async () => { await api(`/v1/enclaves/${e.id}`, { method: "PATCH", body: JSON.stringify({ status: "active" }) }); loadEnclaves(); }}>Resume</button>}
                  </td>
                </tr>
              ))}
            </Table>
          </>
        )}
      </main>
        </div>
      </div>
    </div>
  );
}
