"""APScheduler wiring: fire a Telegram alert at each session start/finish.

Sessions come from libs/market_sessions.py: each major session's hours are
local wall-clock in its own IANA timezone, and the cron triggers run in
that timezone — so alert times shift automatically with DST, matching the
session windows shown on the charts.

Enabled when MARKET_PREP_ALERTS=1 (so dev servers and tests stay silent).
"""
from __future__ import annotations

import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from libs.market_sessions import DEFAULT_SESSIONS as LIB_SESSIONS

from .marketdata import MAJOR_SESSIONS
from .telegram_alerts import send_session_alert

logger = logging.getLogger(__name__)


def alerts_enabled() -> bool:
    return os.environ.get("MARKET_PREP_ALERTS", "0") == "1"


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
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
