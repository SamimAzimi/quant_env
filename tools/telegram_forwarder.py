"""
Telegram Event-Based Message Forwarder (multi-account)
----------------------------------------
Runs multiple Telegram user accounts at once, each listening to its own
list of source chats/channels. Any new message (or reply) seen on any
account is forwarded to the same shared list of destination accounts.

Requirements:
    pip install telethon

Setup:
    Fill in config/config.py with per-account API_ID / API_HASH / SESSION_NAME /
    SOURCE_CHATS, and a single shared DEST_ACCOUNTS list. See ACCOUNTS below.
"""

import asyncio
import logging
import sys
from pathlib import Path

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError

# make `config` importable when run as `python tools/telegram_forwarder.py`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.config import (
    DEST_ACCOUNTS,
    USE_NATIVE_FORWARD,
    API_ID_NAJIB, API_HASH_NAJIB, SESSION_NAME, SOURCE_CHATS,
    API_ID_SAMIM_UZ, API_HASH_SAMIM_UZ, SESSION_NAME_SAMIM, SOURCE_CHATS_SAMIM_UZ,
)

# ----------------------- LOGGING -----------------------

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ----------------------- ACCOUNTS -----------------------
# One entry per Telegram account. Add more dicts here if you add more accounts.

ACCOUNTS = [
    {
        "label": "najib",
        "session": SESSION_NAME,
        "api_id": API_ID_NAJIB,
        "api_hash": API_HASH_NAJIB,
        "source_chats": SOURCE_CHATS,
    },
    {
        "label": "samim_uz",
        "session": SESSION_NAME_SAMIM,
        "api_id": API_ID_SAMIM_UZ,
        "api_hash": API_HASH_SAMIM_UZ,
        "source_chats": SOURCE_CHATS_SAMIM_UZ,
    },
]


async def safe_forward(client, dest, message):
    """Forward a message to a destination, retrying once on flood wait."""
    try:
        if USE_NATIVE_FORWARD:
            await client.forward_messages(dest, message)
        else:
            if message.media:
                await client.send_file(dest, message.media, caption=message.text or '')
            else:
                await client.send_message(dest, message.text or '')
    except FloodWaitError as e:
        logger.warning(f"Flood wait {e.seconds}s, retrying after wait...")
        await asyncio.sleep(e.seconds)
        await safe_forward(client, dest, message)
    except Exception as e:
        logger.error(f"Failed to forward message {message.id} to {dest}: {e}")


def make_handler(client, label):
    """Build a NewMessage handler bound to a specific client/account."""

    async def handler(event):
        message = event.message
        chat = await event.get_chat()
        chat_name = getattr(chat, 'title', None) or getattr(chat, 'username', chat.id)

        logger.info(f"[{label}] New message {message.id} in '{chat_name}'")

        try:
            if message.is_reply:
                reply_msg = await event.get_reply_message()
                if reply_msg:
                    logger.info(f"[{label}]  -> Reply to {reply_msg.id}, forwarding it first")
                    for dest in DEST_ACCOUNTS:
                        await safe_forward(client, dest, reply_msg)

            for dest in DEST_ACCOUNTS:
                await safe_forward(client, dest, message)

            logger.info(f"[{label}]  -> Forwarded message {message.id} to {len(DEST_ACCOUNTS)} destination(s)")

        except Exception as e:
            logger.error(f"[{label}] Error handling message {message.id}: {e}")

    return handler


async def run_account(account):
    label = account["label"]
    client = TelegramClient(account["session"], account["api_id"], account["api_hash"])

    client.add_event_handler(
        make_handler(client, label),
        events.NewMessage(chats=account["source_chats"])
    )

    await client.start()
    me = await client.get_me()
    logger.info(f"[{label}] Logged in as {me.first_name} (@{me.username})")
    logger.info(f"[{label}] Listening on {len(account['source_chats'])} source chat(s)...")

    await client.run_until_disconnected()


async def main():
    await asyncio.gather(*(run_account(account) for account in ACCOUNTS))


if __name__ == '__main__':
    asyncio.run(main())