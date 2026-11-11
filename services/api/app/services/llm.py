"""Generic OpenAI-compatible LLM client + provider factory.

ProofOS's AI copilot can talk to any gateway that exposes OpenAI-style
`POST {base}/chat/completions` and `GET {base}/models`:

- **OmniRoute** (https://github.com/cheaper-inference/OmniRoute) — a local/free
  AI gateway; base URL is `OMNIROUTE_URL` (root), endpoint under `/v1`.
- **OpenRouter** (https://openrouter.ai) — a hosted OpenAI-compatible API with
  free-tier models (the `:free` suffix); base URL already includes `/api/v1`.

Selected by `AI_PROVIDER` (heuristic | omniroute | openrouter). When no backend
is configured or a call fails, `app/services/ai.py` falls back to the
deterministic heuristic engine.
"""
from __future__ import annotations

import httpx

from app.core.config import get_settings

settings = get_settings()

SYSTEM_PROMPT = (
    "You are the ProofOS AI copilot for an RMM / IT-operations platform. "
    "Answer concisely and only from the provided live state. Never invent devices, "
    "tickets, or metrics that are not present in the context. Propose actions but "
    "always require human approval before any change is applied."
)


class OpenAICompatClient:
    """Thin OpenAI-compatible chat client (OmniRoute, OpenRouter, and similar)."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        model: str = "auto",
        provider: str = "",
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        extra_headers: dict | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")  # full API base (already includes version path)
        self.api_key = api_key or ""
        self.model = model or "auto"
        self.provider = provider
        self.timeout = timeout
        self._transport = transport
        self.extra_headers = extra_headers or {}

    def is_configured(self) -> bool:
        # the bridge authenticates to NVIDIA itself, so it needs no key from us
        return bool(self.base_url) and (bool(self.api_key) or self.provider == "bridge")

    # which backend REALLY answered the last chat (bridge only: it silently falls back to other models when NVIDIA fails)
    last_backend: str | None = None

    def identity(self) -> dict:
        """engine/model labels for API answers - truthful about fallbacks."""
        if self.provider == "bridge":
            if self.last_backend == "nvidia":
                return {"engine": "nemotron-via-bridge", "model": self.model}
            return {"engine": f"bridge-fallback-{self.last_backend or 'unknown'}", "model": "unknown (the bridge used a fallback model, not Nemotron)"}
        return {"engine": self.provider, "model": self.model}

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        h.update(self.extra_headers)
        return h

    def chat(self, messages: list[dict], model: str | None = None) -> str:
        """Send a chat request and return the assistant's text. Raises on failure."""
        payload = {
            "model": model or self.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *messages],
        }
        with httpx.Client(transport=self._transport, timeout=self.timeout) as client:
            r = client.post(f"{self.base_url}/chat/completions", headers=self._headers(), json=payload)
            r.raise_for_status()
            data = r.json()
        if self.provider == "bridge":
            self.last_backend = (data.get("x_bridge") or {}).get("backend")
        return data["choices"][0]["message"]["content"].strip()

    def models(self) -> list[dict]:
        """List models the gateway can currently route to."""
        with httpx.Client(transport=self._transport, timeout=self.timeout) as client:
            r = client.get(f"{self.base_url}/models", headers=self._headers())
            r.raise_for_status()
            return r.json().get("data", [])


def get_llm_client() -> OpenAICompatClient | None:
    """Return the client for `AI_PROVIDER`, or None when disabled (heuristic)."""
    provider = settings.ai_provider.lower()
    if provider == "bridge":
        return OpenAICompatClient(
            base_url=f"{settings.ai_bridge_url.rstrip('/')}/v1",
            api_key="",
            model=settings.ai_bridge_model,
            provider="bridge",
            timeout=90.0,
        )
    if provider == "omniroute":
        return OpenAICompatClient(
            base_url=f"{settings.omniroute_url.rstrip('/')}/v1",
            api_key=settings.omniroute_key,
            model=settings.omniroute_model or "auto",
            provider="omniroute",
        )
    if provider == "openrouter":
        return OpenAICompatClient(
            base_url=settings.openrouter_url.rstrip("/"),
            api_key=settings.openrouter_api_key,
            model=settings.openrouter_model,
            provider="openrouter",
            extra_headers={"HTTP-Referer": settings.openrouter_referer, "X-Title": "ProofOS"},
        )
    return None
