"""Idempotent seed data: default tags and the Effect asset taxonomy.

Hard assets: GOLD, OIL, Silver, Commodities.
Soft assets: sub-categorised into Indices, Forex, Crypto, Bonds, Derivatives,
Stock — each seeded with its top tickers. Users can add more via the API.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import Asset, AssetCategory, Country, Source, Tag

DEFAULT_SOURCES = [
    "Bloomberg",
    "Reuters",
    "CNBC",
    "Financial Times",
    "WSJ",
    "X / Twitter",
    "FinancialJuice",
    "ForexFactory",
]

DEFAULT_COUNTRIES = [
    "United States",
    "Eurozone",
    "United Kingdom",
    "Japan",
    "China",
    "Switzerland",
    "Canada",
    "Australia",
    "New Zealand",
    "Global",
]

DEFAULT_TAGS = [
    "TOP5 Countries",
    "AI",
    "EV",
    "Tariffs",
    "Competition",
    "FED Speakers",
    "Geopolitics",
    "Presidents",
]

# category name -> (kind, [(ticker, display name), ...])
DEFAULT_ASSETS = {
    "Commodities": ("hard", [
        ("GOLD", "Gold"),
        ("XAUUSD", "Gold Spot"),
        ("SILVER", "Silver"),
        ("XAGUSD", "Silver Spot"),
        ("OIL", "Crude Oil"),
        ("NATGAS", "Natural Gas"),
        ("COPPER", "Copper"),
    ]),
    "Indices": ("soft", [
        ("NDX", "Nasdaq 100"),
        ("SPX", "S&P 500"),
        ("DJI", "Dow Jones"),
        ("DAX", "DAX 40"),
        ("NIKKEI", "Nikkei 225"),
    ]),
    "Forex": ("soft", [
        ("USDJPY", "USD/JPY"),
        ("EURUSD", "EUR/USD"),
        ("GBPUSD", "GBP/USD"),
        ("AUDUSD", "AUD/USD"),
        ("USDCHF", "USD/CHF"),
    ]),
    "Crypto": ("soft", [
        ("BTCUSDT", "Bitcoin"),
        ("ETHUSDT", "Ethereum"),
        ("SOLUSDT", "Solana"),
    ]),
    "Bonds": ("soft", [
        ("US10Y", "US 10Y Yield"),
        ("US02Y", "US 2Y Yield"),
        ("US30Y", "US 30Y Yield"),
    ]),
    "Derivatives": ("soft", [
        ("VIX", "CBOE VIX"),
        ("ES", "S&P 500 E-mini"),
        ("NQ", "Nasdaq E-mini"),
    ]),
    "Stock": ("soft", [
        ("NVDA", "Nvidia"),
        ("AAPL", "Apple"),
        ("MSFT", "Microsoft"),
        ("TSLA", "Tesla"),
        ("AMZN", "Amazon"),
    ]),
}


def seed(db: Session) -> None:
    existing_tags = {t.name for t in db.query(Tag).all()}
    for name in DEFAULT_TAGS:
        if name not in existing_tags:
            db.add(Tag(name=name))

    existing_countries = {c.name for c in db.query(Country).all()}
    for name in DEFAULT_COUNTRIES:
        if name not in existing_countries:
            db.add(Country(name=name))

    existing_sources = {s.name for s in db.query(Source).all()}
    for name in DEFAULT_SOURCES:
        if name not in existing_sources:
            db.add(Source(name=name))

    existing_cats = {c.name: c for c in db.query(AssetCategory).all()}
    existing_tickers = {a.ticker for a in db.query(Asset).all()}
    for cat_name, (kind, assets) in DEFAULT_ASSETS.items():
        cat = existing_cats.get(cat_name)
        if cat is None:
            cat = AssetCategory(name=cat_name, kind=kind)
            db.add(cat)
            db.flush()
            existing_cats[cat_name] = cat
        for ticker, display in assets:
            if ticker not in existing_tickers:
                db.add(Asset(ticker=ticker, name=display, category_id=cat.id))
                existing_tickers.add(ticker)

    db.commit()
