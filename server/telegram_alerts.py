"""Session start/finish alerts to a Telegram group, sent via Telethon.

Reuses the najib account's API credentials (config/telegram.py) with a
dedicated session file so it never contends with the forwarder's session:

    TELEGRAM_ALERT_SESSION  session file name   (default "alerts_session")
    TELEGRAM_ALERT_CHAT     group @username or numeric id (required)

First run must be interactive once to log in (python -m server.telegram_alerts).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from config.config import API_ID_NAJIB, API_HASH_NAJIB
from config.sessions import DEFAULT_SESSIONS

logger = logging.getLogger(__name__)

ALERT_SESSION = os.environ.get("TELEGRAM_ALERT_SESSION", "alerts_session")

_SESSION_EMOJI = {
    "sydney": "🇦🇺",
    "tokyo": "🇯🇵",
    "london": "🇬🇧",
    "newyork": "🇺🇸",
}


def _alert_chat() -> int | str | None:
    raw = os.environ.get("TELEGRAM_ALERT_CHAT", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return raw


def _pretty(name: str) -> str:
    return name.capitalize().replace("Newyork", "New York")


def format_session_message(session: str, event: str) -> str:
    """A compact, visual session banner (Markdown)."""
    start_h, end_h = DEFAULT_SESSIONS[session]
    emoji = _SESSION_EMOJI.get(session, "🕐")
    icon = "🟢 OPEN" if event == "start" else "🔴 CLOSE"
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    bar = "─" * 22
    return (
        f"{emoji} **{_pretty(session)} session {icon}**\n"
        f"{bar}\n"
        f"🕐 Now: `{now}`\n"
        f"📅 Window: `{start_h:02d}:00 → {end_h:02d}:00 UTC`\n"
        f"{bar}"
    )


async def send_alert(text: str) -> bool:
    """Send one message to the alert group. Returns False when unconfigured."""
    chat = _alert_chat()
    if chat is None or not API_ID_NAJIB:
        logger.warning("Telegram alerts not configured "
                       "(TELEGRAM_ALERT_CHAT / API credentials missing)")
        return False
    from telethon import TelegramClient
    client = TelegramClient(ALERT_SESSION, API_ID_NAJIB, API_HASH_NAJIB)
    async with client:
        await client.send_message(chat, text, parse_mode="md")
    return True


async def send_session_alert(session: str, event: str) -> None:
    try:
        await send_alert(format_session_message(session, event))
        logger.info(f"Sent {session} {event} alert")
    except Exception:
        logger.exception(f"Failed to send {session} {event} alert")


if __name__ == "__main__":
    # One-time interactive login + test message.
    logging.basicConfig(level=logging.INFO)
    asyncio.run(send_alert("✅ Market Prep alert bot connected"))
