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
- **Asset Stats** — pick a ticker → timeframe; the available date range is
  shown and used in full unless you narrow it (From/To), then Analyze. The
  backend studies every trading day in the range, session-based around the
  three majors and their overlaps, DST-correct (`libs/market_sessions.py`):
  - *Session & overlap return distributions* (`server/asset_stats.py`) —
    histograms (μ and ±0.5σ…±4σ band lines in 0.5σ steps, skew, tail
    probabilities) for each segment: Tokyo, Tokyo∖London, Tokyo∩London, London, London∖Tokyo,
    London∖NY, London∩NY, New York, New York∖London, and the full day.
    Segment return = `ln(close/open)` at the selected timeframe.
  - *Band-behaviour study* (`server/band_behavior.py`, A–G) — for each
    consecutive session pair (S_t → S_{t+1}) of the five-part partition:
    μ_t/σ_t from all S_t candle closes define 0.25σ bands to ±4σ (34 bands
    incl. open tails); every S_{t+1} close is banded. Per pair, tabbed:
    **A** band-occupancy distribution vs the normal model; **B** first-touch
    Kaplan–Meier survival curves per band (never-touch days censored at
    session end); **C** path geometry (candles to touch, adverse excursion
    in bands, oscillation share, time inside, depth); **D** 34×34 band
    transition heatmap + P(toward centre) per band; **E** escape velocity
    (signed/absolute bands-per-candle on exits, share toward centre);
    **F** inferential tests with H₀/statistic/p/plain-language reading —
    Kolmogorov–Smirnov and Anderson–Darling on z vs N(0,1), χ² band
    occupancy vs the normal expectation, Wald–Wolfowitz runs tests
    (above/below μ, outer-band hits; Stouffer-combined across days),
    Mann–Whitney U (inner vs outer first-touch times and escape speeds);
    **G** a synthesis verdict (structured / mixed / noise-like). Beyond the
    four adjacent-chain pairs, the study also reports seven extra
    reference→New-York pairs (`EXTRA_PAIRS`): Tokyo (solo), Tokyo ∩ London
    and London (solo) each measured against **New York (solo)** and against
    **New York (full)** — the whole NY session, open → close — plus **New
    York (solo) previous day → next day** (day-over-day). The study can be
    **saved** (`saved_reports` table) for later or **copied as JSON** for
    another AI prompt; saved studies reload from the page.
- **Strategies** — browse backtest runs persisted by the pipeline. Every
  `run_pipeline(...)` saves into the app database (the legacy
  sqlite/parquet ResultStore and its Streamlit dashboard are removed; the
  pipeline prints the exact database URL each run was saved to, which must
  match this server's `MARKET_PREP_DB_URL` — both sides load the project
  `.env`, so they agree by default). Normalized schema: `bt_runs`,
  `bt_metrics` (key/value KPIs), `bt_trades` (typed ledger + strategy
  extras as JSON), `bt_equity`, `bt_frames` (exit reasons, monthly
  returns, rolling/by-period breakdowns, costed, detail frames). The page
  carries full old-dashboard parity: composite score + rank across runs,
  the headline KPI strip, equity + drawdown charts, exit-reason / monthly
  / rolling-Sharpe / rolling-win-rate / by-session / by-day / by-hour
  charts, long-vs-short split, a Monte Carlo bootstrap of trade returns
  (percentiles, prob. of profit, max-DD distribution, histogram), the
  cost summary, every metric in the grouped panels from
  `config/dashboard_meta.py`, run metadata, and the paginated trade
  ledger.
- **Day & Quant** — day-over-day behaviour plus a hedge-fund-style
  character report (`server/quant_stats.py`), same ticker→timeframe→date-
  range flow:
  - *Performance & risk* (from daily returns): annualised return/vol,
    Sharpe, Sortino, Calmar, max drawdown (+ duration, current), VaR/CVaR
    at 95/99, win rate, profit factor, tail ratio, best/worst day.
  - *Daily return distribution* (μ/σ/skew, ±0.5/1/1.5/2σ) and *intraday
    continuation* — the full breakout×target matrix and per-segment clean
    move anchored at the day open (day = Tokyo open→NY close).
  - *Day-to-day transition* (given the previous day's σ-bucket → next
    day), *overnight gap* analysis (size, fill probability, continuation),
    and *streak* statistics.
  - *Desk card* (`libs/desk_card.py`) — the distribution and volatility
    desk cards (directional bias, vol-target sizing, VaR/ES, Kelly and
    tail-capped leverage, option-hedge estimate, overnight-gap split, vol
    regime + cones, GARCH glide path, ATR unit sizing), rendered as the
    monospace cards plus a collapsible raw-numbers view.
  - *Character report + full market metrics* (`libs/market_stats.py`) —
    the text `report()` and the complete `market_metrics()` dict (meta,
    distribution, desk, volatility, mean-reversion, sessions, calendar,
    probability, regimes), rendered block by block with every nested
    section expandable — nothing curated away. Needs scipy/scikit-learn
    (core deps); degrades gracefully with a note if they are missing.
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
