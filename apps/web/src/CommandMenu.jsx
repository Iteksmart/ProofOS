import React, { useEffect, useRef, useState } from "react";

export default function CommandMenu({ pages, api, onSelect, onClose }) {
  const dialog = useRef(null);
  const input = useRef(null);
  const [query, setQuery] = useState("");
  const [records, setRecords] = useState([]);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(0);
  const [searching, setSearching] = useState(false);
  useEffect(() => { dialog.current.showModal(); input.current.focus(); }, []);
  useEffect(() => {
    let current = true;
    setSelected(0); setRecords([]); setError("");
    if (query.trim().length < 2) { setSearching(false); return; }
    setSearching(true);
    const timer = setTimeout(async () => {
      try { const result = await api(`/v1/search?q=${encodeURIComponent(query.trim())}`); if (current) setRecords(result); }
      catch { if (current) setError("Workspace search is unavailable. Page navigation still works."); }
      finally { if (current) setSearching(false); }
    }, 180);
    return () => { current = false; clearTimeout(timer); };
  }, [query]);
  const matches = pages.filter(([, label]) => label.toLowerCase().includes(query.toLowerCase())).slice(0, query ? 6 : 7);
  const results = [...matches.map(([id, label]) => ({ id, kind: "page", title: label, detail: "Navigate to page" })), ...records];
  return <dialog ref={dialog} className="command-dialog" aria-label="Search workspace" onCancel={(e) => { e.preventDefault(); onClose(); }} onClick={(e) => { if (e.target === dialog.current) onClose(); }}>
    <div className="command-input"><span aria-hidden="true">⌕</span><input ref={input} aria-label="Search pages and workspace records" placeholder="Search pages, devices, tickets, knowledge…" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); setSelected((s) => Math.min(s + 1, results.length - 1)); }
      if (e.key === "ArrowUp") { e.preventDefault(); setSelected((s) => Math.max(s - 1, 0)); }
      if (e.key === "Enter" && results[selected]) { e.preventDefault(); onSelect(results[selected]); }
    }} /><button aria-label="Close search" onClick={onClose}><kbd>Esc</kbd></button></div>
    <div className="command-results"><p>{query ? "Search results" : "Jump to"}</p>{results.map((r, i) => <button key={`${r.kind}-${r.id}`} className={selected === i ? "selected" : ""} onMouseEnter={() => setSelected(i)} onClick={() => onSelect(r)}><span className="command-type">{r.kind === "page" ? "↗" : r.kind === "device" ? "▣" : r.kind === "ticket" ? "#" : "▤"}</span><span><strong>{r.title}</strong><small>{r.detail}</small></span><span className="command-kind">{r.kind}</span></button>)}{!results.length && !searching && <div className="command-empty">No results. Try a device name, ticket title, or page.</div>}{searching && <p role="status">Searching workspace…</p>}{error && <p role="status">{error}</p>}</div><footer><span>↑ ↓ to navigate</span><span>↵ to open</span><span>Search is limited to your workspace</span></footer>
  </dialog>;
}
