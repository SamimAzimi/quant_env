"""Single import surface for all framework configuration.

The actual settings live in focused modules — paths, instruments,
data_sources, dashboard_meta, sessions, telegram — and are re-exported here
so `from config.config import X` keeps working everywhere.

Note: OUTPUT_DIR now means the generated-reports folder (<root>/output).
The market-data download folder is MARKET_DATA_DIR (<root>/data/marketdata).
"""

from .paths import (
    PROJECT_ROOT,
    DATA_DIR,
    MARKET_DATA_DIR,
    DB_DIR,
    OUTPUT_DIR,
    DEFAULT_DB,
    ensure_dir,
    output_path,
)

from .instruments import (
    InstrumentSpec,
    _FOREX_TEMPLATE,
    DEFAULT_SPECS,
    _ALIASES,
)

from .data_sources import (
    POLYGON_API_KEY,
    POLYGON_CALLS_PER_MINUTE,
    BINANCE_SLEEP,
    TIME_COL,
    OHLC,
    FULL_SCHEMA,
    ASSETS,
    BINANCE_SYMBOLS,
    INTRADAY_TFS,
    START_DATE,
    DAILY_START,
    POLYGON_TF,
    BINANCE_TF,
    _BINANCE_COLS,
    _DATETIME_SYNONYMS,
)

from .dashboard_meta import (
    METRIC_FMT,
    FILTERABLE,
    SCORE_TERMS,
    METRIC_META,
    METRIC_GROUPS,
    PALETTE,
    _PLOTLY_CDN,
    LWC_CDN,
    _TIME_NAME,
    _LEVEL_NAME,
)

from .sessions import (
    DEFAULT_SESSIONS,
    SESSION_BUCKETS,
    DEFAULT_SESSIONS1,
    DEFAULT_OVERLAP,
    TRADING_DAYS,
    _DOW_NAMES,
)

from .telegram import (
    API_ID_NAJIB,
    API_HASH_NAJIB,
    SESSION_NAME,
    SOURCE_CHATS,
    API_ID_SAMIM_UZ,
    API_HASH_SAMIM_UZ,
    SESSION_NAME_SAMIM,
    SOURCE_CHATS_SAMIM_UZ,
    DEST_ACCOUNTS,
    USE_NATIVE_FORWARD,
)
