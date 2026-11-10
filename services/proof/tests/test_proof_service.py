from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_proof_ledger.db")
os.environ.setdefault("PROOF_SIGNING_SEED_HEX", "00" * 32)
os.environ.setdefault("JWT_SECRET", "proof-service-test-secret-at-least-32")

from fastapi.testclient import TestClient  # noqa: E402


def test_production_settings_reject_weak_database_and_wildcard_cors():
    import pytest

    from app.config import Settings

    bad = Settings(
        database_url="sqlite:///./proof.db",
        jwt_secret="s" * 40,
        proof_key_seed_hex="ab" * 32,
        api_env="production",
        api_cors_origins="*",
    )
    with pytest.raises(ValueError, match="PostgreSQL"):
        Settings(
            database_url="sqlite:///./proof.db",
            jwt_secret="s" * 40,
            proof_key_seed_hex="ab" * 32,
            api_env="production",
            api_cors_origins="https://proofos.example.com",
        ).validate_production()
    with pytest.raises(ValueError, match="wildcard"):
        bad.validate_production()

    good = Settings(
        database_url=f"postgresql+psycopg://proofos:{'c' * 64}@localhost/proofos",
        jwt_secret="s" * 40,
        proof_key_seed_hex="ab" * 32,
        api_env="production",
        api_cors_origins="https://proofos.example.com",
    )
    good.validate_production()

    bad_http_origin = Settings(
        database_url=f"postgresql+psycopg://proofos:{'c' * 64}@localhost/proofos",
        jwt_secret="s" * 40,
        proof_key_seed_hex="ab" * 32,
        api_env="production",
        api_cors_origins="http://proofos.example.com",
    )
    with pytest.raises(ValueError, match="HTTPS origin"):
        bad_http_origin.validate_production()


def test_proof_service():
    from app.db import Base, engine
    from app.main import app

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestClient(app) as c:
        import jwt

        from app.config import get_settings

        settings = get_settings()
        token_a = jwt.encode({"sub": "1", "org_id": 1}, settings.jwt_secret, algorithm=settings.jwt_algo)
        token_b = jwt.encode({"sub": "2", "org_id": 2}, settings.jwt_secret, algorithm=settings.jwt_algo)
        auth_a = {"Authorization": f"Bearer {token_a}"}
        auth_b = {"Authorization": f"Bearer {token_b}"}
        r = c.get("/health")
        assert r.status_code == 200, r.text

        assert c.get("/v1/proof").status_code == 401
        r = c.post("/v1/proof/emit", headers=auth_a, json={"what": "test.emit", "payload": {"a": 1}, "who": {"actor_type": "system"}})
        assert r.status_code == 201, r.text
        receipt_a = r.json()
        rid = receipt_a["id"]

        r = c.get(f"/v1/proof/verify/{rid}", headers=auth_a)
        assert r.status_code == 200, r.text
        v = r.json()
        assert v["verified"] is True, v
        assert v["checks"]["signature_valid"] is True

        r = c.get("/v1/proof/chain", headers=auth_a)
        assert r.status_code == 200, r.text
        assert r.json()["chain_ok"] is True

        other = c.post("/v1/proof/emit", headers=auth_b, json={"what": "other.emit", "payload": {"b": 2}})
        assert other.status_code == 201, other.text
        assert c.get("/v1/proof", headers=auth_a).json() == [receipt_a]
        assert c.get(f"/v1/proof/verify/{other.json()['id']}", headers=auth_a).status_code == 404
        assert c.get("/v1/proof/chain", headers=auth_a).json()["chain_ok"] is True

    Base.metadata.drop_all(bind=engine)
