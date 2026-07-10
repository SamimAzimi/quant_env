# Market Preparation web app

Daily market-prep hub: record news, trades, sentiment and rate expectations
through the day, and get a Stats page each morning with yesterday's market
structure, key levels, and everything you flagged to watch.

Architecture: **FastAPI (Python) + MySQL** backend in `server/`,
**React (Vite + TypeScript)** frontend in `web/`. Market data is read on
request from the existing CSV store maintained by `libs/data_manager.py` —
no duplication into MySQL.

## Setup

```bash
# 1. Backend deps
pip install -e ".[web]"

# 2. MySQL (any 8.x works)
mysql -u root -e "CREATE DATABASE market_prep CHARACTER SET utf8mb4;"
# then set MARKET_PREP_DB_URL in .env (see .env.example)

# 3. Frontend
cd web && npm install && npm run build && cd ..

# 4. Market data for the charts (fills data/marketdata/*.csv)
python libs/data_manager.py
```

Tables are created and default tags/assets seeded automatically on first
startup — no migration step.

## Run

```bash
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

Open `http://<machine-ip>:8000` from any device on the LAN (phone, laptop,
TV). The layout is responsive: 1 column on mobile, 2 on laptop, 4-across
on a TV so everything fits one screen.

For frontend development, `npm run dev` inside `web/` serves a hot-reload
build on :5173 and proxies `/api` to :8000.

## Telegram session alerts

Session start/finish alerts (Sydney, Tokyo, London, New York — UTC windows
from `config/sessions.py`) are sent to a Telegram group via Telethon using
the najib account's API credentials with a dedicated session file.

```bash
# one-time interactive login + test message
TELEGRAM_ALERT_CHAT=@your_group python -m server.telegram_alerts

# then enable in .env
MARKET_PREP_ALERTS=1
TELEGRAM_ALERT_CHAT=@your_group      # or the numeric -100… group id
```

## Pages & data flow

- **Stats** (default page) — sections:
  - *Sentiment*: Fear & Greed gauge + VIX, from readings recorded the
    **previous UTC day** (record today → shows tomorrow).
  - *Macro*: recorded economic reports with inline edit of Actual and
    Beat/Miss once released.
  - *Rate probabilities*: latest recorded FedWatch table as bars, with
    the previous day's value marked for comparison.
  - *Pre-day stats*: color-coded cumulative log returns over yesterday,
    timeframe selector (default 15m), any assets from the CSV store.
  - *Charts*: yesterday's candles for NDX, XAUUSD, XAGUSD, USDJPY, EURUSD
    with pre-day high/low and per-session high/low price lines.
  - *To watch*: news flagged `to_watch`, persists across days until
    dismissed.
  - *Today news*: today's recorded news with effect/tag chips; yesterday's
    news scrolls in a ticker at the top.
  - *Trades*: today's + open trades, with an edit dialog for exit
    time/reason (times are UTC).
- **Record** — the round **+** button (bottom-right, every page) opens an
  overlay with tabs: News, Trade Journal, Analyze & Thoughts, VIX,
  Fear & Greed, Economic Reports, FOMC (paste the rate-probability
  markdown table; `server/rate_table.py` parses and stores it).

New pages: add a `<Route>` in `web/src/App.tsx` — the header and Record
button already live outside the router so they appear everywhere.

## Schema (MySQL, normalized)

`news` ⟷ `tags` via `news_tags`; `news` ⟷ `assets` via `news_effects`;
`assets` belong to `asset_categories` (kind: hard/soft — Commodities are
hard; Indices/Forex/Crypto/Bonds/Derivatives/Stock are soft);
`trades`, `vix_readings`, `fear_greed_readings`, `econ_reports`,
`thoughts`; `rate_snapshots` 1-* `rate_probs` (meeting date × bps bucket).

All timestamps are stored naive-UTC, matching the CSV market data.
