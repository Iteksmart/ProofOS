from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class ProofRecord(Base):
    """Standalone ledger record. Uses its own table name so the extractable
    proof service never merges with the control-plane's embedded ledger."""

    __tablename__ = "proof_ledger_records"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    what: Mapped[str] = mapped_column(String(100), index=True)
    canonical_bytes: Mapped[str] = mapped_column(Text)
    payload_digest: Mapped[str] = mapped_column(String(64), index=True)
    prev_hash: Mapped[str] = mapped_column(String(64))
    signature: Mapped[str] = mapped_column(Text)
    signing_key_id: Mapped[str] = mapped_column(String(100), default="ed25519:proofos-1")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
