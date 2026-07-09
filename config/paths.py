"""Canonical project paths, anchored to the repository root.

Every default location is derived from PROJECT_ROOT (the folder containing
this repo), so modules behave the same no matter which working directory
they are launched from. Each one can be overridden with an environment
variable when your data lives elsewhere:

    QUANT_DATA_DIR    root for downloaded market data   (default <root>/data)
    QUANT_DB_DIR      root for backtest result stores   (default <root>/DB)
    QUANT_OUTPUT_DIR  root for generated reports/HTML   (default <root>/output)
    BACKTEST_DB       full path of the default results database
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _env_dir(var: str, default: Path) -> Path:
    return Path(os.environ.get(var, str(default)))


DATA_DIR = _env_dir("QUANT_DATA_DIR", PROJECT_ROOT / "data")
MARKET_DATA_DIR = DATA_DIR / "marketdata"
DB_DIR = _env_dir("QUANT_DB_DIR", PROJECT_ROOT / "DB")
OUTPUT_DIR = _env_dir("QUANT_OUTPUT_DIR", PROJECT_ROOT / "output")

DEFAULT_DB = os.environ.get("BACKTEST_DB", str(DB_DIR / "all_backtests.db"))


def ensure_dir(path: Path | str) -> Path:
    """Create a directory (and parents) if missing; return it as a Path."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def output_path(filename: str) -> str:
    """Absolute path for a generated report file inside OUTPUT_DIR.

    Absolute inputs are respected as-is; relative ones land in OUTPUT_DIR so
    every artifact ends up in the one output folder.
    """
    p = Path(filename)
    if p.is_absolute():
        ensure_dir(p.parent)
        return str(p)
    ensure_dir(OUTPUT_DIR)
    return str(OUTPUT_DIR / p)
