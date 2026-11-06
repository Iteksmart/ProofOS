from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import Article
from app.schemas.schemas import ArticleCreate, ArticleOut

router = APIRouter()


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id:
        raise HTTPException(status_code=403, detail="org scope mismatch")


@router.get("", response_model=list[ArticleOut])
def list_articles(org_id: int, q: str | None = None, category: str | None = None, limit: int = Query(200, le=1000), db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    query = db.query(Article).filter(Article.org_id == org_id)
    if category:
        query = query.filter(Article.category == category)
    if q:
        like = f"%{q}%"
        query = query.filter((Article.title.ilike(like)) | (Article.body.ilike(like)) | (Article.tags.ilike(like)))
    return query.order_by(Article.updated_at.desc()).limit(limit).all()


@router.post("", response_model=ArticleOut, status_code=201)
def create_article(payload: ArticleCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, payload.org_id)
    a = Article(org_id=payload.org_id, title=payload.title, body=payload.body, category=payload.category, tags=payload.tags, published=payload.published)
    db.add(a)
    db.commit()
    db.refresh(a)
    emit(db, "kb.article.created", {"id": a.id, "title": a.title}, actor_of(user), {"org_id": payload.org_id}, {"reason": "knowledge base"})
    return a


@router.patch("/{aid}", response_model=ArticleOut)
def update_article(aid: int, payload: dict, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = db.query(Article).filter(Article.id == aid).first()
    if not a:
        raise HTTPException(status_code=404, detail="article not found")
    _scope(user, a.org_id)
    for field in ("title", "body", "category", "tags", "published"):
        if field in payload:
            setattr(a, field, payload[field])
    db.commit()
    db.refresh(a)
    return a
