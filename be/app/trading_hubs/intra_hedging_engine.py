"""
intra_hedging_engine.py
-------------------------
Intra-Hedging — Sector Relative-Strength Long/Short Hedge, a "sector pairs
trading" strategy: go long the strongest Nifty sector, short the weakest,
and size both legs beta-neutral so the pair is market-direction-neutral —
you're purely trading the SPREAD between the strong sector's momentum and
the weak sector's weakness, not overall Nifty direction. If the whole
market suddenly moves against you, the other leg offsets it.

Works for BOTH intraday and swing trading, selected by the momentum
timeframe:
  - Intraday timeframes (5m/15m/30m/1h): momentum = today's session close
    vs. session open — the original same-day, flat-by-close read.
  - Swing timeframes (4h/1d/1wk): momentum = close-to-close return over a
    timeframe-appropriate lookback window (6 bars on 4h ≈ ~4 trading days,
    5 bars on 1d ≈ ~1 trading week, 4 bars on 1wk ≈ ~1 month) — a
    multi-day/week rotation read, held for a swing-appropriate duration
    instead of flattened same-day.

The full universe covers every major Nifty sectoral index this app can
resolve OHLC for — 28 sectors, spanning both the heavyweight ones (Banking,
IT, Financial Services) and the smaller/thematic ones (Defence, Tourism,
Housing, ...). A handful of the newer sector indices have no listed Yahoo
Finance index ticker; those fall back to an equal-weight constituent-stock
OHLC proxy (index_ohlcv.py's existing, already-used-elsewhere resolver) —
same honest-fallback convention as this app's other index-driven tools.

Method:
  1. Rank every tracked sector by momentum on the selected timeframe (see
     above — session-based for intraday, lookback-return-based for swing).
  2. The strongest sector is the LONG leg; the weakest is the SHORT leg.
     If the spread between them is too small, there's no clear divergence
     right now and the strategy sits out (per the source idea: "you are
     looking for a day where sectors clearly disagree").
  3. Beta-neutral sizing: each sector's Beta (vs. Nifty 50, from daily
     returns) determines its capital split — the higher-beta leg gets LESS
     capital, so both legs carry the same volatility-weighted exposure and
     net portfolio Beta is ~0.
  4. Execution: either the ETF route (buy the strong sector's ETF — every
     verified, liquid NSE-listed ETF for that sector is listed, not just
     one; India cash-market intraday shorting of ETFs is broker-restricted,
     so the short leg typically needs the sector's futures instead) or the
     stock route (buy/short the sector's top-5 weighted constituent stocks
     directly — faster fills, no minor-ETF liquidity issues).

Data: this app's usual Groww/yfinance OHLCV feed (via index_ohlcv.py's
unified resolver: Groww -> verified Yahoo index ticker -> constituent-stock
proxy), with Nifty sector index display names ("NIFTY BANK", "NIFTY IT", ...)
resolved via nse_index_yfinance.py's single source of truth, same as every
other index-driven engine in this app.

Not a backtested edge — a structured framework for a well-known relative-
strength pairs concept. Research / education only, not financial advice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.index_ohlcv import fetch_index_ohlcv_for_interval
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.nse_index_yfinance import SECTOR_INDEX_NAMES
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smart_money_shared import enrich_smc_live, hold_for_tf

logger = logging.getLogger(__name__)

MOMENTUM_TIMEFRAME_OPTIONS = ["5m", "15m", "30m", "1h", "4h", "1d", "1wk"]
INTRADAY_TIMEFRAMES = frozenset({"5m", "15m", "30m", "1h"})
# Swing timeframes measure momentum as a close-to-close return over this many
# bars, rather than today's session — chosen so each defaults to roughly a
# similar real-world lookback window regardless of bar size.
SWING_LOOKBACK_BARS: dict[str, int] = {"4h": 6, "1d": 5, "1wk": 4}

# Every major Nifty sectoral index this app can resolve OHLC for (direct
# Yahoo ticker or constituent-stock proxy) — nse_index_yfinance.py's own
# curated sector-rotation universe.
SECTOR_UNIVERSE: list[str] = list(SECTOR_INDEX_NAMES)

# "Stock" universe mode scans one index's individual constituents instead of
# the 28 sector indices — curated subset of ticker_utils.INDEX_OPTIONS (real
# indices only, excludes the non-index "Default Groww Tickers"/"High Vol ETF"
# convenience lists).
STOCK_MODE_INDEX_OPTIONS: list[str] = [
    "NIFTY 50", "NIFTY NEXT 50", "NIFTY BANK", "NIFTY IT", "NIFTY FINANCIAL SERVICES",
    "NIFTY AUTO", "NIFTY FMCG", "NIFTY PHARMA", "NIFTY METAL", "NIFTY REALTY",
    "NIFTY ENERGY", "NIFTY CEMENT", "NIFTY CHEMICALS", "NIFTY CONSUMER DURABLES",
    "NIFTY HEALTHCARE", "NIFTY MIDCAP 150", "NIFTY SMALLCAP 250",
]

SECTOR_LABELS: dict[str, str] = {
    "NIFTY AUTO": "Auto", "NIFTY BANK": "Banking", "NIFTY CEMENT": "Cement",
    "NIFTY CHEMICALS": "Chemicals", "NIFTY COMMODITIES": "Commodities",
    "NIFTY CONSUMPTION": "Consumption", "NIFTY CONSUMER DURABLES": "Consumer Durables",
    "NIFTY ENERGY": "Energy / Oil & Gas", "NIFTY FINANCIAL SERVICES": "Financial Services",
    "NIFTY FINANCIAL SERVICES EX-BANK": "Financial Services (ex-Bank)", "NIFTY FMCG": "FMCG",
    "NIFTY HEALTHCARE": "Healthcare", "NIFTY HOUSING": "Housing",
    "NIFTY INDIA DEFENCE": "Defence", "NIFTY INDIA MANUFACTURING": "Manufacturing",
    "NIFTY INDIA TOURISM": "Tourism", "NIFTY INFRASTRUCTURE": "Infrastructure",
    "NIFTY IT": "IT", "NIFTY MEDIA": "Media", "NIFTY METAL": "Metal",
    "NIFTY MOBILITY": "Mobility", "NIFTY OIL & GAS": "Oil & Gas", "NIFTY PHARMA": "Pharma",
    "NIFTY PRIVATE BANK": "Private Bank", "NIFTY PSU BANK": "PSU Bank",
    "NIFTY PSE": "Public Sector Enterprises", "NIFTY REALTY": "Realty",
    "NIFTY SERVICES SECTOR": "Services",
}


def _build_sector_etf_map() -> dict[str, list[str]]:
    """Reuses detect_sector_rotation_engine's already-vetted multi-ETF lists
    (re-keyed from its own sector labels to the canonical NSE index names
    used here) rather than duplicating ETF ticker literals. Sectors it
    doesn't cover are left with an empty list — honest "no liquid ETF"
    rather than an invented ticker."""
    try:
        from app.market_pulse.detect_sector_rotation_engine import INDIA_SECTOR_ETFS, INDIA_SECTOR_INDEX_KEY
        from app.market_pulse.nse_index_yfinance import normalize_index_name
    except Exception:
        return {}
    out: dict[str, list[str]] = {}
    for label, nse_name in INDIA_SECTOR_INDEX_KEY.items():
        etfs = INDIA_SECTOR_ETFS.get(label) or []
        if etfs:
            out[normalize_index_name(nse_name)] = list(etfs)
    return out


# NSE index name -> list of verified, liquid NSE-listed ETFs for the ETF
# execution route (empty list = no sufficiently liquid single-sector ETF,
# use the stock route instead).
SECTOR_ETFS: dict[str, list[str]] = _build_sector_etf_map()
BENCHMARK = "NIFTY 50"


@dataclass
class IntraHedgingConfig:
    total_capital: float = 500_000.0
    momentum_timeframe: str = "15m"
    beta_lookback_days: int = 90
    min_bars_daily: int = 30
    min_divergence_pct: float = 0.5  # min momentum spread (strong - weak) to call it a real divergence
    top_n_execution_stocks: int = 5
    risk_free_rate: float = 0.065
    # required by the shared fixed-universe config contract; unused here (no
    # ticker-level historical lookback beyond beta_lookback_days/momentum)
    min_bars: int = 30
    lookback_bars: int = 150
    # How many non-overlapping long/short pairs to surface — pair 1 is
    # strongest-vs-weakest, pair 2 is 2nd-strongest-vs-2nd-weakest, etc.,
    # stopping early once a candidate pair's spread misses the divergence bar.
    max_pairs: int = 3
    # "sector" scans the 28 tracked Nifty sector indices (original behavior);
    # "stock" scans one chosen index's individual constituent stocks instead.
    universe_mode: str = "sector"
    stock_index: str = "NIFTY BANK"
    stock_universe_cap: int = 25


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

_STOCK_CAL_DAYS_PER_BAR: dict[str, float] = {
    "5m": 1 / 75, "15m": 1 / 25, "30m": 1 / 13, "1h": 1 / 7, "4h": 2 / 3, "1d": 1.5, "1wk": 10,
}


def _fetch_stock_ohlcv(name: str, timeframe: str, target_bars: int, *, groww_token: str, exchange: str) -> pd.DataFrame:
    """Individual-stock OHLCV via this app's standard per-ticker fetcher
    (same one used by ema_position_engine.py etc.) — used only in "stock"
    universe mode, since `fetch_index_ohlcv_for_interval` above is index-only."""
    from datetime import date, timedelta

    from backtesting.data_fetcher import get_historical_data

    days_per_bar = _STOCK_CAL_DAYS_PER_BAR.get(timeframe, 1.5)
    days_back = int(target_bars * days_per_bar) + 5
    end = date.today()
    start = end - timedelta(days=days_back)
    df = get_historical_data(
        symbol=name, start_date=str(start), end_date=str(end + timedelta(days=1)),
        market="Groww (India Stocks)", timeframe=timeframe,
        groww_token=groww_token, groww_exchange=exchange,
    )
    return normalize_ohlcv(df) if df is not None else pd.DataFrame()


def _fetch_momentum_tf(name: str, market: str, cfg: IntraHedgingConfig, *, groww_token: str, exchange: str) -> pd.DataFrame:
    limit = 150 if cfg.momentum_timeframe in INTRADAY_TIMEFRAMES else max(150, SWING_LOOKBACK_BARS.get(cfg.momentum_timeframe, 5) + 60)
    if cfg.universe_mode == "stock":
        return _fetch_stock_ohlcv(name, cfg.momentum_timeframe, limit, groww_token=groww_token, exchange=exchange)
    df = fetch_index_ohlcv_for_interval(name, cfg.momentum_timeframe, limit=limit, groww_token=groww_token, exchange=exchange)
    df = normalize_ohlcv(df) if df is not None else pd.DataFrame()
    return df


def _fetch_daily(name: str, market: str, cfg: IntraHedgingConfig, *, groww_token: str, exchange: str) -> pd.DataFrame:
    limit = cfg.beta_lookback_days + 30
    if cfg.universe_mode == "stock":
        return _fetch_stock_ohlcv(name, "1d", limit, groww_token=groww_token, exchange=exchange)
    df = fetch_index_ohlcv_for_interval(name, "1d", limit=limit, groww_token=groww_token, exchange=exchange)
    df = normalize_ohlcv(df) if df is not None else pd.DataFrame()
    return df


def _fetch_benchmark_daily(cfg: IntraHedgingConfig, *, groww_token: str, exchange: str) -> pd.DataFrame:
    """The Nifty 50 INDEX used for Beta — always fetched via the index path
    regardless of `cfg.universe_mode`, since BENCHMARK is never an individual
    stock ticker even when the scanned universe itself is (stock mode)."""
    limit = cfg.beta_lookback_days + 30
    df = fetch_index_ohlcv_for_interval(BENCHMARK, "1d", limit=limit, groww_token=groww_token, exchange=exchange)
    return normalize_ohlcv(df) if df is not None else pd.DataFrame()


def compute_sector_momentum(name: str, market: str, cfg: IntraHedgingConfig, *, groww_token: str, exchange: str) -> dict[str, Any] | None:
    df = _fetch_momentum_tf(name, market, cfg, groww_token=groww_token, exchange=exchange)
    if df.empty:
        return None

    if cfg.momentum_timeframe in INTRADAY_TIMEFRAMES:
        window = _session_bars(df)
        if len(window) < 2:
            window = df.iloc[-10:]
        base_price = float(window["open"].iloc[0])
        window_label = "today's session"
    else:
        lookback = SWING_LOOKBACK_BARS.get(cfg.momentum_timeframe, 5)
        window = df.iloc[-(lookback + 1):]
        if len(window) < 2:
            window = df
        base_price = float(window["close"].iloc[0])
        window_label = f"the last {len(window) - 1} {cfg.momentum_timeframe} bars"

    last_price = float(df["close"].iloc[-1])
    if base_price <= 0:
        return None
    return {
        "df": df, "last_price": last_price, "base_price": base_price,
        "momentum_pct": (last_price - base_price) / base_price * 100,
        "window_label": window_label,
    }


def compute_beta(name: str, market: str, bench_returns: pd.Series, cfg: IntraHedgingConfig, *, groww_token: str, exchange: str) -> float | None:
    if bench_returns.empty:
        return None
    daily = _fetch_daily(name, market, cfg, groww_token=groww_token, exchange=exchange)
    if daily.empty or len(daily) < cfg.min_bars_daily:
        return None
    rets = daily["close"].pct_change().dropna().tail(cfg.beta_lookback_days)
    # Index-mode fetches (fetch_index_ohlcv_for_interval) and per-stock fetches
    # (get_historical_data, used only in "stock" universe mode) normalize daily
    # bar timestamps differently (midnight vs. NSE-close-in-UTC) — normalizing
    # both to date-only here is what actually lets pd.concat align them; in
    # "sector" mode both sides already share the index fetcher so this is a
    # no-op.
    rets.index = pd.to_datetime(rets.index).normalize()
    bench_returns = bench_returns.copy()
    bench_returns.index = pd.to_datetime(bench_returns.index).normalize()
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


def _pair_confidence(spread_pct: float) -> float:
    """Comparable across pairs by construction: driven directly by the
    momentum spread, so a bigger divergence always scores higher — this is
    what lets multiple simultaneous pairs be ranked against each other."""
    return round(min(95.0, max(30.0, 50 + spread_pct * 6)), 1)


def _sector_row(
    name: str, metrics: dict[str, Any], *, role: str, cfg: IntraHedgingConfig,
    long_capital: float | None = None, short_capital: float | None = None,
    pair_note: str = "", universe_size: int | None = None,
    pair_rank: int | None = None, num_pairs: int = 1, pair_confidence: float | None = None,
) -> dict[str, Any]:
    is_stock_mode = cfg.universe_mode == "stock"
    label = name if is_stock_mode else SECTOR_LABELS.get(name, name)
    universe_size = universe_size if universe_size is not None else len(SECTOR_UNIVERSE)
    universe_noun = "stocks" if is_stock_mode else "sectors"
    momentum = metrics["momentum_pct"]
    beta = metrics.get("beta")
    window_label = metrics.get("window_label", "the tracked window")
    is_intraday = cfg.momentum_timeframe in INTRADAY_TIMEFRAMES
    style = "intraday" if is_intraday else "swing"
    reasons: list[str] = [
        f"{label}{'' if is_stock_mode else f' ({name.title()})'} is {'up' if momentum >= 0 else 'down'} {abs(momentum):.2f}% "
        f"over {window_label} — {'leading' if role == 'long' else 'lagging' if role == 'short' else 'mid-pack'} "
        f"among the {universe_size} tracked {universe_noun}.",
    ]
    if beta is not None:
        reasons.append(f"Beta vs Nifty 50: {beta:.2f} ({cfg.beta_lookback_days}-day daily returns).")

    if role == "neutral":
        return enrich_smc_live({
            "signal": "NONE", "direction": "WAIT", "take_trade": False,
            "verdict": "WAIT", "phase": "NEUTRAL", "confidence_pct": 20.0,
            "sl_pct": 0.0, "tp_pct": 0.0,
            "momentum_pct": round(momentum, 3), "beta": round(beta, 3) if beta is not None else None,
            "reasons": reasons + [pair_note or "Not part of any of today's hedge pairs — momentum isn't extreme enough on either end."],
        }, hold_duration=hold_for_tf(cfg.momentum_timeframe, style))

    direction = "LONG" if role == "long" else "SHORT"
    sl_pct, tp_pct = _leg_risk(metrics)
    hold = hold_for_tf(cfg.momentum_timeframe, style)
    confidence = pair_confidence if pair_confidence is not None else min(90.0, max(35.0, 50 + abs(momentum) * 8))
    pair_tag = f"Pair {pair_rank} of {num_pairs}" if pair_rank is not None and num_pairs > 1 else None

    reasons.append(pair_note)
    if is_stock_mode:
        reasons.append(
            f"Execution: buy {name} directly (cash market)." if role == "long" else
            (
                f"Execution: {'India cash-market intraday shorting is broker-restricted' if is_intraday else 'India cash-market short positions cannot be carried overnight'} "
                f"for {name} — short via stock futures/options instead."
            )
        )
    else:
        top_stocks = sector_top_stocks(name, cfg)
        etfs = SECTOR_ETFS.get(name) or []
        if role == "long":
            reasons.append(
                f"ETF route: buy any of {', '.join(etfs)} (cash market)." if etfs
                else "ETF route: no sufficiently liquid single-sector ETF — use the stock route."
            )
            if top_stocks:
                reasons.append(f"Stock route: buy top {len(top_stocks)} weighted constituents — {', '.join(top_stocks)}.")
        else:
            short_note = (
                "India cash-market intraday shorting is broker-restricted"
                if is_intraday else
                "India cash-market short positions can't be carried overnight"
            )
            reasons.append(
                f"ETF route: {short_note} for {', '.join(etfs)} — short via {name.title()} futures instead." if etfs else
                "ETF route: no sufficiently liquid single-sector ETF to short — use the stock route or sector futures."
            )
            if top_stocks:
                reasons.append(f"Stock route: short top {len(top_stocks)} weighted constituents — {', '.join(top_stocks)}.")
    capital = long_capital if role == "long" else short_capital
    if capital is not None:
        capital_scope = "this pair's share of total capital" if num_pairs > 1 else "of total capital"
        reasons.append(f"Beta-neutral allocation for this leg: ₹{capital:,.0f} ({capital_scope}).")
    if pair_tag:
        reasons.insert(0, f"{pair_tag} — {confidence:.0f}% confidence (ranked by momentum spread vs the other {num_pairs - 1} pair(s) found today).")

    plan = make_trade_plan(
        direction=direction, timeframe=cfg.momentum_timeframe,
        stop_loss_pct=sl_pct, take_profit_pct=tp_pct, confidence_pct=round(confidence, 1),
        style=style,
        exit_rule=(
            "Exit if the momentum spread between the two legs closes/reverses, or flat by end of session."
            if is_intraday else
            "Exit if the momentum spread between the two legs closes/reverses, or re-run the scan and rotate into the new leaders if the ranking has clearly changed."
        ),
        max_hold_exit=(
            "Flat by end of session — this is a same-day pairs trade, not an overnight hold."
            if is_intraday else
            f"Re-check every {'few days' if cfg.momentum_timeframe in ('4h', '1d') else 'week or two'} — swing sector rotation doesn't need to be flattened same-day, but it does need to be revisited as leadership shifts."
        ),
    )

    verdict = f"TAKE {direction}" + (f" ({pair_tag})" if pair_tag else "")
    return enrich_smc_live({
        "signal": direction, "direction": direction, "take_trade": True,
        "verdict": verdict, "phase": "LEADER" if role == "long" else "LAGGARD",
        "confidence_pct": round(confidence, 1), "sl_pct": sl_pct, "tp_pct": tp_pct,
        "momentum_pct": round(momentum, 3), "beta": round(beta, 3) if beta is not None else None,
        "pair_rank": pair_rank, "reasons": reasons, "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)


def analyze_ticker(
    ticker: str, market: str, *, cfg: IntraHedgingConfig | None = None,
    groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """Single-name read (momentum + beta), no pair verdict — the pair
    recommendation(s) only exist at the scan_universe level, across the
    whole scanned universe. Kept for interface parity with the other hub engines."""
    cfg = cfg or IntraHedgingConfig()
    name = ticker.upper() if ticker.upper() in SECTOR_UNIVERSE else ticker
    mom = compute_sector_momentum(name, market, cfg, groww_token=groww_token, exchange=exchange)
    if mom is None:
        return {"ticker": ticker, "error": f"Insufficient {cfg.momentum_timeframe} data."}
    return {
        "ticker": ticker, "market": market,
        "last_close": round(mom["last_price"], 4),
        "live": _sector_row(name, mom, role="neutral", cfg=cfg, pair_note="Run the full Intra-Hedging scan to see today's Long/Short pair(s)."),
    }


def _resolve_universe(tickers: list[str], cfg: IntraHedgingConfig) -> tuple[list[str], dict[str, str], str, str | None]:
    """Returns (names, labels, universe_desc, error). In "stock" mode the
    chosen index's constituents are resolved fresh here — `tickers` is
    ignored, same convention as the sector-mode fixed-universe filter below."""
    if cfg.universe_mode == "stock":
        from app.market_pulse.nifty_index_constituents import get_index_constituent_symbols

        index_name = cfg.stock_index if cfg.stock_index in STOCK_MODE_INDEX_OPTIONS else "NIFTY BANK"
        symbols = get_index_constituent_symbols(index_name)[: cfg.stock_universe_cap]
        if not symbols:
            return [], {}, "", f"Could not resolve constituent stocks for {index_name}."
        return symbols, {s: s for s in symbols}, f"{index_name} constituents ({len(symbols)} stocks)", None

    names = [n for n in (tickers or SECTOR_UNIVERSE) if n in SECTOR_UNIVERSE] or list(SECTOR_UNIVERSE)
    return names, SECTOR_LABELS, f"{len(SECTOR_UNIVERSE)} tracked Nifty sectors", None


def scan_universe(
    tickers: list[str], market: str, *, cfg: IntraHedgingConfig | None = None,
    groww_token: str = "", exchange: str = "NSE", run_bt: bool = False,
) -> dict[str, Any]:
    """Sector mode always scans the fixed 28-sector universe (`tickers` accepted
    only for interface parity, same convention as gokul_chhabra_engine /
    zero_to_hero_engine); stock mode scans `cfg.stock_index`'s constituents
    instead. Surfaces up to `cfg.max_pairs` non-overlapping long/short pairs —
    pair 1 is strongest-vs-weakest, pair 2 is 2nd-strongest-vs-2nd-weakest,
    etc. — stopping once a candidate pair's spread misses the divergence bar
    (spread only shrinks moving inward from the ranked extremes, so this is
    safe to break on rather than exhaustively check every remaining pair)."""
    cfg = cfg or IntraHedgingConfig()
    names, labels, universe_desc, resolve_error = _resolve_universe(tickers, cfg)
    if resolve_error:
        return {"market": market, "error": resolve_error, "results": []}

    bench_daily = _fetch_benchmark_daily(cfg, groww_token=groww_token, exchange=exchange)
    bench_returns = (
        bench_daily["close"].pct_change().dropna().tail(cfg.beta_lookback_days)
        if not bench_daily.empty and len(bench_daily) >= cfg.min_bars_daily else pd.Series(dtype=float)
    )

    metrics: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    for name in names:
        mom = compute_sector_momentum(name, market, cfg, groww_token=groww_token, exchange=exchange)
        if mom is None:
            errors[name] = f"Insufficient {cfg.momentum_timeframe} data."
            continue
        beta = compute_beta(name, market, bench_returns, cfg, groww_token=groww_token, exchange=exchange)
        mom["beta"] = beta
        metrics[name] = mom

    ok_names = [n for n, m in metrics.items() if m.get("beta") is not None]
    universe_noun = "stock" if cfg.universe_mode == "stock" else "sector"
    if len(ok_names) < 2:
        return {
            "market": market, "error": f"Not enough {universe_noun} data (momentum + Beta) available right now.",
            "results": [{"ticker": n, "error": e} for n, e in errors.items()],
        }

    ranked = sorted(ok_names, key=lambda n: metrics[n]["momentum_pct"], reverse=True)
    n_ranked = len(ranked)
    max_possible_pairs = n_ranked // 2
    num_pairs_requested = max(1, cfg.max_pairs)

    candidate_pairs: list[dict[str, Any]] = []
    for i in range(min(num_pairs_requested, max_possible_pairs)):
        long_name, short_name = ranked[i], ranked[n_ranked - 1 - i]
        spread = metrics[long_name]["momentum_pct"] - metrics[short_name]["momentum_pct"]
        if spread < cfg.min_divergence_pct:
            break
        candidate_pairs.append({"rank": i + 1, "long": long_name, "short": short_name, "spread": spread})

    is_intraday = cfg.momentum_timeframe in INTRADAY_TIMEFRAMES
    pair_scope = "Today's" if is_intraday else "Current"
    num_pairs = len(candidate_pairs)

    if not num_pairs:
        best_spread = metrics[ranked[0]]["momentum_pct"] - metrics[ranked[-1]]["momentum_pct"]
        pair_note = (
            f"The best available momentum spread right now is only {best_spread:.2f}% "
            f"(below the {cfg.min_divergence_pct:.1f}% divergence threshold) — no clear {universe_noun} disagreement, "
            "sitting out rather than forcing a weak pair."
        )
        results = [
            {"ticker": n, "label": labels.get(n, n), "error": errors[n]} if n in errors else
            {
                "ticker": n, "label": labels.get(n, n), "last_close": round(metrics[n]["last_price"], 4),
                "live": _sector_row(n, metrics[n], role="neutral", cfg=cfg, pair_note=pair_note, universe_size=len(names)),
            }
            for n in names
        ]
        return {
            "market": market,
            "strategy": "Intra-Hedging — Relative-Strength Long/Short (beta-neutral)",
            "benchmark": BENCHMARK, "universe_mode": cfg.universe_mode, "universe_desc": universe_desc,
            "results": results, "entries": [], "entry_count": 0, "watchlist": [],
            "pair_recommendations": [], "pair_recommendation": None,
        }

    # Split total capital across the pairs actually found — each pair is then
    # beta-neutral *within itself*, so nothing here implies each pair should
    # separately get the full total_capital.
    capital_per_pair = cfg.total_capital / num_pairs
    role_by_name: dict[str, dict[str, Any]] = {}
    pair_recommendations: list[dict[str, Any]] = []

    for p in candidate_pairs:
        long_name, short_name, spread = p["long"], p["short"], p["spread"]
        strong, weak = metrics[long_name], metrics[short_name]
        long_beta = abs(strong["beta"]) or 1.0
        short_beta = abs(weak["beta"]) or 1.0
        long_weight = short_beta / (long_beta + short_beta)
        short_weight = long_beta / (long_beta + short_beta)
        long_capital = round(capital_per_pair * long_weight, 2)
        short_capital = round(capital_per_pair * short_weight, 2)
        net_beta_exposure = round(long_capital * strong["beta"] - short_capital * weak["beta"], 2)
        confidence = _pair_confidence(spread)

        pair_note = (
            f"{pair_scope} pair {p['rank']} of {num_pairs}: LONG {labels.get(long_name, long_name)} ({strong['momentum_pct']:+.2f}%) vs "
            f"SHORT {labels.get(short_name, short_name)} ({weak['momentum_pct']:+.2f}%) — spread {spread:.2f}%, {confidence:.0f}% confidence."
        )
        role_by_name[long_name] = {"role": "long", "pair_rank": p["rank"], "pair_note": pair_note, "long_capital": long_capital, "short_capital": short_capital, "confidence": confidence}
        role_by_name[short_name] = {"role": "short", "pair_rank": p["rank"], "pair_note": pair_note, "long_capital": long_capital, "short_capital": short_capital, "confidence": confidence}

        pair_recommendations.append({
            "pair_rank": p["rank"], "confidence_pct": confidence,
            "divergence_ok": True, "spread_pct": round(spread, 3), "min_divergence_pct": cfg.min_divergence_pct,
            "long_ticker": long_name, "long_label": labels.get(long_name, long_name),
            "long_momentum_pct": round(strong["momentum_pct"], 3), "long_beta": round(strong["beta"], 3),
            "long_capital": long_capital, "long_etfs": [] if cfg.universe_mode == "stock" else SECTOR_ETFS.get(long_name, []),
            "long_top_stocks": [] if cfg.universe_mode == "stock" else sector_top_stocks(long_name, cfg),
            "short_ticker": short_name, "short_label": labels.get(short_name, short_name),
            "short_momentum_pct": round(weak["momentum_pct"], 3), "short_beta": round(weak["beta"], 3),
            "short_capital": short_capital, "short_etfs": [] if cfg.universe_mode == "stock" else SECTOR_ETFS.get(short_name, []),
            "short_top_stocks": [] if cfg.universe_mode == "stock" else sector_top_stocks(short_name, cfg),
            "capital_allocated": round(capital_per_pair, 2), "net_beta_exposure": net_beta_exposure,
            "note": pair_note,
        })

    pair_summaries = [
        f"#{p['rank']}: {labels.get(p['long'], p['long'])}/{labels.get(p['short'], p['short'])}"
        for p in candidate_pairs
    ]
    not_in_any_pair_note = (
        f"{pair_scope} scan found {num_pairs} hedge pair(s) — {', '.join(pair_summaries)}."
    )

    results: list[dict[str, Any]] = []
    for name in names:
        if name in errors:
            results.append({"ticker": name, "label": labels.get(name, name), "error": errors[name]})
            continue
        m = metrics[name]
        assignment = role_by_name.get(name)
        if assignment is None:
            live = _sector_row(name, m, role="neutral", cfg=cfg, pair_note=not_in_any_pair_note, universe_size=len(names), num_pairs=num_pairs)
        else:
            live = _sector_row(
                name, m, role=assignment["role"], cfg=cfg,
                long_capital=assignment["long_capital"], short_capital=assignment["short_capital"],
                pair_note=assignment["pair_note"], universe_size=len(names),
                pair_rank=assignment["pair_rank"], num_pairs=num_pairs, pair_confidence=assignment["confidence"],
            )
        results.append({
            "ticker": name, "label": labels.get(name, name),
            "last_close": round(m["last_price"], 4), "live": live,
        })

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    pair_recommendations.sort(key=lambda p: p["confidence_pct"], reverse=True)

    return {
        "market": market,
        "strategy": "Intra-Hedging — Relative-Strength Long/Short (beta-neutral)",
        "benchmark": BENCHMARK, "universe_mode": cfg.universe_mode, "universe_desc": universe_desc,
        "results": results,
        "entries": entries,
        "entry_count": len(entries),
        "watchlist": [],
        "pair_recommendations": pair_recommendations,
        "pair_recommendation": pair_recommendations[0] if pair_recommendations else None,
    }
