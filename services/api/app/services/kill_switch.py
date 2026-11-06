"""Emergency execution kill switch (fail-closed)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.models import KillSwitch

settings = get_settings()


class KillSwitchEngaged(Exception):
    """Raised when the execution kill switch is engaged."""


def engaged(db: Session) -> bool:
    """True if execution is halted. Fail-closed: any read error returns True (halt)."""
    if settings.kill_switch:  # env override — immediate stop
        return True
    try:
        row = db.query(KillSwitch).filter(KillSwitch.id == 1).first()
        return bool(row.engaged) if row else False
    except Exception:
        return True


def require_disengaged(db: Session) -> None:
    if engaged(db):
        raise KillSwitchEngaged("execution kill switch engaged — agent actions are halted")
