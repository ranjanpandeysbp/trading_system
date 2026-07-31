"""
intra_hedging_engine.py
-------------------------
Intra-Hedging — Sector Relative-Strength Long/Short Hedge (intraday), a
"sector pairs trading" strategy: go long today's strongest Nifty sector,
short today's weakest, and size both legs beta-neutral so the pair is
market-direction-neutral — you're purely trading the SPREAD between the
strong sector's momentum and the weak sector's weakness, not overall Nifty
direction. If the whole market suddenly moves against you, the other leg
offsets it.

The 10-sector universe covers the heaviest, most liquid Nifty sectoral
indices (Banking, IT, Energy, Auto, FMCG, Pharma, Metal, Realty,
Infrastructure, Media) — together these span the large majority of Nifty 50's
weight, so a clear divergence here usually means real institutional rotation,
not noise.

Method:
  1. Rank all 10 sectors by today's intraday momentum (session close vs.
     session open, on the selected intraday timeframe).
  2. The strongest sector is the LONG leg; the weakest is the SHORT leg.
     If the spread between them is too small, there's no clear divergence
     today and the strategy sits out (per the source idea: "you are looking
     for a day where sectors clearly disagree").
  3. Beta-neutral sizing: each sector's Beta (vs. Nifty 50, from daily
     returns) determines its capital split — the higher-beta leg gets LESS
     capital, so both legs carry the same volatility-weighted exposure and
     net portfolio Beta is ~0.
  4. Execution: either the ETF route (buy the strong sector's ETF; India
     cash-market intraday shorting of ETFs is broker-restricted, so the
     short leg typically needs the sector's futures or its top stocks) or
     the stock route (buy/short the sector's top-weighted constituent
     stocks directly — faster fills, no minor-ETF liquidity issues).

Data: this app's usual Groww/yfinance OHLCV feed, with Nifty sector index
display names ("NIFTY BANK", "NIFTY IT", ...) resolved to the correct Yahoo
Finance ticker via nse_index_yfinance.py's single source of truth, same as
every other index-driven engine in this app.

Not a backtested edge — a structured framework for a well-known relative-
strength pairs concept. Research / education only, not financial advice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smart_money_shared import enrich_smc_live, hold_for_tf

logger = logging.getLogger(__name__)

MOMENTUM_TIMEFRAME_OPTIONS = ["5m", "15m", "30m"]

# 10 heaviest, most liquid Nifty sectoral indices — canonical names resolved
# via nse_index_yfinance.NSE_INDEX_YF_TICKERS.
SECTOR_UNIVERSE: list[str] = [
    "NIFTY BANK", "NIFTY IT", "NIFTY ENERGY", "NIFTY AUTO", "NIFTY FMCG",
    "NIFTY PHARMA", "NIFTY METAL", "NIFTY REALTY", "NIFTY INFRASTRUCTURE", "NIFTY MEDIA",
]
SECTOR_LABELS: dict[str, str] = {
    "NIFTY BANK": "Banking", "NIFTY IT": "IT", "NIFTY ENERGY": "Energy / Oil & Gas",
    "NIFTY AUTO": "Auto", "NIFTY FMCG": "FMCG", "NIFTY PHARMA": "Pharma",
    "NIFTY METAL": "Metal", "NIFTY REALTY": "Realty", "NIFTY INFRASTRUCTURE": "Infrastructure",
    "NIFTY MEDIA": "Media",
}
# Verified, liquid NSE-listed ETF proxies for the ETF execution route — None
# where no sufficiently liquid single-sector ETF exists (use the stock route).
SECTOR_ETF_PROXY: dict[str, str | None] = {
    "NIFTY BANK": "BANKBEES", "NIFTY IT": "ITBEES", "NIFTY ENERGY": "ENERGYBEES",
    "NIFTY AUTO": "AUTOBEES", "NIFTY FMCG": "CONSUMBEES", "NIFTY PHARMA": "PHARMABEES",
    "NIFTY METAL": "METALBEES", "NIFTY REALTY": "REALTYBEES", "NIFTY INFRASTRUCTURE": "INFRABEES",
    "NIFTY MEDIA": None,
}
BENCHMARK = "NIFTY 50"


@dataclass
class IntraHedgingConfig:
    total_capital: float = 500_000.0
    momentum_timeframe: str = "15m"
    beta_lookback_days: int = 90
    min_bars_daily: int = 30
    min_divergence_pct: float = 0.5  # min momentum spread (strong - weak) to call it a real divergence
    top_n_execution_stocks: int = 2
    risk_free_rate: float = 0.065
    # required by the shared fixed-universe config contract; unused here (no
    # ticker-level historical lookback beyond beta_lookback_days/momentum)
    min_bars: int = 30
    lookback_bars: int = 150


# ---------------------------------------------------------------------------
# Shared low-level helpers (self-contained, matching the style of the other
# hub engines rather than a shared library)
# ---------------------------------------------------------------------------

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=max(2, period // 2)).mean()


def _session_bars(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    last_date = df.index[-1].date()
    return df[df.index.map(lambda ts: ts.date()) == last_date]


# ---------------------------------------------------------------------------
# Per-sector momentum + beta
# ---------------------------------------------------------------------------

def _fetch_intraday(name: str, market: str, cfg: IntraHedgingConfig, *, groww_token: str, exchange: str) -> pd.DataFrame:
    df = fetch_data_for_gap_scan(name, cfg.momentum_timeframe, market, groww_token, exchange, limit=150)
    df = normalize_ohlcv(df)
    if df.empty:
        df = normalize_ohlcv(fetch_ohlcv_yfinance(name, cfg.momentum_timeframe, is_crypto=False, limit=150, market=market))
    return df


def _fetch_daily(name: str, market: str, cfg: IntraHedgingConfig, *, groww_token: str, exchange: str) -> pd.DataFrame:
    limit = cfg.beta_lookback_days + 30
    df = fetch_data_for_gap_scan(name, "1d", market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < cfg.min_bars_daily:
        df = normalize_ohlcv(fetch_ohlcv_yfinance(name, "1d", is_crypto=False, limit=limit, market=market))
    return df


def compute_sector_momentum(name: str, market: str, cfg: IntraHedgingConfig, *, groww_token: str, exchange: str) -> dict[str, Any] | None:
    df = _fetch_intraday(name, market, cfg, groww_token=groww_token, exchange=exchange)
    if df.empty:
        return None
    session = _session_bars(df)
    if len(session) < 2:
        session = df.iloc[-10:]
    open_price = float(session["open"].iloc[0])
    last_price = float(session["close"].iloc[-1])
    if open_price <= 0:
        return None
    return {
        "df": df, "last_price": last_price, "open_price": open_price,
        "momentum_pct": (last_price - open_price) / open_price * 100,
    }


def compute_beta(name: str, market: str, bench_returns: pd.Series, cfg: IntraHedgingConfig, *, groww_token: str, exchange: str) -> float | None:
    if bench_returns.empty:
        return None
    daily = _fetch_daily(name, market, cfg, groww_token=groww_token, exchange=exchange)
    if daily.empty or len(daily) < cfg.min_bars_daily:
        return None
    rets = daily["close"].pct_change().dropna().tail(cfg.beta_lookback_days)
    aligned = pd.concat([rets.rename("s"), bench_returns.rename("b")], axis=1).dropna()
    if len(aligned) < 20:
        return None
    cov = float(np.cov(aligned["s"], aligned["b"])[0][1])
    var = float(np.var(aligned["b"]))
    return cov / var if var > 0 else 1.0


def sector_top_stocks(name: str, cfg: IntraHedgingConfig) -> list[str]:
    try:
        from app.market_pulse.nifty_index_constituents import get_index_constituent_symbols

        return list(get_index_constituent_symbols(name))[: cfg.top_n_execution_stocks]
    except Exception as exc:
        logger.debug("Constituent lookup failed for %s: %s", name, exc)
        return []


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------

def _leg_risk(row: dict[str, Any]) -> tuple[float, float]:
    df = row["df"]
    atr = _atr(df, 14)
    price = row["last_price"]
    atr_last = float(atr.dropna().iloc[-1]) if not atr.dropna().empty else price * 0.005
    sl_pct = round(max(0.15, atr_last / price * 100), 2) if price else 0.5
    return sl_pct, round(sl_pct * 2, 2)


def _sector_row(
    name: str, metrics: dict[str, Any], *, role: str, cfg: IntraHedgingConfig,
    long_capital: float | None = None, short_capital: float | None = None,
    pair_note: str = "",
) -> dict[str, Any]:
    label = SECTOR_LABELS.get(name, name)
    momentum = metrics["momentum_pct"]
    beta = metrics.get("beta")
    reasons: list[str] = [
        f"{label} ({name.title()}) is {'up' if momentum >= 0 else 'down'} {abs(momentum):.2f}% "
        f"from today's session open — {'leading' if role == 'long' else 'lagging' if role == 'short' else 'mid-pack'} "
        f"among the 10 tracked sectors.",
    ]
    if beta is not None:
        reasons.append(f"Beta vs Nifty 50: {beta:.2f} ({cfg.beta_lookback_days}-day daily returns).")

    if role == "neutral":
        return enrich_smc_live({
            "signal": "NONE", "direction": "WAIT", "take_trade": False,
            "verdict": "WAIT", "phase": "NEUTRAL", "confidence_pct": 20.0,
            "sl_pct": 0.0, "tp_pct": 0.0,
            "momentum_pct": round(momentum, 3), "beta": round(beta, 3) if beta is not None else None,
            "reasons": reasons + [pair_note or "Not today's pair leg — momentum isn't extreme enough on either end."],
        }, hold_duration=hold_for_tf(cfg.momentum_timeframe, "intraday"))

    direction = "LONG" if role == "long" else "SHORT"
    sl_pct, tp_pct = _leg_risk(metrics)
    hold = hold_for_tf(cfg.momentum_timeframe, "intraday")
    confidence = min(90.0, max(35.0, 50 + abs(momentum) * 8))

    reasons.append(pair_note)
    top_stocks = sector_top_stocks(name, cfg)
    etf = SECTOR_ETF_PROXY.get(name)
    if role == "long":
        reasons.append(
            f"ETF route: buy {etf} (cash market)." if etf else "ETF route: no sufficiently liquid single-sector ETF — use the stock route."
        )
        if top_stocks:
            reasons.append(f"Stock route: buy top {len(top_stocks)} weighted constituents — {', '.join(top_stocks)}.")
    else:
        reasons.append(
            f"ETF route: India cash-market intraday shorting of {etf} may be broker-restricted — short via "
            f"{name.title()} futures instead." if etf else
            "ETF route: no sufficiently liquid single-sector ETF to short — use the stock route or sector futures."
        )
        if top_stocks:
            reasons.append(f"Stock route: short top {len(top_stocks)} weighted constituents — {', '.join(top_stocks)}.")
    capital = long_capital if role == "long" else short_capital
    if capital is not None:
        reasons.append(f"Beta-neutral allocation for this leg: ₹{capital:,.0f} of total capital.")

    plan = make_trade_plan(
        direction=direction, timeframe=cfg.momentum_timeframe,
        stop_loss_pct=sl_pct, take_profit_pct=tp_pct, confidence_pct=round(confidence, 1),
        style="intraday",
        exit_rule="Exit if the momentum spread between the two legs closes/reverses, or flat by end of session.",
        max_hold_exit="Flat by end of session — this is a same-day pairs trade, not an overnight hold.",
    )

    return enrich_smc_live({
        "signal": direction, "direction": direction, "take_trade": True,
        "verdict": f"TAKE {direction}", "phase": "LEADER" if role == "long" else "LAGGARD",
        "confidence_pct": round(confidence, 1), "sl_pct": sl_pct, "tp_pct": tp_pct,
        "momentum_pct": round(momentum, 3), "beta": round(beta, 3) if beta is not None else None,
        "reasons": reasons, "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)


def analyze_ticker(
    ticker: str, market: str, *, cfg: IntraHedgingConfig | None = None,
    groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """Single-sector read (momentum + beta), no pair verdict — the pair
    recommendation only exists at the scan_universe level, across all 10
    sectors. Kept for interface parity with the other hub engines."""
    cfg = cfg or IntraHedgingConfig()
    name = ticker.upper() if ticker.upper() in SECTOR_UNIVERSE else ticker
    mom = compute_sector_momentum(name, market, cfg, groww_token=groww_token, exchange=exchange)
    if mom is None:
        return {"ticker": ticker, "error": f"Insufficient {cfg.momentum_timeframe} intraday data."}
    return {
        "ticker": ticker, "market": market,
        "last_close": round(mom["last_price"], 4),
        "live": _sector_row(name, mom, role="neutral", cfg=cfg, pair_note="Run the full Intra-Hedging scan to see today's Long/Short pair."),
    }


def scan_universe(
    tickers: list[str], market: str, *, cfg: IntraHedgingConfig | None = None,
    groww_token: str = "", exchange: str = "NSE", run_bt: bool = False,
) -> dict[str, Any]:
    """Always scans the fixed 10-sector universe — `tickers` is accepted for
    interface parity with the other fixed-universe hub sections and filtered
    against SECTOR_UNIVERSE, same convention as gokul_chhabra_engine / zero_to_hero_engine."""
    cfg = cfg or IntraHedgingConfig()
    names = [n for n in (tickers or SECTOR_UNIVERSE) if n in SECTOR_UNIVERSE] or list(SECTOR_UNIVERSE)

    bench_daily = _fetch_daily(BENCHMARK, market, cfg, groww_token=groww_token, exchange=exchange)
    bench_returns = (
        bench_daily["close"].pct_change().dropna().tail(cfg.beta_lookback_days)
        if not bench_daily.empty and len(bench_daily) >= cfg.min_bars_daily else pd.Series(dtype=float)
    )

    metrics: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    for name in names:
        mom = compute_sector_momentum(name, market, cfg, groww_token=groww_token, exchange=exchange)
        if mom is None:
            errors[name] = f"Insufficient {cfg.momentum_timeframe} intraday data."
            continue
        beta = compute_beta(name, market, bench_returns, cfg, groww_token=groww_token, exchange=exchange)
        mom["beta"] = beta
        metrics[name] = mom

    ok_names = [n for n, m in metrics.items() if m.get("beta") is not None]
    if len(ok_names) < 2:
        return {
            "market": market, "error": "Not enough sector data (momentum + Beta) available right now.",
            "results": [{"ticker": n, "error": e} for n, e in errors.items()],
        }

    ranked = sorted(ok_names, key=lambda n: metrics[n]["momentum_pct"], reverse=True)
    strong_name, weak_name = ranked[0], ranked[-1]
    strong, weak = metrics[strong_name], metrics[weak_name]
    spread = strong["momentum_pct"] - weak["momentum_pct"]
    divergence_ok = spread >= cfg.min_divergence_pct

    long_beta = abs(strong["beta"]) or 1.0
    short_beta = abs(weak["beta"]) or 1.0
    long_weight = short_beta / (long_beta + short_beta)
    short_weight = long_beta / (long_beta + short_beta)
    long_capital = round(cfg.total_capital * long_weight, 2)
    short_capital = round(cfg.total_capital * short_weight, 2)
    net_beta_exposure = round(long_capital * strong["beta"] - short_capital * weak["beta"], 2)

    pair_note = (
        f"Today's pair: LONG {SECTOR_LABELS.get(strong_name, strong_name)} ({strong['momentum_pct']:+.2f}%) vs "
        f"SHORT {SECTOR_LABELS.get(weak_name, weak_name)} ({weak['momentum_pct']:+.2f}%) — spread {spread:.2f}%."
        if divergence_ok else
        f"Momentum spread today is only {spread:.2f}% (below the {cfg.min_divergence_pct:.1f}% divergence threshold) "
        "— no clear sector disagreement, sitting out rather than forcing a weak pair."
    )

    results: list[dict[str, Any]] = []
    for name in names:
        if name in errors:
            results.append({"ticker": name, "label": SECTOR_LABELS.get(name, name), "error": errors[name]})
            continue
        m = metrics[name]
        if not divergence_ok:
            live = _sector_row(name, m, role="neutral", cfg=cfg, pair_note=pair_note)
        elif name == strong_name:
            live = _sector_row(name, m, role="long", cfg=cfg, long_capital=long_capital, short_capital=short_capital, pair_note=pair_note)
        elif name == weak_name:
            live = _sector_row(name, m, role="short", cfg=cfg, long_capital=long_capital, short_capital=short_capital, pair_note=pair_note)
        else:
            live = _sector_row(name, m, role="neutral", cfg=cfg, pair_note=pair_note)
        results.append({
            "ticker": name, "label": SECTOR_LABELS.get(name, name),
            "last_close": round(m["last_price"], 4), "live": live,
        })

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]

    pair_recommendation = {
        "divergence_ok": divergence_ok,
        "spread_pct": round(spread, 3),
        "min_divergence_pct": cfg.min_divergence_pct,
        "long_sector": strong_name, "long_label": SECTOR_LABELS.get(strong_name, strong_name),
        "long_momentum_pct": round(strong["momentum_pct"], 3), "long_beta": round(strong["beta"], 3),
        "long_capital": long_capital, "long_etf": SECTOR_ETF_PROXY.get(strong_name),
        "long_top_stocks": sector_top_stocks(strong_name, cfg),
        "short_sector": weak_name, "short_label": SECTOR_LABELS.get(weak_name, weak_name),
        "short_momentum_pct": round(weak["momentum_pct"], 3), "short_beta": round(weak["beta"], 3),
        "short_capital": short_capital, "short_etf": SECTOR_ETF_PROXY.get(weak_name),
        "short_top_stocks": sector_top_stocks(weak_name, cfg),
        "total_capital": cfg.total_capital, "net_beta_exposure": net_beta_exposure,
        "note": pair_note,
    }

    return {
        "market": market,
        "strategy": "Intra-Hedging — Sector Relative-Strength Long/Short (beta-neutral)",
        "benchmark": BENCHMARK,
        "results": results,
        "entries": entries,
        "entry_count": len(entries),
        "watchlist": [],
        "pair_recommendation": pair_recommendation,
    }
