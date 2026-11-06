// Design tokens — dark-first, Atera-style slate surfaces with emerald proof accent.
export const tokens = {
  surface: "bg-slate-950 text-slate-100",
  card: "bg-slate-900 border border-slate-800",
  radius: "rounded-xl",
  accent: "text-emerald-400",
  danger: "text-red-400",
  warning: "text-amber-400",
  ok: "text-emerald-400",
  info: "text-sky-400",
  muted: "text-slate-500",
};

export const healthClass = (status) => {
  const map = {
    online: "text-emerald-400 bg-emerald-500/10 border-emerald-500/30",
    ok: "text-emerald-400 bg-emerald-500/10 border-emerald-500/30",
    offline: "text-red-400 bg-red-500/10 border-red-500/30",
    critical: "text-red-400 bg-red-500/10 border-red-500/30",
    stale: "text-amber-400 bg-amber-500/10 border-amber-500/30",
    warning: "text-amber-400 bg-amber-500/10 border-amber-500/30",
    maintenance: "text-sky-400 bg-sky-500/10 border-sky-500/30",
    unknown: "text-slate-400 bg-slate-800 border-slate-700",
  };
  return map[status] || map.unknown;
};
