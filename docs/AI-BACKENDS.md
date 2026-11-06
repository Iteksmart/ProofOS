# AI copilot backends

ProofOS's copilot (`/v1/ai/*`) supports three backends, selected by `AI_PROVIDER`:

| Mode | Setting | Behaviour |
|---|---|---|
| **heuristic** (default) | `AI_PROVIDER=heuristic` | Deterministic, offline, auditable rules. No external calls. |
| **openrouter** | `AI_PROVIDER=openrouter` | Hosted OpenAI-compatible API with **free-tier models** (`:free` suffix). |
| **omniroute** | `AI_PROVIDER=omniroute` | Local/free AI gateway ([OmniRoute](https://github.com/cheaper-inference/OmniRoute)), `model: auto`. |

Any LLM failure falls back to the heuristic engine and records a `fallback_reason`;
the request is still proof-logged. `/v1/ai/triage/{id}` stays deterministic in all
modes (auditable).

## OpenRouter — free models (zero cost)

1. Create a free API key at <https://openrouter.ai/keys> (free models need no
   payment method; they are rate-limited).
2. Configure `.env`:

   ```ini
   AI_PROVIDER=openrouter
   OPENROUTER_URL=https://openrouter.ai/api/v1
   OPENROUTER_API_KEY=<your-openrouter-key>
   OPENROUTER_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free   # any ":free" model
   OPENROUTER_REFERER=https://proofos.local
   ```

3. Restart the API. `/v1/ai/ask` now returns `"engine": "openrouter"`.

List free models (end in `:free`):

```powershell
curl -s https://openrouter.ai/api/v1/models -H "Authorization: Bearer YOUR_KEY" | Select-String ":free"
# or browse https://openrouter.ai/models?max_price=0
```

## OmniRoute — local/free gateway

1. Start OmniRoute (already wired into ProofOS compose as an opt-in profile):

   ```powershell
   docker compose -f infra/docker-compose.yml --profile ai up -d omniroute
   # or standalone:  npm install -g omniroute && omniroute
   # Dashboard: http://localhost:20128 · API: http://localhost:20128/v1
   ```

2. Connect a provider in the dashboard, copy your key from **Dashboard → Endpoints**.
3. Configure `.env`:

   ```ini
   AI_PROVIDER=omniroute
   OMNIROUTE_URL=http://localhost:20128   # http://omniroute:20128 inside compose
   OMNIROUTE_KEY=<your-omniroute-key>
   OMNIROUTE_MODEL=auto
   ```

## Verify

```powershell
curl -X POST http://localhost:8000/v1/ai/ask \
  -H "Authorization: Bearer <proofos-token>" -H "Content-Type: application/json" \
  -d '{"org_id":1,"query":"which devices are offline?"}'
```

Expect `"engine":"openrouter"` (or `"omniroute"`) with an `"answer"`. If the backend
is unreachable, the response carries `"engine":"heuristic"` and a `"fallback_reason"`
— the copilot never hard-fails.

See [OmniRoute's docs](https://github.com/cheaper-inference/OmniRoute) and
[OpenRouter's docs](https://openrouter.ai/docs) for terms, limits, and free-tier
eligibility.
