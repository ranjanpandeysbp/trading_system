"""
hedging_toolkit_engine.py
-------------------------
Multi-timeframe hedging toolkit for Groww (India), US equities, and crypto.

Techniques: Beta hedge, Pairs trade, Delta hedge (puts), Inverse ETF,
            Crypto min-variance correlation hedge, Portfolio risk metrics.
"""

from __future__ import annotations

import logging
from math import exp, log, sqrt
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import norm, pearsonr

from app.market_pulse.ticker_utils import is_crypto_market, is_india_market, is_us_market
from app.market_pulse.us_market_yfinance import us_symbol_to_yf
from app.market_pulse.nse_index_yfinance import (
    NSE_INDEX_YF_TICKERS,
    index_yf_candidates,
    normalize_index_name,
    stock_symbol_to_yf,
)

logger = logging.getLogger(__name__)

HEDGE_ROLES: tuple[str, ...] = ("LTF", "MTF", "HTF")

# Chart timeframe → (yfinance period, interval)
TF_YF_CONFIG: dict[str, tuple[str, str]] = {
    "5m": ("60d", "5m"),
    "15m": ("60d", "15m"),
    "30m": ("60d", "30m"),
    "1h": ("730d", "1h"),
    "4h": ("730d", "1h"),
    "1d": ("2y", "1d"),
    "1w": ("5y", "1wk"),
    "1wk": ("5y", "1wk"),
}

HEDGE_TF_OPTIONS: dict[str, list[str]] = {
    "groww": ["15m", "1h", "4h", "1d", "1wk"],
    "us": ["1h", "4h", "1d", "1wk"],
    "crypto": ["5m", "15m", "1h", "4h", "1d"],
}

DEFAULT_HEDGE_TFS: dict[str, dict[str, str]] = {
    "groww": {"LTF": "1h", "MTF": "1d", "HTF": "1wk"},
    "us": {"LTF": "1h", "MTF": "1d", "HTF": "1wk"},
    "crypto": {"LTF": "15m", "MTF": "1h", "HTF": "1d"},
}

# Legacy aliases (calendar lookbacks — prefer HEDGE_ROLES + chart TFs)
MTF_HEDGE_PERIODS: tuple[str, ...] = HEDGE_ROLES
MTF_PERIOD_LABELS: dict[str, str] = {
    "LTF": "LTF — Low timeframe",
    "MTF": "MTF — Medium timeframe",
    "HTF": "HTF — High timeframe",
}


def market_tf_bucket(market: str) -> str:
    if is_crypto_market(market):
        return "crypto"
    if is_us_market(market):
        return "us"
    return "groww"


def hedge_tf_options(market: str) -> list[str]:
    return HEDGE_TF_OPTIONS.get(market_tf_bucket(market), HEDGE_TF_OPTIONS["groww"])


def default_hedge_timeframes(market: str) -> dict[str, str]:
    return dict(DEFAULT_HEDGE_TFS.get(market_tf_bucket(market), DEFAULT_HEDGE_TFS["groww"]))


def timeframe_label(tf: str) -> str:
    cfg = TF_YF_CONFIG.get(tf, ("6mo", "1d"))
    return f"{tf} ({cfg[1]} bars · {cfg[0]})"


def bars_per_year_for_tf(tf: str) -> float:
    mapping = {
        "5m": 252 * 75,
        "15m": 252 * 25,
        "30m": 252 * 13,
        "1h": 252 * 6.5,
        "4h": 252 * 1.625,
        "1d": 252,
        "1w": 52,
        "1wk": 52,
    }
    return mapping.get(tf, 252)

INVERSE_ETF_MAP: dict[str, str] = {
    "SPY": "SH",
    "QQQ": "PSQ",
    "IWM": "RWM",
    "DIA": "DOG",
    "^GSPC": "SH",
    "^IXIC": "PSQ",
    "^NDX": "PSQ",
}

US_BENCHMARK_OPTIONS = ["SPY", "QQQ", "IWM", "DIA"]
INDIA_BENCHMARK_OPTIONS = ["NIFTY 50", "NIFTY BANK", "NIFTY IT", "SENSEX"]
CRYPTO_PRIMARY_DEFAULT = "BTC-USD"
CRYPTO_HEDGE_DEFAULT = "ETH-USD"

