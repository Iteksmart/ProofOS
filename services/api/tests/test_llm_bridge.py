"""ProofOS AI via the iTechSmart bridge: no key needed, and answers are labelled by what REALLY served them."""
import httpx

from app.services.llm import OpenAICompatClient


def _client(handler):
    return OpenAICompatClient(base_url="http://bridge:8089/v1", api_key="", model="nvidia/nemotron-3.5-super-vl-120b-a12b",
                              provider="bridge", transport=httpx.MockTransport(handler))


def _reply(backend):
    return {"choices": [{"message": {"content": " hello "}}], "x_bridge": {"backend": backend, "served_by_nvidia": backend == "nvidia"}}


def test_bridge_is_configured_without_a_key_and_sends_no_auth_header():
    seen = {}

    def handler(req: httpx.Request):
        seen["auth"] = req.headers.get("authorization")
        seen["url"] = str(req.url)
        return httpx.Response(200, json=_reply("nvidia"))
    c = _client(handler)
    assert c.is_configured() is True
    assert c.chat([{"role": "user", "content": "hi"}]) == "hello"
    assert seen["auth"] is None and seen["url"] == "http://bridge:8089/v1/chat/completions"


def test_label_is_nemotron_only_when_nvidia_served_it():
    c = _client(lambda r: httpx.Response(200, json=_reply("nvidia")))
    c.chat([{"role": "user", "content": "hi"}])
    assert c.identity() == {"engine": "nemotron-via-bridge", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b"}


def test_fallback_answer_is_not_labelled_nemotron():
    c = _client(lambda r: httpx.Response(200, json=_reply("ollama")))
    c.chat([{"role": "user", "content": "hi"}])
    ident = c.identity()
    assert ident["engine"] == "bridge-fallback-ollama" and "not Nemotron" in ident["model"]


def test_other_providers_unchanged():
    c = OpenAICompatClient(base_url="http://x/v1", api_key="k", model="m", provider="omniroute")
    assert c.identity() == {"engine": "omniroute", "model": "m"}
    assert OpenAICompatClient(base_url="http://x/v1", api_key="", provider="omniroute").is_configured() is False   # keyless still NOT ok elsewhere
