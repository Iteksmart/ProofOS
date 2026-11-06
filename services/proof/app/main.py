from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import check_db, get_db, init_db
from app.models import ProofRecord
from app.proof import emit, verify, verify_chain
from app.schemas import ProofEmitIn, ProofOut, ProofVerifyOut

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("proofos-proof")


@asynccontextmanager
async def lifespan(app: FastAPI):
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


@app.get("/health")
def health():
    if check_db():
        return {"ok": True, "service": "proofos-proof", "version": "1.0.0", "db": "ok"}
    return JSONResponse(
        status_code=503,
        content={"ok": False, "service": "proofos-proof", "version": "1.0.0", "db": "unreachable"},
    )


@app.get("/v1/proof", response_model=list[ProofOut])
def list_proofs(limit: int = Query(100, le=500), db: Session = Depends(get_db)):
    return db.query(ProofRecord).order_by(ProofRecord.created_at.desc()).limit(limit).all()


@app.get("/v1/proof/chain")
def chain(db: Session = Depends(get_db)):
    recs = db.query(ProofRecord).order_by(ProofRecord.created_at.asc()).limit(500).all()
    return verify_chain(recs)


@app.get("/v1/proof/verify/{rid}", response_model=ProofVerifyOut)
def verify_proof(rid: str, db: Session = Depends(get_db)):
    rec = db.query(ProofRecord).filter(ProofRecord.id == rid).first()
    if not rec:
        raise HTTPException(status_code=404, detail="receipt not found")
    return verify(rec)


@app.post("/v1/proof/emit", response_model=ProofOut, status_code=201)
def emit_proof(body: ProofEmitIn, db: Session = Depends(get_db)):
    return emit(db, body.what, body.payload, body.who, body.where, body.why)
