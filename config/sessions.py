# ─────────────────────────────────────────────────────────────────────────────
# FX session windows & calendar constants
# (consumed by libs/market_stats.py, libs/performance.py, libs/market_sessions.py)
# ─────────────────────────────────────────────────────────────────────────────

# FX session windows as (start_hour, end_hour) in the working timezone (UTC by
# default). A window with start > end wraps midnight (e.g. Sydney). These are
# conventional GMT/UTC boundaries and shift ~1h with daylight saving — override
# them to match your data's timezone if you need exact alignment.
DEFAULT_SESSIONS = {
    "sydney":  (21, 6),
    "tokyo":   (0, 9),     # "Asian" session
    "london":  (7, 16),
    "newyork": (12, 21),
}

# Non-overlapping partition of the 24h day used for per-session P&L attribution
# (performance.py). Distinct from DEFAULT_SESSIONS, which models the real,
# overlapping market sessions.
SESSION_BUCKETS = [
    ("Asian",             0, 7),
    ("London",            7, 12),
    ("London/NY overlap", 12, 16),
    ("New York",          16, 21),
    ("Off-hours",         21, 24),
]
# Backward-compatible alias (old name)
DEFAULT_SESSIONS1 = SESSION_BUCKETS

# The window where London and New York are both open — the high-liquidity core.
DEFAULT_OVERLAP = (12, 16)

TRADING_DAYS = 252         # used only to turn bars-per-year into bars-per-day

_DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
