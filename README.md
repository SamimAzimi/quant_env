# quant_env

A framework to analyze and profile market behavior across multiple timeframes,
backtest trading strategies, and visualize the results.

## Layout & conventions

```
config/       All configuration. Import via `from config.config import X`.
              Split into: paths, instruments, data_sources, dashboard_meta,
              sessions, telegram, secrets (env-loaded), API.
libs/         Reusable engine code: data loading/downloading, indicators,
              market statistics & profiling, cost model, account simulator,
              performance analytics, result store, dashboards.
strategies/   Strategy implementations (injected into the pipeline).
              strategies/archive/ holds retired experiments.
tests/        Test suite (pytest).
output/       All generated reports/HTML land here. Gitignored.
data/         Downloaded market data (gitignored; override QUANT_DATA_DIR).
DB/           Backtest result stores (gitignored; override QUANT_DB_DIR).
tools/        Standalone utilities (telegram forwarder).
server/       Market Preparation web app backend (FastAPI + MySQL).
web/          Market Preparation web app frontend (React + Vite).
docs/         Notes and process docs (see docs/MarketPrep.md for the web app).
```

Rules the code follows (and new code should too):

- **Config** comes from `config/` — import from `config.config`, never
  hardcode paths, symbols, or keys in `libs/`.
- **Secrets** come from the environment / `.env` (see `.env.example`).
  Never commit keys, tokens, or `.session` files.
- **Outputs** go to `output/` — `config.paths.output_path("name.html")`
  resolves any relative report name into it.
- **Tests** live in `tests/`.

## Setup

```bash
pip install -e .                       # core engine
pip install -e ".[data,dashboard,dev]" # + downloader, dashboards, pytest

cp .env.example .env                   # then fill in your API keys
```

The editable install makes `libs`, `config`, and `strategies` importable
from anywhere (notebooks, streamlit, scripts) with no `sys.path` tricks.

## Usage

Run a backtest through the pipeline (strategy is injected):

```python
from libs.pipeline import PipelineConfig, run_pipeline
from strategies.session_sigma_strategy import SessionSigmaStrategy

res = run_pipeline(PipelineConfig(asset="XAUUSD", asset_class="Commodities",
                                  timeframe="5m", cost_symbol="XAUUSD",
                                  strategy_cls=SessionSigmaStrategy))
res.metrics
```

Market character dashboard:

```python
from libs.market_dashboard import build_dashboard
build_dashboard({"EURUSD": df}, output="eurusd_dashboard.html")  # → output/
```

Backtest results dashboard:

```bash
streamlit run libs/dashboard.py
```

Update market data (needs `POLYGON_API_KEY` in `.env`):

```bash
python libs/data_manager.py
```

Tests:

```bash
pytest
```

## Paths

Defaults are anchored to the repo root and overridable via env vars:
`QUANT_DATA_DIR`, `QUANT_DB_DIR`, `QUANT_OUTPUT_DIR`, `BACKTEST_DB`.

## ⚠️ Security note

Earlier commits of this repository contained live API keys, Telegram
credentials, and session files. They have been removed from the working
tree, but they remain in git history — **rotate all of those credentials**
and consider purging history with `git filter-repo`.
