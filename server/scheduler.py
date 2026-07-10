"""APScheduler wiring: fire a Telegram alert at each session start/finish.

Session boundaries come from config.sessions.DEFAULT_SESSIONS (UTC hours).
Enabled when MARKET_PREP_ALERTS=1 (so dev servers and tests stay silent).
"""
from __future__ import annotations

import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config.sessions import DEFAULT_SESSIONS

from .telegram_alerts import send_session_alert

logger = logging.getLogger(__name__)


def alerts_enabled() -> bool:
    return os.environ.get("MARKET_PREP_ALERTS", "0") == "1"


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    for session, (start_h, end_h) in DEFAULT_SESSIONS.items():
        scheduler.add_job(
            send_session_alert, CronTrigger(hour=start_h, minute=0),
            args=[session, "start"], id=f"{session}-start",
        )
        scheduler.add_job(
            send_session_alert, CronTrigger(hour=end_h, minute=0),
            args=[session, "finish"], id=f"{session}-finish",
        )
    return scheduler
