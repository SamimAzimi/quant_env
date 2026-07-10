"""News recording, day views (as-of aware), history, and To Watch."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..dates import as_of_or_today, day_bounds, range_bounds
from ..db import get_db
from ..models import Asset, News, Tag
from ..schemas import NewsIn, NewsOut, NewsPatch

router = APIRouter(prefix="/api/news", tags=["news"])


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


def _on_day(db: Session, day: date) -> list[News]:
    start, end = day_bounds(day)
    return (
        db.query(News)
        .filter(News.created_at >= start, News.created_at < end)
        .order_by(News.created_at.desc())
        .all()
    )


@router.get("/today", response_model=list[NewsOut])
def today_news(date_: date | None = Query(None, alias="date"),
               db: Session = Depends(get_db)):
    """News recorded on the selected day (default: today, UTC)."""
    return _on_day(db, as_of_or_today(date_))


@router.get("/yesterday", response_model=list[NewsOut])
def yesterday_news(date_: date | None = Query(None, alias="date"),
                   db: Session = Depends(get_db)):
    """News recorded the day before the selected day — the preview ticker."""
    return _on_day(db, as_of_or_today(date_) - timedelta(days=1))


@router.get("/watch", response_model=list[NewsOut])
def watch_list(db: Session = Depends(get_db)):
    """Items flagged to-watch; they persist across days until switched off."""
    return (
        db.query(News)
        .filter(News.to_watch.is_(True))
        .order_by(News.created_at.desc())
        .all()
    )


@router.get("/history", response_model=list[NewsOut])
def history(start: date | None = None, end: date | None = None,
            tag_id: int | None = None, effect_id: int | None = None,
            db: Session = Depends(get_db)):
    """News over a date range, optionally filtered by tag and/or effect."""
    s, e = range_bounds(start, end)
    q = db.query(News).filter(News.created_at >= s, News.created_at < e)
    if tag_id is not None:
        q = q.filter(News.tags.any(Tag.id == tag_id))
    if effect_id is not None:
        q = q.filter(News.effects.any(Asset.id == effect_id))
    return q.order_by(News.created_at.desc()).limit(500).all()


@router.patch("/{news_id}", response_model=NewsOut)
def patch_news(news_id: int, payload: NewsPatch, db: Session = Depends(get_db)):
    news = db.get(News, news_id)
    if not news:
        raise HTTPException(404, "News not found")
    if payload.to_watch is not None:
        news.to_watch = payload.to_watch
    db.commit()
    return news
