# Indian Stock Paper Trading

Demo paper trading platform for Indian equities with strategy scanner, backtester, and 15 rule-based technical strategies.

## Architecture

```
indian_stock_trading/
├── be/          FastAPI backend (Python 3.12+)
└── fe/          React frontend (Vite + TypeScript)
```

## Quick Start

### Backend

```bash
cd be
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

API: http://localhost:8000/docs

### Frontend

```bash
cd fe
npm install
npm run dev
```

App: http://localhost:5173

## Features

- **15 Strategies** — 5 scalping, 5 intraday, 5 swing (Indian market)
- **Strategy Scanner** — scan tickers × strategies × timeframes → BUY/SELL with SL%, TP%, confidence%
- **Backtester** — transparent historical evaluation with cost modelling
- **Paper Trading** — virtual portfolio with order execution
- **Data Providers** — yfinance (default) or Groww (REST + public charting, optional bearer token)

## Disclaimer

Educational/technical demo only — not investment advice. Backtest ≠ live performance.
