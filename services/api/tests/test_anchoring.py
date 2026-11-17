"""Independent RFC 3161 anchoring of the proof-chain head."""
from __future__ import annotations

import pytest

from app.services import anchoring
from tests.tsa_fixture import LocalTsa


@pytest.fixture()
def tsa(monkeypatch):
    local = LocalTsa()
    monkeypatch.setenv("PROOF_TSA_URLS", "https://tsa.test/tsr")
    monkeypatch.setenv("PROOF_TSA_TRUSTED_ROOTS", local.root_sha256)
    original = anchoring.request_token
    monkeypatch.setattr(anchoring, "request_token", lambda url, imprint, transport=None: original(url, imprint, local.transport()))
    return local


def test_anchor_verifies_and_detects_ledger_rewrite(auth_client, tsa):
    c, org_id, _ = auth_client
    c.post("/v1/devices", json={"org_id": org_id, "hostname": "anchor-host"})
    created = c.post("/v1/anchors")
    assert created.status_code == 201, created.text
    anchor = created.json()
    assert anchor["verification"]["verified"] is True
    assert all(anchor["verification"]["checks"].values())
    assert anchor["tsa_url"] == "https://tsa.test/tsr" and anchor["record_count"] >= 2

    token = c.get(f"/v1/anchors/{anchor['id']}/token")
    assert token.status_code == 200 and token.headers["content-type"] == "application/timestamp-reply"

    # Rewriting the anchored record is detected even though ProofOS's own signature could be re-made.
    from app.core.db import SessionLocal
    from app.models.models import ProofRecord
    with SessionLocal() as db:
        db.get(ProofRecord, anchor["last_record_id"]).payload_digest = "0" * 64
        db.commit()
    rewritten = c.get(f"/v1/anchors/{anchor['id']}").json()["verification"]
    assert rewritten["checks"]["head_still_in_ledger"] is False and rewritten["verified"] is False


def test_unchanged_head_is_not_reanchored_and_untrusted_root_fails(auth_client, tsa, monkeypatch):
    c, org_id, _ = auth_client
    from app.core.db import SessionLocal
    with SessionLocal() as db:
        first = anchoring.anchor_now(db)
        again = anchoring.anchor_now(db)
        assert first.id == again.id and tsa.requests == 1
    monkeypatch.setenv("PROOF_TSA_TRUSTED_ROOTS", "ab" * 32)
    listing = c.get("/v1/anchors").json()
    assert listing["anchors"][0]["verification"]["checks"]["root_trusted"] is False
    assert listing["anchors"][0]["verification"]["verified"] is False


def test_unreachable_authority_and_permissions(auth_client, monkeypatch):
    c, org_id, _ = auth_client
    monkeypatch.setenv("PROOF_TSA_URLS", "https://tsa.invalid/tsr")
    original = anchoring.request_token
    import httpx
    down = httpx.MockTransport(lambda request: httpx.Response(503))
    monkeypatch.setattr(anchoring, "request_token", lambda url, imprint, transport=None: original(url, imprint, down))
    assert c.post("/v1/anchors").status_code == 502
    c.post("/v1/auth/users", json={"org_id": org_id, "email": "viewer-anchor@proofos.dev", "password": "a-long-test-password", "role": "viewer"})
    token = c.post("/v1/auth/login", json={"email": "viewer-anchor@proofos.dev", "password": "a-long-test-password"}).json()["access_token"]
    assert c.post("/v1/anchors", headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert c.get("/v1/anchors", headers={"Authorization": f"Bearer {token}"}).status_code == 200
