"""APScheduler wiring: session start/finish banners plus user alerts.

Sessions come from libs/market_sessions.py: each major session's hours are
local wall-clock in its own IANA timezone, and the cron triggers run in
that timezone — so alert times shift automatically with DST, matching the
session windows shown on the charts. Session banners are enabled with
MARKET_PREP_ALERTS=1 (dev servers and tests stay silent).

User-scheduled alerts (Record → Alert) are always dispatched: every 30s
due alerts are sent to the Telegram alert chat and deleted on success —
failed/unconfigured sends stay queued and retry on the next tick.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from libs.market_sessions import DEFAULT_SESSIONS as LIB_SESSIONS

from .db import SessionLocal
from .marketdata import MAJOR_SESSIONS
from .models import Alert
from .telegram_alerts import send_alert, send_session_alert

logger = logging.getLogger(__name__)


def alerts_enabled() -> bool:
    return os.environ.get("MARKET_PREP_ALERTS", "0") == "1"


async def dispatch_due_alerts() -> None:
    """Send every due user alert; delete each one only after it was sent."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as db:
        due = (db.query(Alert).filter(Alert.due_time <= now)
               .order_by(Alert.due_time.asc()).all())
        for alert in due:
            try:
                sent = await send_alert(
                    f"⏰ **Alert** — "
                    f"`{alert.due_time.strftime('%H:%M UTC')}`\n{alert.message}")
            except Exception:
                logger.exception("Failed to send alert #%s", alert.id)
                continue
            if sent:
                db.delete(alert)
                db.commit()
                logger.info("Sent and deleted alert #%s", alert.id)


def build_scheduler(session_banners: bool = True) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(dispatch_due_alerts, IntervalTrigger(seconds=30),
                      id="dispatch-alerts")
    if not session_banners:
        return scheduler
    for session in LIB_SESSIONS:
        if session.name not in MAJOR_SESSIONS:
            continue
        scheduler.add_job(
            send_session_alert,
            CronTrigger(day_of_week="mon-fri", hour=session.open.hour,
                        minute=session.open.minute, timezone=session.tz),
            args=[session.name, "start"], id=f"{session.name}-start",
        )
        scheduler.add_job(
            send_session_alert,
            CronTrigger(day_of_week="mon-fri", hour=session.close.hour,
                        minute=session.close.minute, timezone=session.tz),
            args=[session.name, "finish"], id=f"{session.name}-finish",
        )
    return scheduler
