from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_proofos.db")
os.environ.setdefault("JWT_SECRET", "test-secret-with-at-least-32-characters")
os.environ.setdefault("PROOF_SIGNING_SEED_HEX", "00" * 32)

import httpx

from app.services.llm import OpenAICompatClient, get_llm_client


def test_chat_uses_model_and_bearer():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["referer"] = request.headers.get("HTTP-Referer")
        captured["body"] = request.read().decode()
        return httpx.Response(200, json={"choices": [{"message": {"content": "  ok  "}}]})

    client = OpenAICompatClient(
        base_url="https://openrouter.ai/api/v1",
        api_key="secret",
        model="nvidia/nemotron-3-ultra-550b-a55b:free",
        provider="openrouter",
        extra_headers={"HTTP-Referer": "https://proofos.local", "X-Title": "ProofOS"},
        transport=httpx.MockTransport(handler),
    )
    out = client.chat([{"role": "user", "content": "hello"}])

    assert out == "ok"
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["auth"] == "Bearer secret"
    assert captured["referer"] == "https://proofos.local"
    assert '"model": "nvidia/nemotron-3-ultra-550b-a55b:free"' in captured["body"]


def test_models():
    handler = lambda request: httpx.Response(200, json={"data": [{"id": "nvidia/nemotron-3-ultra-550b-a55b:free"}]})
    client = OpenAICompatClient(base_url="https://openrouter.ai/api/v1", api_key="k", transport=httpx.MockTransport(handler))
    assert client.models() == [{"id": "nvidia/nemotron-3-ultra-550b-a55b:free"}]


def test_is_configured_requires_key():
    assert OpenAICompatClient(base_url="https://openrouter.ai/api/v1").is_configured() is False
    assert OpenAICompatClient(base_url="https://openrouter.ai/api/v1", api_key="k").is_configured() is True


def test_chat_surfaces_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "No auth credentials found"}})

    client = OpenAICompatClient(base_url="https://openrouter.ai/api/v1", api_key="bad", transport=httpx.MockTransport(handler))
    try:
        client.chat([{"role": "user", "content": "hi"}])
    except httpx.HTTPStatusError:
        return
    raise AssertionError("expected HTTPStatusError to propagate (caller falls back)")


def test_factory_heuristic_returns_none(monkeypatch):
    from types import SimpleNamespace

    import app.services.llm as llm_mod

    monkeypatch.setattr(llm_mod, "settings", SimpleNamespace(ai_provider="heuristic"))
    assert get_llm_client() is None


def test_factory_openrouter(monkeypatch):
    from types import SimpleNamespace

    import app.services.llm as llm_mod

    monkeypatch.setattr(
        llm_mod,
        "settings",
        SimpleNamespace(
            ai_provider="openrouter",
            openrouter_url="https://openrouter.ai/api/v1",
            openrouter_api_key="k",
            openrouter_model="nvidia/nemotron-3-ultra-550b-a55b:free",
            openrouter_referer="https://proofos.local",
        ),
    )
    c = get_llm_client()
    assert c is not None
    assert c.provider == "openrouter"
    assert c.base_url == "https://openrouter.ai/api/v1"
    assert c.model == "nvidia/nemotron-3-ultra-550b-a55b:free"


def test_factory_omniroute_appends_v1(monkeypatch):
    from types import SimpleNamespace

    import app.services.llm as llm_mod

    monkeypatch.setattr(
        llm_mod,
        "settings",
        SimpleNamespace(
            ai_provider="omniroute",
            omniroute_url="http://localhost:20128",
            omniroute_key="k",
            omniroute_model="auto",
        ),
    )
    c = get_llm_client()
    assert c is not None
    assert c.provider == "omniroute"
    assert c.base_url == "http://localhost:20128/v1"
