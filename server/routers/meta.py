"""Tags and Effect assets: dropdown options plus inline "+" creation."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Asset, AssetCategory, Country, Source, Tag
from ..schemas import (
    AssetCategoryOut, AssetIn, AssetOut, CountryIn, CountryOut,
    SourceIn, SourceOut, TagIn, TagOut,
)

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


@router.get("/sources", response_model=list[SourceOut])
def list_sources(db: Session = Depends(get_db)):
    return db.query(Source).order_by(Source.name).all()


@router.post("/sources", response_model=SourceOut, status_code=201)
def create_source(payload: SourceIn, db: Session = Depends(get_db)):
    name = payload.name.strip()
    existing = db.query(Source).filter(Source.name == name).first()
    if existing:
        return existing
    source = Source(name=name)
    db.add(source)
    db.commit()
    return source


@router.get("/effects", response_model=list[AssetCategoryOut])
def list_effects(db: Session = Depends(get_db)):
    """Asset taxonomy grouped by category (hard first, then soft)."""
    return (
        db.query(AssetCategory)
        .order_by(AssetCategory.kind, AssetCategory.name)
        .all()
    )


@router.get("/countries", response_model=list[CountryOut])
def list_countries(db: Session = Depends(get_db)):
    return db.query(Country).order_by(Country.name).all()


@router.post("/countries", response_model=CountryOut, status_code=201)
def create_country(payload: CountryIn, db: Session = Depends(get_db)):
    name = payload.name.strip()
    existing = db.query(Country).filter(Country.name == name).first()
    if existing:
        return existing
    country = Country(name=name)
    db.add(country)
    db.commit()
    return country


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
