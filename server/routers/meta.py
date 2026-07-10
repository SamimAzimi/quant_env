"""Tags and Effect assets: dropdown options plus inline "+" creation."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Asset, AssetCategory, Tag
from ..schemas import AssetCategoryOut, AssetIn, AssetOut, TagIn, TagOut

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/tags", response_model=list[TagOut])
def list_tags(db: Session = Depends(get_db)):
    return db.query(Tag).order_by(Tag.name).all()


@router.post("/tags", response_model=TagOut, status_code=201)
def create_tag(payload: TagIn, db: Session = Depends(get_db)):
    name = payload.name.strip()
    existing = db.query(Tag).filter(Tag.name == name).first()
    if existing:
        return existing
    tag = Tag(name=name)
    db.add(tag)
    db.commit()
    return tag


@router.get("/effects", response_model=list[AssetCategoryOut])
def list_effects(db: Session = Depends(get_db)):
    """Asset taxonomy grouped by category (hard first, then soft)."""
    return (
        db.query(AssetCategory)
        .order_by(AssetCategory.kind, AssetCategory.name)
        .all()
    )


@router.post("/effects", response_model=AssetOut, status_code=201)
def create_effect(payload: AssetIn, db: Session = Depends(get_db)):
    ticker = payload.ticker.strip().upper()
    existing = db.query(Asset).filter(Asset.ticker == ticker).first()
    if existing:
        return existing
    if not db.get(AssetCategory, payload.category_id):
        raise HTTPException(404, "Unknown asset category")
    asset = Asset(ticker=ticker, name=payload.name.strip() or ticker,
                  category_id=payload.category_id)
    db.add(asset)
    db.commit()
    return asset
