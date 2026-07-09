"""Regression tests for the config package: legacy import surface,
root-anchored paths, and no committed secrets."""
import importlib
import re
from pathlib import Path

import config.config as C
from config.paths import PROJECT_ROOT

LEGACY_NAMES = [
    # instruments
    "InstrumentSpec", "DEFAULT_SPECS", "_FOREX_TEMPLATE", "_ALIASES",
    # paths / dashboard
    "DEFAULT_DB", "OUTPUT_DIR", "MARKET_DATA_DIR",
    "METRIC_FMT", "FILTERABLE", "SCORE_TERMS", "METRIC_META", "METRIC_GROUPS",
    "PALETTE", "_PLOTLY_CDN", "LWC_CDN", "_TIME_NAME", "_LEVEL_NAME",
    # data sources
    "POLYGON_API_KEY", "POLYGON_CALLS_PER_MINUTE", "BINANCE_SLEEP",
    "TIME_COL", "OHLC", "FULL_SCHEMA", "ASSETS", "BINANCE_SYMBOLS",
    "INTRADAY_TFS", "START_DATE", "DAILY_START", "POLYGON_TF", "BINANCE_TF",
    "_BINANCE_COLS", "_DATETIME_SYNONYMS",
    # sessions
    "DEFAULT_SESSIONS", "DEFAULT_SESSIONS1", "DEFAULT_OVERLAP",
    "TRADING_DAYS", "_DOW_NAMES",
    # telegram
    "API_ID_NAJIB", "API_HASH_NAJIB", "SESSION_NAME", "SOURCE_CHATS",
    "DEST_ACCOUNTS", "USE_NATIVE_FORWARD",
]


def test_legacy_import_surface_is_preserved():
    missing = [n for n in LEGACY_NAMES if not hasattr(C, n)]
    assert not missing, f"config.config lost legacy names: {missing}"


def test_paths_are_root_anchored():
    assert Path(C.DEFAULT_DB).is_absolute() or "BACKTEST_DB" in str(C.DEFAULT_DB)
    assert C.OUTPUT_DIR.is_absolute()
    assert C.MARKET_DATA_DIR.is_absolute()
    assert (PROJECT_ROOT / "config" / "config.py").exists()


def test_output_path_puts_relative_names_in_output_dir():
    p = Path(C.output_path("some_report.html"))
    assert p.parent == C.OUTPUT_DIR
    absolute = C.OUTPUT_DIR / "sub" / "x.html"
    assert C.output_path(str(absolute)) == str(absolute)


SECRET_PATTERN = re.compile(
    r"""(?:api_?key|api_?hash|secret|token|private_key)\s*['"]?\s*[:=]\s*['"][A-Za-z0-9+/_%-]{16,}['"]""",
    re.IGNORECASE,
)


def test_no_hardcoded_secrets_in_config_sources():
    offenders = []
    for py in (PROJECT_ROOT / "config").glob("*.py"):
        for i, line in enumerate(py.read_text().splitlines(), 1):
            if SECRET_PATTERN.search(line):
                offenders.append(f"{py.name}:{i}")
    assert not offenders, f"possible hardcoded secrets: {offenders}"
