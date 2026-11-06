from __future__ import annotations

from pydantic import BaseModel


class ProofOut(BaseModel):
    id: str
    what: str
    canonical_bytes: str
    payload_digest: str
    prev_hash: str
    signature: str

    class Config:
        from_attributes = True


class ProofVerifyOut(BaseModel):
    id: str
    what: str = ""
    verified: bool
    checks: dict
    trust: dict


class ProofEmitIn(BaseModel):
    what: str = "note"
    payload: dict = {}
    who: dict = {}
    where: dict = {}
    why: dict = {}
