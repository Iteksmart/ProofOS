# UI

Shared React components + design tokens + proof UI. Wired into `apps/web` as a
workspace dependency (`@proofos/ui`).

## Tokens (`src/tokens.js`)
- Dark-first: slate-950 surfaces, emerald proof actions, slate borders
- 4px spacing scale, 12px radius, 16px base font
- `tokens` object + `healthClass(status)` helper

## Components
- `ProofBadge` — `verified: true | false | null` + checks tooltip (null = unchecked, never "invalid")
- `HealthPill` — status pill (online/offline/stale/maintenance/ok/warning/critical)
- `DeviceCard` — hostname, OS/IP, CPU/Disk/Mem mini-grid
- `TicketRow` — id, title/body, status, priority

```jsx
import { ProofBadge, HealthPill, DeviceCard, TicketRow, tokens } from "@proofos/ui";
```

Consumed by `apps/web/src/App.jsx` (devices status pill + proof verify badge).
