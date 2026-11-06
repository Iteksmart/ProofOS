from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import check_db, get_db, init_db
from app.models import ProofRecord
from app.proof import emit, record_org_id, verify, verify_chain
from app.schemas import ProofEmitIn, ProofOut, ProofVerifyOut

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("proofos-proof")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_production()
    init_db()
    log.info("ProofOS proof ledger ready db_ok=%s", check_db())
    yield


app = FastAPI(title="ProofOS Proof Ledger", version="1.0.0", docs_url="/docs", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def current_org_id(request: Request) -> int:
    from jose import JWTError, jwt

    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization: Bearer <token>")
    token = header.split(" ", 1)[1].strip()
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algo])
        org_id = int(claims["org_id"])
        if not claims.get("sub"):
            raise ValueError("missing subject")
        return org_id
    except (JWTError, KeyError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")


@app.get("/health")
def health():
    if check_db():
        return {"ok": True, "service": "proofos-proof", "version": "1.0.0", "db": "ok"}
    return JSONResponse(
        status_code=503,
        content={"ok": False, "service": "proofos-proof", "version": "1.0.0", "db": "unreachable"},
    )


@app.get("/v1/proof", response_model=list[ProofOut])
def list_proofs(limit: int = Query(100, le=500), org_id: int = Depends(current_org_id), db: Session = Depends(get_db)):
    rows = db.query(ProofRecord).order_by(ProofRecord.created_at.desc()).all()
    return [r for r in rows if record_org_id(r) == org_id][:limit]


@app.get("/v1/proof/chain")
def chain(org_id: int = Depends(current_org_id), db: Session = Depends(get_db)):
    rows = db.query(ProofRecord).order_by(ProofRecord.created_at.asc()).all()
    recs = [r for r in rows if record_org_id(r) == org_id][-500:]
    return verify_chain(recs)


@app.get("/v1/proof/verify/{rid}", response_model=ProofVerifyOut)
def verify_proof(rid: str, org_id: int = Depends(current_org_id), db: Session = Depends(get_db)):
    rec = db.query(ProofRecord).filter(ProofRecord.id == rid).first()
    if not rec or record_org_id(rec) != org_id:
        raise HTTPException(status_code=404, detail="receipt not found")
    return verify(rec)


@app.post("/v1/proof/emit", response_model=ProofOut, status_code=201)
def emit_proof(body: ProofEmitIn, org_id: int = Depends(current_org_id), db: Session = Depends(get_db)):
    return emit(db, org_id, body.what, body.payload, body.who, body.where, body.why)
