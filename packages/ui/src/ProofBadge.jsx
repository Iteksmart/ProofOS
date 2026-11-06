import React from "react";

// verified: true | false | null (null = not checked — never conflate with "invalid").
export function ProofBadge({ verified, checks }) {
  const cls =
    verified === true
      ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/30"
      : verified === false
        ? "text-red-400 bg-red-500/10 border-red-500/30"
        : "text-slate-400 bg-slate-800 border-slate-700";
  const glyph = verified === true ? "✓" : verified === false ? "✗" : "?";
  const label = verified === true ? "verified" : verified === false ? "invalid" : "unchecked";
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border ${cls}`}
      title={checks ? JSON.stringify(checks) : ""}
    >
      {glyph} {label}
    </span>
  );
}
