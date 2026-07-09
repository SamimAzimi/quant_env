"""
data_manager.py
================
Incremental market-data downloader / updater.

For every (asset, timeframe) it:
  1. Looks for an existing CSV.
  2. If it exists, reads the LAST row's timestamp.
  3. Fetches new data from the API starting at that timestamp (inclusive,
     so the last - possibly still-forming - bar gets refreshed).
  4. Appends, then de-duplicates keeping the NEWEST copy of any overlapping
     bar and re-sorts ascending.  => no data loss, newer bars win.

Sources
  - Polygon   -> indices / FX / metals  (intraday 5m..4h)
  - Binance   -> crypto                 (intraday 5m..4h)
  - yfinance  -> stocks / indices       (daily, via vectorbt's YFData)

Each asset has ONE canonical, filesystem-safe folder name shared by all
sources; files inside differ only by timeframe (5m.csv, 1h.csv, 1d.csv, ...).

CSV schema (uniform across all sources):
    Open time, open, high, low, close [, volume]
'Open time' is bar-open time in UTC (tz-naive, stored as plain text).

VOLUME IS OPTIONAL. Instruments with no real volume (indices, FX) are saved
without a volume column. The rule that keeps a file internally consistent:
  - new file  -> include volume only if the data has non-zero volume
  - existing  -> always follow the file's own header (never flip mid-life)
"""

import os
import sys
import time
import argparse
from datetime import datetime, timezone

import pandas as pd
import vectorbt as vbt
from config.config import (
    MARKET_DATA_DIR as OUTPUT_DIR,   # download target: <root>/data/marketdata
    POLYGON_API_KEY, POLYGON_CALLS_PER_MINUTE, BINANCE_SLEEP,
    TIME_COL, OHLC, FULL_SCHEMA, ASSETS, BINANCE_SYMBOLS, INTRADAY_TFS,
    START_DATE, DAILY_START, POLYGON_TF, BINANCE_TF, _BINANCE_COLS,
)
# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def path_for(folder: str, tf: str, suffix: str = "") -> str:
    """Return <OUTPUT_DIR>/<folder>/<tf><suffix>.csv, creating the folder."""
    folder_path = os.path.join(OUTPUT_DIR, folder)
    os.makedirs(folder_path, exist_ok=True)
    return os.path.join(folder_path, f"{tf}{suffix}.csv")


def to_ms_utc(ts) -> int:
    """Timestamp/str -> Unix milliseconds, treating naive values as UTC."""
    ts = pd.Timestamp(ts)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return int(ts.timestamp() * 1000)


def file_has_volume(filepath: str):
    """True/False if the file exists and its header is readable, else None.

    None means 'unknown / new file' -> the caller decides from the data.
    """
    if not (os.path.exists(filepath) and os.path.getsize(filepath) > 0):
        return None
    try:
        return "volume" in pd.read_csv(filepath, nrows=0).columns
    except Exception:
        return None


def _has_real_volume(df: pd.DataFrame) -> bool:
    """True when df has a volume column with at least one non-zero value."""
    if "volume" not in df.columns:
        return False
    vol = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    return bool(vol.abs().sum() > 0)


def _apply_schema(df: pd.DataFrame, keep_volume: bool) -> pd.DataFrame:
    """Select [Open time, OHLC] (+ volume only when keep_volume is True).

    If keep_volume is True but the data lacks a volume column, a NA column is
    added so the file's columns stay consistent across appends.
    """
    cols = [TIME_COL] + OHLC + (["volume"] if keep_volume else [])
    if keep_volume and "volume" not in df.columns:
        df = df.copy()
        df["volume"] = pd.NA
    return df[cols]


def _read_last_data_line(filepath: str, chunk: int = 2048):
    """Efficiently read the last non-empty line without loading the file."""
    with open(filepath, "rb") as f:
        f.seek(0, os.SEEK_END)
        filesize = f.tell()
        if filesize == 0:
            return None
        data = b""
        pos = filesize
        while pos > 0:
            read_size = min(chunk, pos)
            pos -= read_size
            f.seek(pos)
            data = f.read(read_size) + data
            lines = [ln for ln in data.split(b"\n") if ln.strip()]
            if len(lines) >= 2:                       # header + >=1 data row seen
                return lines[-1].decode("utf-8", "replace")
    lines = [ln for ln in data.split(b"\n") if ln.strip()]
    return lines[-1].decode("utf-8", "replace") if len(lines) >= 2 else None


def get_last_timestamp(filepath: str):
    """Timestamp of the last data row (files are stored ascending), else None."""
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return None
    line = _read_last_data_line(filepath)
    if not line:
        return None
    first_field = line.split(",")[0].strip()
    try:
        ts = pd.to_datetime(first_field)
        return None if pd.isna(ts) else ts
    except (ValueError, TypeError):
        try:                                          # fallback: full read
            df = pd.read_csv(filepath)
            return None if df.empty else pd.to_datetime(df.iloc[-1, 0])
        except Exception:
            return None


