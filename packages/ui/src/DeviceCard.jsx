import React from "react";
import { HealthPill } from "./HealthPill.jsx";

export function DeviceCard({ device }) {
  const d = device || {};
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-semibold truncate">{d.hostname}</h3>
        <HealthPill status={d.status} />
      </div>
      <p className="text-xs text-slate-500 mt-1">
        {d.os || "—"} · {d.ip || "—"}
      </p>
      <div className="grid grid-cols-3 gap-2 mt-3 text-center text-xs">
        {[
          ["CPU", d.cpu],
          ["Disk", d.disk],
          ["Mem", d.mem],
        ].map(([label, value]) => (
          <div key={label} className="bg-slate-950 border border-slate-800 rounded-lg py-2">
            <div className="text-slate-500">{label}</div>
            <div className="font-semibold mt-0.5">{Number(value || 0).toFixed(0)}%</div>
          </div>
        ))}
      </div>
    </div>
  );
}
