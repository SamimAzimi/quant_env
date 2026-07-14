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

The header carries a main menu: **Market Prep** (default), **History**, and
**Asset Stats**.

"Yesterday" everywhere means the **trading-day window**: Tokyo session
open → New York session close. Sessions come from
`libs/market_sessions.py` — local wall-clock hours per financial centre
converted through the IANA tz database — so every window is DST-correct
across all of history (the NY close is 21:00 UTC in summer, 22:00 in
winter; London shifts 07:00↔08:00). The four major sessions (Sydney,
Tokyo, London, New York) are shaded as background bands on the candle
charts and the log-return chart, and the session high/low key levels are
computed over exactly those shaded regions. Telegram session alerts fire
on cron triggers in each centre's own timezone, so they shift with DST
too.

- **Market Prep** (default page) — a date picker in the page toolbar
  replays any past day: every section behaves as if that day were today.
  Sections:
  - *Sentiment*: Fear & Greed gauge + VIX, from readings recorded the
    **previous UTC day** (record today → shows tomorrow).
  - *Macro*: the selected day's economic reports (plus still-pending
    ones from earlier days when viewing today), grouped by country
    (expanded by default, collapsible per country) with inline edit of
    Actual and Beat/Miss.
  - *Rate probabilities*: latest recorded FedWatch table as bars — top 3
    buckets per meeting, the rest behind "see more…" — with the previous
    day's value marked for comparison.
  - *Pre-day stats*: color-coded cumulative log returns over yesterday,
    timeframe selector (default 15m), any assets from the CSV store.
  - *Charts*: yesterday's candles for NDX, XAUUSD, XAGUSD, USDJPY, EURUSD
    with pre-day high/low and per-session high/low price lines.
  - *To watch*: all **open** stories, with related follow-ups nested
    recursively under their parent story. Click a story to expand its
    details; Edit opens the full story editor (fields, tags, effects, and
    parent relationships); Done ✓ closes it. Effect and tag labels sit
    beside each title.
  - *Today news*: today's recorded news with effect/tag chips; yesterday's
    news scrolls in a ticker at the top.
  - *Trades*: the day's + open trades — open ones are highlighted with an
    accent border, closed ones dimmed — with an edit dialog for exit
    time/price/reason (times are UTC).
- **History** — date-range filtered sections: all trades (open rows
  highlighted); news with fuzzy title search (select a story to see its
  full related thread), recursive **story groups** (connected stories in
  the range, named after the earliest primary story) with an optional
  graph view (clickable nodes) and a news-on-candles view (pick timeframe
  + asset; each story is pinned to the candle nearest its publish time) —
  every story shown in History is fully editable in place;
  VIX readings as a line chart; and the evolution of the nearest FOMC
  meeting's top rate buckets across recorded snapshots.
- **Asset Stats** — pick a ticker and an intraday timeframe; the backend
  (`server/asset_stats.py`) studies every trading day of history and returns:
  - *Session return distributions* for Tokyo, London, New York, and the
    full trading day — histogram with μ and ±1σ/±2σ band lines, plus skew
    and empirical tail probabilities. Session return = `ln(close/open)`.
  - *Session transitions* (Tokyo→London, London→New York, New York→London
    overnight): the reference session's return distribution sets ±1σ/±2σ
    bands; the card shows, up and down, P(the trigger session closes beyond
    ±1σ), P(it reaches the reference ±2σ), and the key conditional
    **P(reach 2σ | breakout)** — plus "clean move" quality for the 1σ→2σ
    segment: path efficiency `|net| / Σ|bar move|`, mean adverse excursion
    (in σ), and bar count. Everything is on a cumulative-log-return axis
    anchored at the reference session's open; sessions are DST-correct
    (`libs/market_sessions.py`).
  - *Day-over-day*: the daily return distribution and bands, the intraday
    continuation (P(2σ | closed beyond 1σ) and cleanliness anchored at the
    day open), and the day-to-day conditional transition (given the
    previous day closed beyond ±1σ, what the current day does).
- **Record** — the round **+** button (bottom-right, every page) opens an
  overlay with tabs: News (title, details, role — primary / supporting /
  contradicting / duplicate / update —, source with inline add, publish
  time, tags, effects, open/close status, and fuzzy-search linking to
  related stories), Trade Journal (asset ticker from the database,
  entry/exit price), Analyze & Thoughts, VIX, Fear & Greed, Economic
  Reports (with country), FOMC (paste the rate-probability markdown
  table; `server/rate_table.py` parses and stores it).

New pages: add a `<Route>` in `web/src/App.tsx` and a link in the header
nav — the Record button lives outside the router so it appears everywhere.

## Schema (MySQL, normalized)

`news` (role, open/close status, publish_time, FK → `sources`) ⟷ `tags`
via `news_tags`; ⟷ `assets` via `news_effects`; stories link to each
other through `news_relationships` (parent → child, cycle-checked);
`assets` belong to `asset_categories` (kind: hard/soft — Commodities are
hard; Indices/Forex/Crypto/Bonds/Derivatives/Stock are soft);
`trades` (FK → assets, entry/exit price); `econ_reports` (FK →
`countries`, seeded and user-extendable); `vix_readings`,
`fear_greed_readings`, `thoughts`; `rate_snapshots` 1-* `rate_probs`
(meeting date × bps bucket). Upgrading databases keep their watch list:
the old `to_watch` flag backfills `status` (watched → open).

Schema changes are applied automatically on startup: `server/migrate.py`
creates missing tables and adds missing (nullable/defaulted) columns, so
an existing database upgrades in place.

All timestamps are stored naive-UTC, matching the CSV market data.
