from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.security import get_current_user
from app.models.models import Article, Device, Ticket

router = APIRouter()


@router.get("")
def search(q: str = Query(min_length=2, max_length=100), db: Session = Depends(get_db), user=Depends(get_current_user)):
    pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    results = []
    for model, field, kind in ((Device, Device.hostname, "device"), (Ticket, Ticket.title, "ticket"), (Article, Article.title, "article")):
        rows = db.query(model).filter(model.org_id == user.org_id, field.ilike(pattern, escape="\\")).order_by(model.id.desc()).limit(8).all()
        results.extend({"id": r.id, "kind": kind, "title": r.hostname if kind == "device" else r.title,
            "detail": r.os if kind == "device" else r.status if kind == "ticket" else r.category} for r in rows)
    return results