def _atomic_write_csv(df: pd.DataFrame, filepath: str):
    """Write via a temp file + os.replace so an interrupt can't corrupt data."""
    tmp = filepath + ".tmp"
    df.to_csv(tmp, index=False)
    os.replace(tmp, filepath)


def append_df(df: pd.DataFrame, filepath: str):
    """Append rows; write the header only when the file is new/empty."""
    if df is None or df.empty:
        return
    write_header = not (os.path.exists(filepath) and os.path.getsize(filepath) > 0)
    df.to_csv(filepath, mode="a", header=write_header, index=False)


def consolidate_csv(filepath: str):
    """De-duplicate on Open time keeping the LAST (newest) copy, then sort asc.

    Schema-agnostic: works whether or not the file carries a volume column.
    Because new bars are appended after existing ones, 'keep=last' means a
    refreshed/overlapping bar overwrites the stale one -> newer data wins.
    """
    if not os.path.exists(filepath):
        return
    df = pd.read_csv(filepath)
    if df.empty or TIME_COL not in df.columns:
        return
    df[TIME_COL] = pd.to_datetime(df[TIME_COL])
    df = (df.drop_duplicates(subset=TIME_COL, keep="last")
            .sort_values(TIME_COL)
            .reset_index(drop=True))
    _atomic_write_csv(df, filepath)


def _get_with_retry(url, params=None, max_retries=5):
    """GET with backoff on 429 / 5xx / network errors. Returns Response or None."""
    import requests
    backoff = 2.0
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, timeout=30)
        except requests.RequestException as e:
            print(f"[WARN] request error: {e} (retry {attempt + 1}/{max_retries})")
            time.sleep(backoff); backoff *= 2; continue
        if resp.status_code == 429 or resp.status_code >= 500:
            wait = backoff
            ra = resp.headers.get("Retry-After")
            if ra:
                try:
                    wait = max(wait, float(ra))
                except ValueError:
                    pass
            print(f"[WARN] HTTP {resp.status_code}; backing off {wait:.0f}s")
            time.sleep(wait); backoff *= 2; continue
        return resp
    print("[ERROR] max retries exceeded")
    return None


# --------------------------------------------------------------------------- #
# Polygon  (indices / FX / metals, intraday)
# --------------------------------------------------------------------------- #
def _polygon_pages(symbol, multiplier, timespan, start, end, filepath, keep_volume):
    """Stream every paginated page to disk. Returns total rows or None on error.

    keep_volume: True/False to force, or None to decide from the first page
    (kept fixed for the rest of the pull so the file stays consistent).
    """
    base = (f"https://api.polygon.io/v2/aggs/ticker/{symbol}"
            f"/range/{multiplier}/{timespan}/{start}/{end}")
    use_params = {"adjusted": "true", "sort": "asc",
                  "limit": 50000, "apiKey": POLYGON_API_KEY}
    url, total = base, 0

    while url:
        resp = _get_with_retry(url, params=use_params)
        if resp is None:
            return None
        if resp.status_code != 200:
            print(f"[ERROR] {symbol} {multiplier}{timespan}: "
                  f"{resp.status_code} {resp.text[:200]}")
            return None

        data = resp.json()
        if data.get("status") == "ERROR":
            print(f"[ERROR] {symbol}: {data.get('error')}")
            return None

        results = data.get("results")
        if not results:
            break

        df = pd.DataFrame(results)
        df[TIME_COL] = pd.to_datetime(df["t"], unit="ms")
        df = df.rename(columns={"o": "open", "h": "high",
                                "l": "low", "c": "close", "v": "volume"})
        if keep_volume is None:                       # new file: decide once
            keep_volume = _has_real_volume(df)
        df = _apply_schema(df, keep_volume)
        append_df(df, filepath)
        total += len(df)

        url = data.get("next_url")
        use_params = {"apiKey": POLYGON_API_KEY} if url else None
        if url:
            time.sleep(60 / POLYGON_CALLS_PER_MINUTE)   # respect rate limit

    return total


def update_polygon(folder, symbol, tf):
    multiplier, timespan = POLYGON_TF[tf]
    filepath = path_for(folder, tf)

    last_ts = get_last_timestamp(filepath)
    keep_volume = file_has_volume(filepath)      # True/False, or None -> decide
    end = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if last_ts is None:
        start, first_run = START_DATE, True
        print(f"[INFO] Polygon {symbol} {tf}: full pull from {start}")
    else:
        start, first_run = str(to_ms_utc(last_ts)), False   # inclusive ms
        print(f"[INFO] Polygon {symbol} {tf}: resume from {last_ts}")

    total = _polygon_pages(symbol, multiplier, timespan, start, end,
                           filepath, keep_volume)
    if total is None:
        return
    if not first_run:
        consolidate_csv(filepath)
    print(f"[DONE] Polygon {symbol} {tf}: +{total} rows -> {filepath}")





