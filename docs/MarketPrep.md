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

The header carries a main menu: **Market Prep** (default) and **History**.

"Yesterday" everywhere means the **trading-day window**: Tokyo session
open → New York session close in UTC (00:00–21:00 with the default
session config). Pre-day levels and log returns use this window too.

- **Market Prep** (default page) — a date picker in the page toolbar
  replays any past day: every section behaves as if that day were today.
  Sections:
  - *Sentiment*: Fear & Greed gauge + VIX, from readings recorded the
    **previous UTC day** (record today → shows tomorrow).
  - *Macro*: economic reports grouped by country (expanded by default,
    collapsible per country) with inline edit of Actual and Beat/Miss.
  - *Rate probabilities*: latest recorded FedWatch table as bars — top 3
    buckets per meeting, the rest behind "see more…" — with the previous
    day's value marked for comparison.
  - *Pre-day stats*: color-coded cumulative log returns over yesterday,
    timeframe selector (default 15m), any assets from the CSV store.
  - *Charts*: yesterday's candles for NDX, XAUUSD, XAGUSD, USDJPY, EURUSD
    with pre-day high/low and per-session high/low price lines.
  - *To watch*: news flagged `to_watch`, persists across days until
    dismissed; click an item to expand its recorded details.
  - *Today news*: today's recorded news with effect/tag chips; yesterday's
    news scrolls in a ticker at the top.
  - *Trades*: the day's + open trades — open ones are highlighted with an
    accent border, closed ones dimmed — with an edit dialog for exit
    time/price/reason (times are UTC).
- **History** — date-range filtered sections: all trades (open rows
  highlighted), news (filterable by tag and effect), VIX readings as a
  line chart, and the evolution of the nearest FOMC meeting's top rate
  buckets across recorded snapshots.
- **Record** — the round **+** button (bottom-right, every page) opens an
  overlay with tabs: News, Trade Journal (asset ticker from the database,
  entry/exit price), Analyze & Thoughts, VIX, Fear & Greed, Economic
  Reports (with country), FOMC (paste the rate-probability markdown
  table; `server/rate_table.py` parses and stores it).

New pages: add a `<Route>` in `web/src/App.tsx` and a link in the header
nav — the Record button lives outside the router so it appears everywhere.

## Schema (MySQL, normalized)

`news` ⟷ `tags` via `news_tags`; `news` ⟷ `assets` via `news_effects`;
`assets` belong to `asset_categories` (kind: hard/soft — Commodities are
hard; Indices/Forex/Crypto/Bonds/Derivatives/Stock are soft);
`trades` (FK → assets, entry/exit price); `econ_reports` (FK →
`countries`, seeded and user-extendable); `vix_readings`,
`fear_greed_readings`, `thoughts`; `rate_snapshots` 1-* `rate_probs`
(meeting date × bps bucket).

Schema changes are applied automatically on startup: `server/migrate.py`
creates missing tables and adds missing (nullable/defaulted) columns, so
an existing database upgrades in place.

All timestamps are stored naive-UTC, matching the CSV market data.
