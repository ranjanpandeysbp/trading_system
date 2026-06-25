# Indian Stock Paper Trading — Backend

FastAPI backend for paper trading, strategy scanning, and backtesting on Indian equities.

## Setup

```bash
cd be
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
python run.py
```

API docs: http://localhost:8000/docs

## Optional: Groww API

Groww data fetching mirrors `truebacktesting/heatmap.py`:

1. **Authenticated API** — set bearer token in Manage Settings (historical candles + live quotes)
2. **Public charting** — works without token via Groww charting service
3. **yfinance fallback** — used automatically if Groww returns no data

Select **Groww** as data provider in Manage Settings. Token is optional but recommended for live quotes and higher rate limits.

## Modules

| Module | Path |
|--------|------|
| Strategies | `app/strategies/` |
| Data providers | `app/data/` |
| Scanner | `app/services/scanner_service.py` |
| Backtester | `app/services/backtest_service.py` |
| Paper trading | `app/services/paper_trading_service.py` |
| Settings | `app/services/settings_service.py` |
