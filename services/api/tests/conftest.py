"""Shared fixtures. Environment must be set before the app is imported."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_proofos.db")
os.environ.setdefault("JWT_SECRET", "test-secret-with-at-least-32-characters")
os.environ.setdefault("PROOF_SIGNING_SEED_HEX", "00" * 32)

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from app.core.db import Base, engine

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    from app.main import app

    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def auth_client(client):
    r = client.post("/v1/auth/bootstrap", json={"name": "Test Org"})
    assert r.status_code == 201, r.text
    data = r.json()
    client.headers.update({"Authorization": f"Bearer {data['access_token']}"})
    return client, data["org"]["id"], data["access_token"]
