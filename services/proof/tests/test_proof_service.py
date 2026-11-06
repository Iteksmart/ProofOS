from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_proof_ledger.db")
os.environ.setdefault("PROOF_SIGNING_SEED_HEX", "00" * 32)

from fastapi.testclient import TestClient  # noqa: E402


def test_proof_service():
    from app.db import Base, engine
    from app.main import app

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestClient(app) as c:
        r = c.get("/health")
        assert r.status_code == 200, r.text

        r = c.post("/v1/proof/emit", json={"what": "test.emit", "payload": {"a": 1}, "who": {"actor_type": "system"}})
        assert r.status_code == 201, r.text
        rid = r.json()["id"]

        r = c.get(f"/v1/proof/verify/{rid}")
        assert r.status_code == 200, r.text
        v = r.json()
        assert v["verified"] is True, v
        assert v["checks"]["signature_valid"] is True

        r = c.get("/v1/proof/chain")
        assert r.status_code == 200, r.text
        assert r.json()["chain_ok"] is True

    Base.metadata.drop_all(bind=engine)