def _binance_pages(symbol, interval, start_ms, filepath, keep_volume,
                   end_ms=None, limit=1000):
    """Stream klines to disk page by page. Returns total rows or None on error."""
    url, total = "https://api.binance.com/api/v3/klines", 0

    while True:
        params = {"symbol": symbol, "interval": interval,
                  "startTime": start_ms, "limit": limit}
        if end_ms:
            params["endTime"] = end_ms

        resp = _get_with_retry(url, params=params)
        if resp is None:
            return None
        data = resp.json()

        if isinstance(data, dict):           # error payload, e.g. invalid symbol
            print(f"[ERROR] Binance {symbol} {interval}: {data.get('msg', data)}")
            return None
        if not data:
            break

        df = pd.DataFrame(data, columns=_BINANCE_COLS)
        df[TIME_COL] = pd.to_datetime(df["Open time"], unit="ms")
        df[OHLC + ["volume"]] = df[OHLC + ["volume"]].astype(float)
        df = _apply_schema(df, keep_volume)
        append_df(df, filepath)
        total += len(df)

        start_ms = data[-1][0] + 1           # next page strictly after last open
        if end_ms and start_ms >= end_ms:
            break
        if len(data) < limit:                # last page reached
            break
        time.sleep(BINANCE_SLEEP)

    return total


def update_binance(symbol, tf):
    interval = BINANCE_TF[tf]
    filepath = path_for(symbol, tf)          # folder == symbol for crypto

    last_ts = get_last_timestamp(filepath)
    keep_volume = file_has_volume(filepath)
    keep_volume = True if keep_volume is None else keep_volume   # crypto has volume

    if last_ts is None:
        start_ms, first_run = to_ms_utc(START_DATE), True
        print(f"[INFO] Binance {symbol} {tf}: full pull from {START_DATE}")
    else:
        start_ms, first_run = to_ms_utc(last_ts), False     # inclusive
        print(f"[INFO] Binance {symbol} {tf}: resume from {last_ts}")

    total = _binance_pages(symbol, interval, start_ms, filepath, keep_volume)
    if total is None:
        return
    if not first_run:
        consolidate_csv(filepath)
    print(f"[DONE] Binance {symbol} {tf}: +{total} rows -> {filepath}")


# --------------------------------------------------------------------------- #
# yfinance daily  (stocks / indices, via vectorbt)
# --------------------------------------------------------------------------- #
def update_yf_daily(folder, symbol, tf="1d"):
    try:
        import vectorbt as vbt
    except ImportError:
        print("[WARN] vectorbt not installed; skipping daily download")
        return

    filepath = path_for(folder, tf)          # same folder as the Polygon intraday
    last_ts = get_last_timestamp(filepath)
    existing_vol = file_has_volume(filepath)
    start = last_ts.strftime("%Y-%m-%d") if last_ts is not None else DAILY_START
    first_run = last_ts is None
    print(f"[INFO] yfinance {symbol} {tf}: "
          f"{'full pull' if first_run else 'resume'} from {start}")

    try:
        df = vbt.YFData.download(symbol, start=start).get()
    except Exception as e:
        print(f"[ERROR] yfinance {symbol}: {e}")
        return
    if df is None or df.empty:
        print(f"[WARN] yfinance {symbol}: no data returned")
        return

    df = df.reset_index()
    df = df.rename(columns={df.columns[0]: TIME_COL, "Open": "open",
                            "High": "high", "Low": "low",
                            "Close": "close", "Volume": "volume"})
    df[TIME_COL] = pd.to_datetime(df[TIME_COL]).dt.tz_localize(None)

    keep_volume = _has_real_volume(df) if existing_vol is None else existing_vol
    df = _apply_schema(df, keep_volume)

    append_df(df, filepath)
    if not first_run:
        consolidate_csv(filepath)
    print(f"[DONE] yfinance {symbol} {tf}: +{len(df)} rows -> {filepath}")


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run(sources=("polygon", "binance", "yfinance")):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if "polygon" in sources:
        for folder, poly, _yf in ASSETS:
            for tf in INTRADAY_TFS:
                try:
                    update_polygon(folder, poly, tf)
                except Exception as e:
                    print(f"[ERROR] Polygon {poly} {tf}: {e}")

    if "binance" in sources:
        for symbol in BINANCE_SYMBOLS:
            for tf in INTRADAY_TFS:
                try:
                    update_binance(symbol, tf)
                except Exception as e:
                    print(f"[ERROR] Binance {symbol} {tf}: {e}")

    if "yfinance" in sources:
        for folder, _poly, yf in ASSETS:
            try:
                update_yf_daily(folder, yf)
            except Exception as e:
                print(f"[ERROR] yfinance {yf}: {e}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Incremental market-data manager")
    p.add_argument("--sources", nargs="+",
                   default=["polygon", "binance", "yfinance"],
                   choices=["polygon", "binance", "yfinance"],
                   help="which sources to update")
    args = p.parse_args()
    run(sources=tuple(args.sources))