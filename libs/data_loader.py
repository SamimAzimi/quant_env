"""
data_loader.py — OHLCV data ingestion helpers.

Responsibilities:
  • Read CSV files into a clean DataFrame with standard column names.
  • Nothing else.  No indicators, no strategy logic.
"""
from __future__ import annotations

import pandas as pd

from config.config import _DATETIME_SYNONYMS

def load_csv(filepath: str, has_volume: bool = False) -> pd.DataFrame:
    """
    Load an OHLCV (or OHLC) CSV and return a clean DataFrame.

    Expected raw column names (case-insensitive): open, high, low, close,
    and optionally volume.  The timestamp column can be named 'Date',
    'Open time', 'Datetime', or 'Timestamp'.

    Parameters
    ----------
    filepath   : path to the CSV file
    has_volume : if True, also load and return a 'Volume' column

    Returns
    -------
    DataFrame with columns: Open, High, Low, Close, Datetime[, Volume]
    """
    df = pd.read_csv(filepath, on_bad_lines="skip").dropna()

    # Normalise timestamp column name
    for col in df.columns:
        if col.lower() in _DATETIME_SYNONYMS:
            df.rename(columns={col: "Datetime"}, inplace=True)
            df['Datetime'] = pd.to_datetime(df['Datetime'],errors="coerce")
            break

    # Normalise OHLCV column names
    rename_map = {"open": "Open", "high": "High", "low": "Low", "close": "Close"}
    if has_volume:
        rename_map["volume"] = "Volume"
    df.rename(columns=rename_map, inplace=True)

    # Coerce numeric
    numeric_cols = ["Open", "High", "Low", "Close"] + (["Volume"] if has_volume else [])
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Select final columns
    base = ["Open", "High", "Low", "Close", "Datetime"]
    if has_volume and "Volume" in df.columns:
        base.append("Volume")

    available = [c for c in base if c in df.columns]
    return df[available].reset_index(drop=True)