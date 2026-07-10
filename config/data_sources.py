# ─────────────────────────────────────────────────────────────────────────────
# Market-data download & loading settings
# (consumed by libs/data_manager.py and libs/data_loader.py)
# ─────────────────────────────────────────────────────────────────────────────

from .paths import MARKET_DATA_DIR
from .secrets import get_secret

# API keys come from the environment / .env — see .env.example
POLYGON_API_KEY = get_secret("POLYGON_API_KEY")
POLYGON_CALLS_PER_MINUTE = 5            # free tier = 5/min -> 12s between calls
BINANCE_SLEEP = 0.3                     # Binance limits are generous

TIME_COL = "Open time"
OHLC = ["open", "high", "low", "close"]
FULL_SCHEMA = [TIME_COL] + OHLC + ["volume"]   # volume is optional per file

# What to download -----------------------------------------------------------
# One canonical folder per asset, shared by Polygon (intraday) and yfinance
# (daily). Folder names are filesystem-safe: no ':' '^' '=' characters.
#
#   (folder,    polygon symbol,  yfinance symbol)
ASSETS = [
    ("NDX",      "I:NDX",     "^NDX"),
    ("XAUUSD",   "C:XAUUSD",  "GC=F"),
    ("XAGUSD",   "C:XAGUSD",  "SI=F"),
    ("XPTUSD",   "C:XPTUSD",  "PL=F"),
    ("USDJPY",   "C:USDJPY",  "USDJPY=X"),
    ("EURUSD",   "C:EURUSD",  "EURUSD=X"),
    ("USDEUR",   "C:USDEUR",  "USDEUR=X"),  # NOTE: confirm base/quote direction
    ("GBPUSD",   "C:GBPUSD",  "GBPUSD=X"),
    ("GSPC",     "I:GSPC",    "^GSPC"),
    ("IRX",      "I:IRX",     "^IRX"),
    ("TNX",      "I:TNX",     "^TNX"),
    ("VIX",      "I:VIX",     "^VIX"),
]

BINANCE_SYMBOLS = ["BTCUSDT", "ETHUSDT"]      # crypto -> folder == symbol

INTRADAY_TFS = ["5m", "15m", "30m", "1h", "2h", "4h"]

START_DATE = "2020-01-01"      # first bar to pull when an intraday file is new
DAILY_START = "1980-01-01"     # full-history start for the daily/yfinance source

# Polygon multiplier / timespan per canonical timeframe
POLYGON_TF = {
    "5m":  (5, "minute"),
    "15m": (15, "minute"),
    "30m": (30, "minute"),
    "1h":  (1, "hour"),
    "2h":  (2, "hour"),
    "4h":  (4, "hour"),
}
# Binance native interval strings
BINANCE_TF = {tf: tf for tf in INTRADAY_TFS}

# Binance kline column layout
_BINANCE_COLS = ["Open time", "open", "high", "low", "close", "volume",
                 "Close time", "qav", "trades", "tbbav", "tbqav", "ignore"]

# Columns that might hold the timestamp in raw CSVs (data_loader.py)
_DATETIME_SYNONYMS = {"date", "open time", "datetime", "timestamp", "time"}
