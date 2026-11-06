import React from "react";

export function TicketRow({ ticket }) {
  const t = ticket || {};
  return (
    <div className="px-4 py-3 flex items-center gap-3">
      <span className="text-slate-500 text-xs">#{t.id}</span>
      <div className="flex-1 min-w-0">
        <div className="font-medium truncate">{t.title}</div>
        {t.body ? <div className="text-xs text-slate-500 truncate">{t.body}</div> : null}
      </div>
      <span className="text-xs text-slate-300">{t.status}</span>
      <span className="text-xs text-slate-400">{t.priority}</span>
    </div>
  );
}