# Tradeable index ETFs for India hedging (sell units to offset beta)
INDIA_INDEX_ETF_MAP: dict[str, str] = {
    "NIFTY 50": "NIFTYBEES.NS",
    "NIFTY BANK": "BANKBEES.NS",
    "NIFTY IT": "ITBEES.NS",
    "SENSEX": "SETFSN50.BO",
    "^NSEI": "NIFTYBEES.NS",
    "^NSEBANK": "BANKBEES.NS",
    "^CNXIT": "ITBEES.NS",
    "^BSESN": "SETFSN50.BO",
}


def crypto_symbol_to_yf(symbol: str) -> str:
    """Map CoinDCX-style symbol to Yahoo crypto ticker."""
    raw = (symbol or "").strip().upper()
    raw = raw.replace("B-", "").replace("_", "-")
    if raw.endswith("USDT"):
        base = raw[:-4]
        return f"{base}-USD"
    if "-USD" in raw or raw.endswith("-USD"):
        return raw
    return f"{raw}-USD"


def india_symbol_to_yf(symbol: str) -> str:
    """Map NSE equity or index label to Yahoo Finance ticker."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return sym
    if sym in NSE_INDEX_YF_TICKERS:
        return NSE_INDEX_YF_TICKERS[sym]
    canonical = normalize_index_name(sym)
    if canonical in NSE_INDEX_YF_TICKERS:
        return NSE_INDEX_YF_TICKERS[canonical]
    cands = index_yf_candidates(sym)
    if cands:
        return cands[0]
    if sym.startswith("^") or sym.endswith((".NS", ".BO")):
        return sym
    return stock_symbol_to_yf(sym)


def resolve_benchmark_yf(benchmark: str, market: str) -> str:
    """Index symbol used for beta / correlation calculations."""
    if is_crypto_market(market):
        return benchmark
    if is_us_market(market):
        return us_symbol_to_yf(benchmark)
    return india_symbol_to_yf(benchmark)


def resolve_hedge_instrument_yf(benchmark: str, market: str) -> str:
    """Tradeable hedge leg (inverse ETF US, index ETF India)."""
    if is_us_market(market):
        bench = us_symbol_to_yf(benchmark)
        return INVERSE_ETF_MAP.get(benchmark, INVERSE_ETF_MAP.get(bench, "SH"))
    if is_india_market(market):
        key = (benchmark or "").strip().upper()
        yf_bench = india_symbol_to_yf(benchmark)
        return (
            INDIA_INDEX_ETF_MAP.get(key)
            or INDIA_INDEX_ETF_MAP.get(yf_bench)
            or INDIA_INDEX_ETF_MAP.get("NIFTY 50")
            or "NIFTYBEES.NS"
        )
    return benchmark


def resolve_yf_ticker(symbol: str, market: str) -> str:
    sym = (symbol or "").strip().upper()
    if not sym:
        return sym
    if is_crypto_market(market):
        return crypto_symbol_to_yf(sym)
    if is_us_market(market):
        return us_symbol_to_yf(sym)
    return india_symbol_to_yf(sym)


def _fmt_money(amount: float, market: str) -> str:
    cur = currency_for_market(market)
    if cur == "₹":
        return f"₹{amount:,.0f}"
    return f"${amount:,.0f}"


def currency_for_market(market: str) -> str:
    return "$" if is_crypto_market(market) or is_us_market(market) else "₹"


def fetch_prices(
    tickers: list[str],
    period: str = "6mo",
    interval: str = "1d",
    timeframe: str | None = None,
) -> pd.DataFrame:
    """Download adjusted closing prices (optionally via chart timeframe key)."""
    if timeframe and timeframe in TF_YF_CONFIG:
        period, interval = TF_YF_CONFIG[timeframe]
    unique = list(dict.fromkeys(t for t in tickers if t))
    if not unique:
        return pd.DataFrame()
    try:
        raw = yf.download(
            unique,
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as exc:
        logger.warning("fetch_prices failed: %s", exc)
        return pd.DataFrame()
    if raw is None or raw.empty:
        return pd.DataFrame()

    if len(unique) == 1:
        sym = unique[0]
        if isinstance(raw.columns, pd.MultiIndex):
            if "Close" in raw.columns.get_level_values(0):
                series = raw["Close"].iloc[:, 0] if raw["Close"].ndim > 1 else raw["Close"]
            else:
                series = raw.iloc[:, 0]
        else:
            series = raw["Close"] if "Close" in raw.columns else raw.iloc[:, 0]
        out = pd.DataFrame({sym: pd.to_numeric(series, errors="coerce")})
        return out.dropna(how="all")

    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw["Close"].copy()
    else:
        prices = raw.copy()
    prices = prices.dropna(how="all")
    if isinstance(prices, pd.Series):
        prices = prices.to_frame(name=unique[0])
    return prices


def black_scholes_put_delta(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = (log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt(T))
    return norm.cdf(d1) - 1


def beta_hedge(
    portfolio_ticker: str,
    benchmark: str = "SPY",
    portfolio_value: float = 100_000,
    timeframe: str = "1d",
    market: str = "",
    hedge_instrument_yf: str | None = None,
) -> dict[str, Any] | None:
    bench_yf = benchmark
    prices = fetch_prices([portfolio_ticker, bench_yf], timeframe=timeframe)
    if prices.empty or portfolio_ticker not in prices.columns or bench_yf not in prices.columns:
        return None
    sub = prices[[portfolio_ticker, bench_yf]].dropna()
    if len(sub) < 10:
        return None

    returns = sub.pct_change().dropna()
    cov = returns.cov().iloc[0, 1]
    var = returns[bench_yf].var()
    if var == 0 or pd.isna(var):
        return None
    beta = float(cov / var)

    bench_price = float(sub[bench_yf].iloc[-1])
    exec_yf = hedge_instrument_yf or bench_yf
    if exec_yf != bench_yf:
        exec_df = fetch_prices([exec_yf], timeframe=timeframe)
        exec_price = (
            float(exec_df[exec_yf].iloc[-1])
            if not exec_df.empty and exec_yf in exec_df.columns
            else bench_price
        )
    else:
        exec_price = bench_price

    hedge_units = (portfolio_value * beta) / exec_price if exec_price else 0
    hedge_cost = hedge_units * exec_price

    if is_india_market(market):
        verb = "SELL"
        instr = exec_yf.replace(".NS", "").replace(".BO", "")
        strategy = "Beta Hedge (Sell Index ETF)"
    else:
        verb = "SHORT"
        instr = exec_yf
        strategy = "Beta Hedge (Short Index)"

    return {
        "strategy": strategy,
        "timeframe": timeframe,
        "timeframe_label": timeframe_label(timeframe),
        "portfolio": portfolio_ticker,
        "benchmark": bench_yf,
        "hedge_instrument": exec_yf,
        "beta": round(beta, 4),
        "portfolio_value": portfolio_value,
        "bench_price": round(bench_price, 2),
        "exec_price": round(exec_price, 2),
        "hedge_units": round(hedge_units, 2),
        "hedge_cost": round(hedge_cost, 2),
        "interpretation": (
            f"{verb} {round(hedge_units, 2)} units of {instr} "
            f"(≈ {_fmt_money(hedge_cost, market)} notional) to neutralise "
            f"beta={round(beta, 2)} vs {bench_yf} on {timeframe_label(timeframe)}."
        ),
    }


def pairs_trade_hedge(
    ticker_a: str,
    ticker_b: str,
    position_value: float = 50_000,
    timeframe: str = "1d",
) -> dict[str, Any] | None:
    prices = fetch_prices([ticker_a, ticker_b], timeframe=timeframe)
    if prices.empty:
        return None
    prices = prices[[c for c in [ticker_a, ticker_b] if c in prices.columns]].dropna()
    if len(prices) < 15 or ticker_a not in prices.columns or ticker_b not in prices.columns:
        return None

    log_a = np.log(prices[ticker_a].astype(float))
    log_b = np.log(prices[ticker_b].astype(float))
    hedge_ratio = float(np.polyfit(log_b, log_a, 1)[0])

    spread = log_a - hedge_ratio * log_b
    spread_std = float(spread.std())
    if spread_std == 0:
        return None
    z_score = float((spread.iloc[-1] - spread.mean()) / spread_std)

    price_a = float(prices[ticker_a].iloc[-1])
    price_b = float(prices[ticker_b].iloc[-1])
    ret_a = prices[ticker_a].pct_change().dropna()
    ret_b = prices[ticker_b].pct_change().dropna()
    aligned = pd.concat([ret_a, ret_b], axis=1).dropna()
    if len(aligned) < 5:
        corr = 0.0
    else:
        corr, _ = pearsonr(aligned.iloc[:, 0], aligned.iloc[:, 1])

    units_b = round((position_value * hedge_ratio) / price_b, 2) if price_b else 0

    if z_score < -1.5:
        signal = "ENTER: Long A / Short B — spread is cheap"
    elif z_score > 1.5:
        signal = "ENTER: Short A / Long B — spread is rich"
    else:
        signal = "HOLD — spread within normal range"

    return {
        "strategy": "Pairs Trade (Stat-Arb) Hedge",
        "timeframe": timeframe,
        "timeframe_label": timeframe_label(timeframe),
        "ticker_a": ticker_a,
        "ticker_b": ticker_b,
        "hedge_ratio": round(hedge_ratio, 4),
        "correlation": round(float(corr), 4),
        "z_score": round(z_score, 4),
        "price_a": round(price_a, 2),
        "price_b": round(price_b, 2),
        "units_b_to_short": units_b,
        "signal": signal,
        "spread_mean": round(float(spread.mean()), 6),
        "spread_std": round(spread_std, 6),
        "interpretation": (
            f"Hedge ratio = {round(hedge_ratio, 2)}: for every 1 unit of {ticker_a} long, "
            f"short {round(hedge_ratio, 2)} units of {ticker_b}. "
            f"z-score = {round(z_score, 2)} ({timeframe_label(timeframe)}). {signal}"
        ),
    }


def delta_hedge_options(
    ticker: str,
    portfolio_value: float = 100_000,
    strike_pct: float = 0.95,
    days_to_expiry: int = 30,
    risk_free_rate: float = 0.05,
    period: str = "6mo",
    timeframe: str = "1d",
    market: str = "",
) -> dict[str, Any] | None:
    prices = fetch_prices([ticker], timeframe=timeframe)
    if prices.empty or ticker not in prices.columns:
        return None
    series = prices[ticker].dropna()
    if len(series) < 10:
        return None

    S = float(series.iloc[-1])
    rets = series.pct_change().dropna()
    sigma = float(rets.std() * np.sqrt(bars_per_year_for_tf(timeframe))) if len(rets) else 0.2
    sigma = max(sigma, 0.05)
    K = round(S * strike_pct, 2)
    T = days_to_expiry / 365

    delta = black_scholes_put_delta(S, K, T, risk_free_rate, sigma)
    shares_held = portfolio_value / S if S else 0
    contracts_needed = abs(shares_held / (delta * 100)) if delta else 0

    cur = currency_for_market(market)
    strike_label = f"{cur}{K:,.2f}" if is_india_market(market) else f"${K}"
    lot_note = " Verify NSE F&O lot size before trading." if is_india_market(market) else ""

    return {
        "strategy": "Delta Hedge via Put Options",
        "timeframe": timeframe,
        "timeframe_label": timeframe_label(timeframe),
        "ticker": ticker,
        "spot_price": round(S, 2),
        "strike_price": K,
        "days_to_expiry": days_to_expiry,
        "implied_vol_ann": f"{round(sigma * 100, 2)}%",
        "put_delta": round(delta, 4),
        "shares_held": round(shares_held, 2),
        "put_contracts_buy": round(contracts_needed, 2),
        "interpretation": (
            f"BUY ≈ {round(contracts_needed, 0):.0f} put contracts "
            f"(strike {strike_label}, {days_to_expiry}d expiry) on {ticker} "
            f"to delta-hedge {round(shares_held, 0):.0f} shares ({timeframe_label(timeframe)}). "
            f"Put delta = {round(delta, 3)}.{lot_note}"
        ),
    }


def inverse_etf_hedge(
    portfolio_ticker: str,
    benchmark: str = "SPY",
    portfolio_value: float = 100_000,
    hedge_pct: float = 0.50,
    timeframe: str = "1d",
    market: str = "",
    hedge_instrument: str | None = None,
) -> dict[str, Any] | None:
    hedge_notional = portfolio_value * hedge_pct

    if is_india_market(market):
        etf = hedge_instrument or resolve_hedge_instrument_yf(benchmark, market)
        prices = fetch_prices([etf], timeframe=timeframe)
        if prices.empty or etf not in prices.columns:
            return None
        etf_price = float(prices[etf].dropna().iloc[-1])
        units = round(hedge_notional / etf_price, 2) if etf_price else 0
        etf_label = etf.replace(".NS", "").replace(".BO", "")
        return {
            "strategy": "Index ETF Hedge (Sell ETF)",
            "timeframe": timeframe,
            "timeframe_label": timeframe_label(timeframe),
            "portfolio": portfolio_ticker,
            "benchmark": benchmark,
            "hedge_etf": etf,
            "hedge_pct": f"{int(hedge_pct * 100)}%",
            "hedge_notional": round(hedge_notional, 2),
            "etf_price": round(etf_price, 2),
            "units_to_sell": units,
            "interpretation": (
                f"SELL {units} units of {etf_label} (≈ {_fmt_money(hedge_notional, market)}) "
                f"to hedge {int(hedge_pct * 100)}% of {portfolio_ticker} vs {benchmark} "
                f"({timeframe_label(timeframe)}). Cash-settled index ETF overlay — no F&O margin."
            ),
        }

    bench_yf = benchmark
    inverse_etf = hedge_instrument or INVERSE_ETF_MAP.get(benchmark, INVERSE_ETF_MAP.get(bench_yf, "SH"))
    prices = fetch_prices([inverse_etf], timeframe=timeframe)
    if prices.empty or inverse_etf not in prices.columns:
        return None
    inv_price = float(prices[inverse_etf].iloc[-1])
    units = round(hedge_notional / inv_price, 2) if inv_price else 0

    return {
        "strategy": "Inverse ETF Hedge",
        "timeframe": timeframe,
        "timeframe_label": timeframe_label(timeframe),
        "portfolio": portfolio_ticker,
        "benchmark": benchmark,
        "inverse_etf": inverse_etf,
        "hedge_pct": f"{int(hedge_pct * 100)}%",
        "hedge_notional": round(hedge_notional, 2),
        "inv_etf_price": round(inv_price, 2),
        "units_to_buy": units,
        "interpretation": (
            f"BUY {units} units of {inverse_etf} (≈ {_fmt_money(hedge_notional, market)}) "
            f"to hedge {int(hedge_pct * 100)}% of {portfolio_ticker} vs {benchmark} "
            f"drawdowns ({timeframe_label(timeframe)}). No margin/shorting required."
        ),
    }


def crypto_hedge(
    primary: str = "BTC-USD",
    hedge_asset: str = "ETH-USD",
    portfolio_value: float = 50_000,
    timeframe: str = "1d",
) -> dict[str, Any] | None:
    prices = fetch_prices([primary, hedge_asset], timeframe=timeframe)
    if prices.empty:
        return None
    prices = prices.dropna()
    if len(prices) < 10 or primary not in prices.columns or hedge_asset not in prices.columns:
        return None

    returns = prices.pct_change().dropna()
    corr, _ = pearsonr(returns[primary], returns[hedge_asset])
    sigma_p = returns[primary].std()
    sigma_h = returns[hedge_asset].std()
    if sigma_h == 0 or pd.isna(sigma_h):
        return None
    hedge_ratio = float(corr * (sigma_p / sigma_h))

    price_h = float(prices[hedge_asset].iloc[-1])
    units_short = round((portfolio_value * hedge_ratio) / price_h, 4) if price_h else 0
    hedge_cost = round(units_short * price_h, 2)

    return {
        "strategy": "Crypto Min-Variance Hedge",
        "timeframe": timeframe,
        "timeframe_label": timeframe_label(timeframe),
        "primary": primary,
        "hedge_asset": hedge_asset,
        "correlation": round(float(corr), 4),
        "hedge_ratio": round(hedge_ratio, 4),
        "price_hedge": round(price_h, 2),
        "units_short": units_short,
        "hedge_cost": hedge_cost,
        "interpretation": (
            f"SHORT {units_short} {hedge_asset} "
            f"(≈ ${hedge_cost:,}) to hedge ${portfolio_value:,} in {primary} "
            f"({timeframe_label(timeframe)}). "
            f"Correlation = {round(corr, 2)}, hedge ratio = {round(hedge_ratio, 2)}."
        ),
    }


def portfolio_risk(
    tickers: list[str],
    weights: list[float],
    portfolio_value: float = 100_000,
    timeframe: str = "1d",
) -> dict[str, Any] | None:
    prices = fetch_prices(tickers, timeframe=timeframe)
    if prices.empty:
        return None
    cols = [t for t in tickers if t in prices.columns]
    if not cols:
        return None
    returns = prices[cols].pct_change().dropna()
    if len(returns) < 10:
        return None

    w = np.array(weights[: len(cols)], dtype=float)
    if w.sum() <= 0:
        w = np.ones(len(cols)) / len(cols)
    else:
        w = w / w.sum()

    mu = returns.mean().values
    cov = returns.cov().values
    port_ret = float(np.dot(w, mu))
    port_var = float(w @ cov @ w)
    port_vol = float(np.sqrt(port_var))
    ann_vol = port_vol * np.sqrt(bars_per_year_for_tf(timeframe))
    ann_ret = port_ret * bars_per_year_for_tf(timeframe)
    sharpe = ann_ret / ann_vol if ann_vol else 0

    var_95 = portfolio_value * (port_ret - 1.645 * port_vol)
    cvar_95 = portfolio_value * (port_ret - 2.063 * port_vol)

    return {
        "strategy": "Portfolio Risk Metrics",
        "timeframe": timeframe,
        "timeframe_label": timeframe_label(timeframe),
        "tickers": cols,
        "weights": [round(float(w_i), 4) for w_i in w],
        "ann_return_pct": f"{round(ann_ret * 100, 2)}%",
        "ann_vol_pct": f"{round(ann_vol * 100, 2)}%",
        "sharpe_ratio": round(sharpe, 4),
        "daily_var_95": f"-${abs(round(var_95, 2)):,.2f}",
        "daily_cvar_95": f"-${abs(round(cvar_95, 2)):,.2f}",
        "interpretation": (
            f"Pre-hedge portfolio ({timeframe_label(timeframe)}): ann. vol {round(ann_vol * 100, 2)}%, "
            f"Sharpe {round(sharpe, 2)}, 1-day 95% VaR {abs(round(var_95, 2)):,.0f}."
        ),
    }


def build_pairs_spread_series(
    ticker_a: str,
    ticker_b: str,
    hedge_ratio: float,
    timeframe: str = "1d",
) -> pd.DataFrame | None:
    prices = fetch_prices([ticker_a, ticker_b], timeframe=timeframe)
    if prices.empty or ticker_a not in prices.columns or ticker_b not in prices.columns:
        return None
    prices = prices.dropna()
    spread = np.log(prices[ticker_a].astype(float)) - hedge_ratio * np.log(prices[ticker_b].astype(float))
    mean = float(spread.mean())
    std = float(spread.std())
    return pd.DataFrame({
        "spread": spread,
        "mean": mean,
        "upper": mean + 1.5 * std,
        "lower": mean - 1.5 * std,
    })


def run_mtf_strategy(
    strategy_key: str,
    timeframe: str,
    **kwargs: Any,
) -> dict[str, Any] | None:
    runners = {
        "beta": beta_hedge,
        "pairs": pairs_trade_hedge,
        "delta": delta_hedge_options,
        "inverse_etf": inverse_etf_hedge,
        "crypto": crypto_hedge,
        "portfolio_risk": portfolio_risk,
    }
    fn = runners.get(strategy_key)
    if not fn:
        return None
    return fn(timeframe=timeframe, **kwargs)


def run_full_mtf_hedging_suite(
    market: str,
    portfolio_ticker: str,
    pair_ticker: str,
    benchmark: str,
    hedge_asset: str,
    portfolio_value: float,
    pair_value: float,
    hedge_pct: float,
    strike_pct: float,
    days_to_expiry: int,
    portfolio_tickers: list[str],
    portfolio_weights: list[float],
    timeframes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run all hedging strategies across LTF / MTF / HTF chart timeframes."""
    tf_map = timeframes or default_hedge_timeframes(market)
    primary = resolve_yf_ticker(portfolio_ticker, market)
    pair = resolve_yf_ticker(pair_ticker, market)
    bench_yf = resolve_benchmark_yf(benchmark, market)
    hedge_etf = resolve_hedge_instrument_yf(benchmark, market)
    hedge_yf = resolve_yf_ticker(hedge_asset, market) if is_crypto_market(market) else hedge_asset

    suite: dict[str, Any] = {
        "market": market,
        "primary_yf": primary,
        "pair_yf": pair,
        "benchmark_yf": bench_yf,
        "hedge_etf_yf": hedge_etf,
        "hedge_asset_yf": hedge_yf,
        "portfolio_value": portfolio_value,
        "timeframes": tf_map,
        "roles": list(HEDGE_ROLES),
        "strategies": {},
    }

    for role in HEDGE_ROLES:
        tf = tf_map.get(role, "1d")
        period_block: dict[str, Any] = {"timeframe": tf, "timeframe_label": timeframe_label(tf)}

        if is_crypto_market(market):
            beta_bench = "BTC-USD" if primary != "BTC-USD" else "ETH-USD"
            period_block["crypto"] = crypto_hedge(
                primary=primary,
                hedge_asset=hedge_yf,
                portfolio_value=portfolio_value,
                timeframe=tf,
            )
            period_block["beta"] = beta_hedge(
                portfolio_ticker=primary,
                benchmark=beta_bench,
                portfolio_value=portfolio_value,
                timeframe=tf,
                market=market,
            )
        else:
            period_block["beta"] = beta_hedge(
                portfolio_ticker=primary,
                benchmark=bench_yf,
                portfolio_value=portfolio_value,
                timeframe=tf,
                market=market,
                hedge_instrument_yf=hedge_etf,
            )
            period_block["inverse_etf"] = inverse_etf_hedge(
                portfolio_ticker=primary,
                benchmark=bench_yf,
                portfolio_value=portfolio_value,
                hedge_pct=hedge_pct,
                timeframe=tf,
                market=market,
                hedge_instrument=hedge_etf,
            )
            period_block["delta"] = delta_hedge_options(
                ticker=primary,
                portfolio_value=portfolio_value,
                strike_pct=strike_pct,
                days_to_expiry=days_to_expiry,
                timeframe=tf,
                market=market,
            )

        period_block["pairs"] = pairs_trade_hedge(
            ticker_a=primary,
            ticker_b=pair,
            position_value=pair_value,
            timeframe=tf,
        )

        port_tickers = [resolve_yf_ticker(t, market) for t in portfolio_tickers]
        period_block["portfolio_risk"] = portfolio_risk(
            tickers=port_tickers,
            weights=portfolio_weights,
            portfolio_value=portfolio_value,
            timeframe=tf,
        )

        suite["strategies"][role] = period_block

    htf_pairs = suite["strategies"].get("HTF", {}).get("pairs")
    chart_tf = tf_map.get("HTF", "1d")
    if htf_pairs and htf_pairs.get("hedge_ratio"):
        suite["pairs_spread"] = build_pairs_spread_series(
            primary, pair, htf_pairs["hedge_ratio"], timeframe=chart_tf,
        )
    return suite
