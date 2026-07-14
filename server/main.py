"""Market Preparation app entrypoint.

    uvicorn server.main:app --host 0.0.0.0 --port 8000

On startup it creates missing tables, seeds default tags/assets, and (when
MARKET_PREP_ALERTS=1) starts the session-alert scheduler. If web/dist exists
(the built React frontend), it is served at /.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .db import SessionLocal, engine
from .migrate import migrate
from .routers import (
    alerts, asset_stats, meta, news, rate_probs, records, stats, trades,
)
from .scheduler import alerts_enabled, build_scheduler
from .seed import seed

logger = logging.getLogger(__name__)

WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    migrate(engine)   # create missing tables and additive columns
    with SessionLocal() as db:
        seed(db)
    # user-alert dispatch always runs; session banners are opt-in
    scheduler = build_scheduler(session_banners=alerts_enabled())
    scheduler.start()
    logger.info("Scheduler started (session banners: %s)", alerts_enabled())
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Market Preparation", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # LAN devices: TV, phone, laptop
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(alerts.router)
app.include_router(asset_stats.router)
app.include_router(meta.router)
app.include_router(news.router)
app.include_router(trades.router)
app.include_router(records.router)
app.include_router(rate_probs.router)
app.include_router(stats.router)

if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
