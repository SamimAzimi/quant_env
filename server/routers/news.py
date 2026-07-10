"""News: recording with relationships, threaded watch list, fuzzy search,
story groups, and day/history views.

Stories form a DAG via news_relationships (parent → child). The To Watch
list shows open stories with their related follow-ups nested recursively;
History groups connected stories in a date range.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..dates import as_of_or_today, day_bounds, range_bounds
from ..db import get_db
from ..models import Asset, News, NewsRelationship, Tag
from ..schemas import (
    NewsGroupOut, NewsIn, NewsOut, NewsPatch, NewsThreadOut, NewsTreeOut,
)

router = APIRouter(prefix="/api/news", tags=["news"])


def _naive_utc(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None)


# --- relationship helpers -------------------------------------------------

def _rels(db: Session) -> list[NewsRelationship]:
    return db.query(NewsRelationship).all()


def _parents_map(rels) -> dict[int, set[int]]:
    out: dict[int, set[int]] = {}
    for r in rels:
        out.setdefault(r.child_id, set()).add(r.parent_id)
    return out


def _children_map(rels) -> dict[int, set[int]]:
    out: dict[int, set[int]] = {}
    for r in rels:
        out.setdefault(r.parent_id, set()).add(r.child_id)
    return out


def _ancestors(news_id: int, parents: dict[int, set[int]]) -> set[int]:
    seen: set[int] = set()
    stack = list(parents.get(news_id, ()))
    while stack:
        nid = stack.pop()
        if nid in seen:
            continue
        seen.add(nid)
        stack.extend(parents.get(nid, ()))
    return seen


def _assert_no_cycle(db: Session, child_id: int, parent_ids: list[int]) -> None:
    """Linking child under parent must not make the child its own ancestor."""
    parents = _parents_map(_rels(db))
    for pid in parent_ids:
        if pid == child_id or child_id in _ancestors(pid, parents):
            raise HTTPException(422, "Relationship would create a cycle")


def _set_parents(db: Session, news: News, parent_ids: list[int]) -> None:
    """Replace all parent links of a story (validated, cycle-safe)."""
    parent_ids = sorted({pid for pid in parent_ids if pid != news.id})
    if parent_ids:
        found = {row[0] for row in
                 db.query(News.id).filter(News.id.in_(parent_ids)).all()}
        missing = set(parent_ids) - found
        if missing:
            raise HTTPException(404, f"Unknown related news ids: {sorted(missing)}")
    _assert_no_cycle(db, news.id, parent_ids)
    db.query(NewsRelationship).filter(
        NewsRelationship.child_id == news.id).delete()
    for pid in parent_ids:
        db.add(NewsRelationship(parent_id=pid, child_id=news.id))


def _tree(news: News, children: dict[int, set[int]],
          by_id: dict[int, News], seen: set[int]) -> NewsTreeOut:
    seen.add(news.id)
    kids = [
        _tree(by_id[cid], children, by_id, seen)
        for cid in sorted(children.get(news.id, ()))
        if cid in by_id and cid not in seen
    ]
    node = NewsTreeOut.model_validate(news)
    node.children = sorted(kids, key=lambda k: k.publish_time)
    return node


# --- create / edit ----------------------------------------------------------

@router.post("", response_model=NewsOut, status_code=201)
def create_news(payload: NewsIn, db: Session = Depends(get_db)):
    news = News(
        title=payload.title.strip(),
        body=payload.body,
        role=payload.role,
        source_id=payload.source_id,
        status=payload.status,
        publish_time=_naive_utc(payload.publish_time),
    )
    if payload.tag_ids:
        news.tags = db.query(Tag).filter(Tag.id.in_(payload.tag_ids)).all()
    if payload.effect_ids:
        news.effects = db.query(Asset).filter(Asset.id.in_(payload.effect_ids)).all()
    db.add(news)
    db.flush()
    if payload.parent_ids:
        _set_parents(db, news, payload.parent_ids)
    db.commit()
    return news


# --- day views (as-of aware) -------------------------------------------------

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


# --- watch (open stories, threaded) ------------------------------------------

@router.get("/watch", response_model=list[NewsTreeOut])
def watch_list(db: Session = Depends(get_db)):
    """Open stories with their related follow-ups nested recursively.

    An open story that is itself a follow-up of another *open* story is
    folded under it instead of appearing twice at the top level.
    """
    open_news = (
        db.query(News)
        .filter(News.status == "open")
        .order_by(News.publish_time.desc())
        .all()
    )
    open_ids = {n.id for n in open_news}
    rels = _rels(db)
    parents = _parents_map(rels)
    children = _children_map(rels)

    # collect every story reachable from an open one, for nesting details
    needed = set(open_ids)
    stack = list(open_ids)
    while stack:
        nid = stack.pop()
        for cid in children.get(nid, ()):
            if cid not in needed:
                needed.add(cid)
                stack.append(cid)
    by_id = {n.id: n for n in
             db.query(News).filter(News.id.in_(needed)).all()} if needed else {}

    out = []
    seen: set[int] = set()
    for n in open_news:
        if _ancestors(n.id, parents) & open_ids:
            continue   # appears nested inside an open ancestor's tree
        if n.id not in seen:
            out.append(_tree(n, children, by_id, seen))
    return out


# --- fuzzy search --------------------------------------------------------------

@router.get("/search", response_model=list[NewsOut])
def search(q: str = Query(min_length=1), limit: int = 10,
           db: Session = Depends(get_db)):
    """Non-strict title search: substring and best fuzzy matches, ranked."""
    q_low = q.strip().lower()
    candidates = (
        db.query(News).order_by(News.publish_time.desc()).limit(2000).all()
    )
    scored = []
    for n in candidates:
        title = n.title.lower()
        score = SequenceMatcher(None, q_low, title).ratio()
        if q_low in title:
            score += 0.6
        else:
            words = title.split()
            if any(w.startswith(q_low) for w in words):
                score += 0.3
        if score >= 0.25:
            scored.append((score, n))
    scored.sort(key=lambda s: -s[0])
    return [n for _, n in scored[:max(1, min(limit, 50))]]


# --- history / groups -----------------------------------------------------------

@router.get("/history", response_model=list[NewsOut])
def history(start: date | None = None, end: date | None = None,
            tag_id: int | None = None, effect_id: int | None = None,
            db: Session = Depends(get_db)):
    """News over a date range, optionally filtered by tag and/or effect."""
    s, e = range_bounds(start, end)
    q = db.query(News).filter(News.publish_time >= s, News.publish_time < e)
    if tag_id is not None:
        q = q.filter(News.tags.any(Tag.id == tag_id))
    if effect_id is not None:
        q = q.filter(News.effects.any(Asset.id == effect_id))
    return q.order_by(News.publish_time.desc()).limit(500).all()


@router.get("/groups", response_model=list[NewsGroupOut])
def groups(start: date | None = None, end: date | None = None,
           db: Session = Depends(get_db)):
    """Connected story groups touching the date range.

    Starts from stories published in the range and expands recursively
    through news_relationships (both directions), so each group is the
    complete story even when parts fall outside the range. Named after the
    earliest primary story; sorted newest-first; edges included for graphs.
    """
    s, e = range_bounds(start, end)
    in_range = (
        db.query(News)
        .filter(News.publish_time >= s, News.publish_time < e)
        .all()
    )
    rels = _rels(db)
    parents = _parents_map(rels)
    children = _children_map(rels)

    def neighbours(nid: int) -> set[int]:
        return parents.get(nid, set()) | children.get(nid, set())

    groups_out: list[NewsGroupOut] = []
    assigned: set[int] = set()
    for seed in in_range:
        if seed.id in assigned:
            continue
        comp = {seed.id}
        stack = [seed.id]
        while stack:
            nid = stack.pop()
            for nb in neighbours(nid):
                if nb not in comp:
                    comp.add(nb)
                    stack.append(nb)
        assigned |= comp
        members = (
            db.query(News).filter(News.id.in_(comp))
            .order_by(News.publish_time.asc()).all()
        )
        primaries = [m for m in members if m.role == "primary"]
        name = (primaries or members)[0].title
        edges = [(r.parent_id, r.child_id) for r in rels
                 if r.parent_id in comp and r.child_id in comp]
        groups_out.append(NewsGroupOut(
            name=name,
            news=[NewsOut.model_validate(m) for m in members],
            edges=edges,
        ))
    groups_out.sort(key=lambda g: max(n.publish_time for n in g.news),
                    reverse=True)
    return groups_out


# --- single story ------------------------------------------------------------------

@router.get("/{news_id}/thread", response_model=NewsThreadOut)
def thread(news_id: int, db: Session = Depends(get_db)):
    """One story in context: its ancestors and its nested follow-ups."""
    news = db.get(News, news_id)
    if not news:
        raise HTTPException(404, "News not found")
    rels = _rels(db)
    parents = _parents_map(rels)
    children = _children_map(rels)

    anc_ids = _ancestors(news_id, parents)
    ancestors = (
        db.query(News).filter(News.id.in_(anc_ids))
        .order_by(News.publish_time.asc()).all()
    ) if anc_ids else []

    desc = {news_id}
    stack = [news_id]
    while stack:
        nid = stack.pop()
        for cid in children.get(nid, ()):
            if cid not in desc:
                desc.add(cid)
                stack.append(cid)
    by_id = {n.id: n for n in db.query(News).filter(News.id.in_(desc)).all()}
    return NewsThreadOut(
        ancestors=[NewsOut.model_validate(a) for a in ancestors],
        parent_ids=sorted(parents.get(news_id, set())),
        tree=_tree(news, children, by_id, set()),
    )


@router.patch("/{news_id}", response_model=NewsOut)
def patch_news(news_id: int, payload: NewsPatch, db: Session = Depends(get_db)):
    news = db.get(News, news_id)
    if not news:
        raise HTTPException(404, "News not found")
    data = payload.model_dump(exclude_unset=True)
    if "publish_time" in data and data["publish_time"] is not None:
        data["publish_time"] = _naive_utc(data["publish_time"])
    if "tag_ids" in data:
        ids = data.pop("tag_ids") or []
        news.tags = db.query(Tag).filter(Tag.id.in_(ids)).all() if ids else []
    if "effect_ids" in data:
        ids = data.pop("effect_ids") or []
        news.effects = db.query(Asset).filter(Asset.id.in_(ids)).all() if ids else []
    if "parent_ids" in data:
        _set_parents(db, news, data.pop("parent_ids") or [])
    for field, value in data.items():
        setattr(news, field, value)
    db.commit()
    return news
