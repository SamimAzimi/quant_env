"""News recording, Today News, the tomorrow-preview ticker, and To Watch."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Asset, News, Tag
from ..schemas import NewsIn, NewsOut, NewsPatch

router = APIRouter(prefix="/api/news", tags=["news"])


def _utc_today() -> datetime:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


@router.post("", response_model=NewsOut, status_code=201)
def create_news(payload: NewsIn, db: Session = Depends(get_db)):
    news = News(title=payload.title.strip(), body=payload.body,
                to_watch=payload.to_watch)
    if payload.tag_ids:
        news.tags = db.query(Tag).filter(Tag.id.in_(payload.tag_ids)).all()
    if payload.effect_ids:
        news.effects = db.query(Asset).filter(Asset.id.in_(payload.effect_ids)).all()
    db.add(news)
    db.commit()
    return news


@router.get("/today", response_model=list[NewsOut])
def today_news(db: Session = Depends(get_db)):
    """News recorded today (UTC) — the Today News section."""
    start = _utc_today()
    return (
        db.query(News)
        .filter(News.created_at >= start)
        .order_by(News.created_at.desc())
        .all()
    )


@router.get("/yesterday", response_model=list[NewsOut])
def yesterday_news(db: Session = Depends(get_db)):
    """News recorded the previous UTC day — the scroll preview strip."""
    start = _utc_today() - timedelta(days=1)
    return (
        db.query(News)
        .filter(News.created_at >= start, News.created_at < _utc_today())
        .order_by(News.created_at.desc())
        .all()
    )


@router.get("/watch", response_model=list[NewsOut])
def watch_list(db: Session = Depends(get_db)):
    """Items flagged to-watch; they persist across days until switched off."""
    return (
        db.query(News)
        .filter(News.to_watch.is_(True))
        .order_by(News.created_at.desc())
        .all()
    )


@router.patch("/{news_id}", response_model=NewsOut)
def patch_news(news_id: int, payload: NewsPatch, db: Session = Depends(get_db)):
    news = db.get(News, news_id)
    if not news:
        raise HTTPException(404, "News not found")
    if payload.to_watch is not None:
        news.to_watch = payload.to_watch
    db.commit()
    return news
