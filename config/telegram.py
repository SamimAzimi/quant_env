# ─────────────────────────────────────────────────────────────────────────────
# Telegram forwarder settings (consumed by tools/telegram_forwarder.py)
#
# API credentials are secrets and come from the environment / .env —
# see .env.example. Chat IDs and behaviour flags stay here as plain config.
# ─────────────────────────────────────────────────────────────────────────────

from .secrets import get_secret


def _int_secret(name: str) -> int:
    value = get_secret(name)
    return int(value) if value else 0


# Account "najib"
API_ID_NAJIB = _int_secret("TELEGRAM_API_ID_NAJIB")
API_HASH_NAJIB = get_secret("TELEGRAM_API_HASH_NAJIB")
SESSION_NAME = "forwarder_session"          # session file name, can be anything

# Account "samim_uz"
API_ID_SAMIM_UZ = _int_secret("TELEGRAM_API_ID_SAMIM_UZ")
API_HASH_SAMIM_UZ = get_secret("TELEGRAM_API_HASH_SAMIM_UZ")
SESSION_NAME_SAMIM = "forwarder_session_samim_uz"

# Source chats/channels each account listens to
SOURCE_CHATS  = [
    get_secret("SOURCE_CHATS"),
]
SOURCE_CHATS_SAMIM_UZ = [
    get_secret("SOURCE_CHATS_SAMIM_UZ"),
]

# Destination accounts to forward messages to.
# Use @username, or numeric user ID. Must be someone you can message
# (existing chat, or a public username).
DEST_ACCOUNTS = [
    get_secret("DEST_ACCOUNTS"),
]

# If True, uses native Telegram "forward" (keeps "Forwarded from X" tag,
# preserves media/formatting perfectly).
# If False, re-sends message as a fresh copy (no "Forwarded from" tag,
# but loses some metadata for certain media types).
USE_NATIVE_FORWARD = True
