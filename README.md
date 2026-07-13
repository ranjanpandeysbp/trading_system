# Indian Stock Paper Trading

Demo paper trading platform for Indian equities with strategy scanner, backtester, and 15 rule-based technical strategies.

npm run dev -- --host 0.0.0.0
# OR if using npx directly
npx vite --host 0.0.0.0

pm2 delete all
(Or if you have other unrelated PM2 apps running that you want to keep, just run pm2 delete 0 1)

Step 2: Start a single instance with the host flag

Bash
pm2 start npm --name "my-vite-app" -- run dev -- --host
Step 3: Find out exactly which port it is using
Run the log command:

Bash
pm2 logs my-vite-app

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
