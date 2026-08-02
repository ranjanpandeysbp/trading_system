"""
advanced_backtest_report.py
---------------------------
Professional-grade stress metrics for backtest trade lists:
CAGR, payoff, profit factor, expectancy, Sharpe/Sortino/Calmar,
drawdown duration, Monte Carlo, in/out-of-sample split, and a
plain-English good / bad / how-to-improve assessment.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

_MC_RUNS = 500
_MC_SEED = 42


def _empty_metrics() -> dict[str, Any]:
    return {
        "num_trades": 0,
        "win_rate_pct": None,
        "total_return_pct": 0.0,
        "avg_return_per_trade_pct": None,
        "max_drawdown_pct": 0.0,
        "cagr_pct": None,
        "payoff_ratio": None,
        "profit_factor": None,
        "expectancy_pct": None,
        "avg_win_pct": None,
        "avg_loss_pct": None,
        "sharpe_ratio": None,
        "sortino_ratio": None,
        "calmar_ratio": None,
        "annual_volatility_pct": None,
        "max_drawdown_duration_trades": None,
        "max_consecutive_wins": 0,
        "max_consecutive_losses": 0,
        "best_trade_pct": None,
        "worst_trade_pct": None,
    }


def _pnl_series(trades: list[dict[str, Any]]) -> pd.Series:
    """Normalize trade pnl to fraction.

    App trade records store ``pnl_pct`` as a *percent* number
    (e.g. ``1.25`` means +1.25%). Convert to fraction for compounding.
    """
    vals: list[float] = []
    for t in trades:
        raw = t.get("pnl_pct")
        if raw is None:
            continue
        vals.append(float(raw) / 100.0)
    return pd.Series(vals, dtype=float)


def _max_streak(bools: pd.Series) -> int:
    longest = current = 0
    for v in bools:
        current = current + 1 if bool(v) else 0
        longest = max(longest, current)
    return int(longest)


def _drawdown_duration_trades(equity: pd.Series) -> int:
    """Longest underwater stretch measured in trade-steps (peak → recovery)."""
    if len(equity) < 2:
        return 0
    peak = equity.cummax()
    underwater = equity < peak
    longest = current = 0
    for u in underwater:
        if u:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return int(longest)


def _years_from_period(period: str | None, trades: list[dict[str, Any]]) -> float:
    if period:
        mapping = {
            "7d": 7 / 365.25, "30d": 30 / 365.25, "60d": 60 / 365.25,
            "90d": 90 / 365.25, "180d": 180 / 365.25,
            "1y": 1.0, "2y": 2.0, "5y": 5.0, "10y": 10.0,
        }
        if period in mapping:
            return max(mapping[period], 1 / 365.25)
        if period.endswith("d") and period[:-1].isdigit():
            return max(int(period[:-1]) / 365.25, 1 / 365.25)
        if period.endswith("y") and period[:-1].isdigit():
            return max(float(period[:-1]), 1 / 365.25)

    times: list[pd.Timestamp] = []
    for t in trades:
        raw = t.get("exit_time") or t.get("Datetime") or t.get("entry_time")
        if raw is None:
            continue
        try:
            times.append(pd.Timestamp(raw))
        except Exception:
            continue
    if len(times) >= 2:
        days = max((max(times) - min(times)).days, 1)
        return max(days / 365.25, 1 / 365.25)
    n = max(len(trades), 1)
    return max(n / 52.0, 1 / 365.25)


def compute_core_metrics(
    trades: list[dict[str, Any]],
    *,
    period: str | None = None,
    costs_pct: float = 0.0008,
) -> dict[str, Any]:
    pnl = _pnl_series(trades)
    if pnl.empty:
        out = _empty_metrics()
        out["costs_pct"] = costs_pct
        out["costs_bps"] = round(costs_pct * 10_000, 2)
        return out

    equity = (1.0 + pnl).cumprod()
    running_max = equity.cummax()
    dd = (equity - running_max) / running_max
    max_dd = float(dd.min() * 100.0)
    total_return = float((equity.iloc[-1] - 1.0) * 100.0)

    years = _years_from_period(period, trades)
    final_eq = float(equity.iloc[-1])
    cagr = ((final_eq ** (1.0 / years)) - 1.0) * 100.0 if final_eq > 0 else -100.0

    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    n = len(pnl)
    win_rate = 100.0 * len(wins) / n
    avg_win = float(wins.mean() * 100.0) if len(wins) else 0.0
    avg_loss = float(losses.mean() * 100.0) if len(losses) else 0.0
    payoff = (abs(avg_win / avg_loss) if avg_loss != 0 else (float("inf") if avg_win > 0 else None))

    gross_win = float(wins.sum()) if len(wins) else 0.0
    gross_loss = float(abs(losses.sum())) if len(losses) else 0.0
    if gross_loss > 0:
        profit_factor = gross_win / gross_loss
    else:
        profit_factor = float("inf") if gross_win > 0 else 0.0

    expectancy = float(pnl.mean() * 100.0)

    trades_per_year = n / years
    mean_r = float(pnl.mean())
    std_r = float(pnl.std(ddof=1)) if n > 1 else 0.0
    if std_r > 0:
        sharpe = (mean_r / std_r) * np.sqrt(max(trades_per_year, 1.0))
    else:
        sharpe = 0.0
    downside = pnl[pnl < 0]
    dstd = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    if dstd > 0:
        sortino = (mean_r / dstd) * np.sqrt(max(trades_per_year, 1.0))
    else:
        sortino = 0.0 if mean_r <= 0 else float("inf")
    calmar = (cagr / abs(max_dd)) if max_dd != 0 else (0.0 if cagr <= 0 else float("inf"))
    ann_vol = std_r * np.sqrt(max(trades_per_year, 1.0)) * 100.0

    def _finite(x: float | None, digits: int = 3) -> float | None:
        if x is None:
            return None
        if not np.isfinite(x):
            return None
        return round(float(x), digits)

    return {
        "num_trades": n,
        "win_rate_pct": round(win_rate, 2),
        "total_return_pct": round(total_return, 2),
        "avg_return_per_trade_pct": round(expectancy, 3),
        "max_drawdown_pct": round(max_dd, 2),
        "cagr_pct": round(cagr, 2),
        "payoff_ratio": _finite(payoff, 3),
        "profit_factor": _finite(profit_factor, 3) if profit_factor != float("inf") else None,
        "profit_factor_display": "∞" if profit_factor == float("inf") else (
            round(profit_factor, 3) if np.isfinite(profit_factor) else None
        ),
        "expectancy_pct": round(expectancy, 3),
        "avg_win_pct": round(avg_win, 3),
        "avg_loss_pct": round(avg_loss, 3),
        "sharpe_ratio": _finite(sharpe, 3),
        "sortino_ratio": _finite(sortino, 3),
        "calmar_ratio": _finite(calmar, 3),
        "annual_volatility_pct": round(ann_vol, 2),
        "max_drawdown_duration_trades": _drawdown_duration_trades(equity),
        "max_consecutive_wins": _max_streak(pnl > 0),
        "max_consecutive_losses": _max_streak(pnl <= 0),
        "best_trade_pct": round(float(pnl.max() * 100.0), 3),
        "worst_trade_pct": round(float(pnl.min() * 100.0), 3),
        "years_analyzed": round(years, 3),
        "costs_pct": costs_pct,
        "costs_bps": round(costs_pct * 10_000, 2),
        "equity_final": round(final_eq, 4),
    }


def run_monte_carlo(
    trades: list[dict[str, Any]],
    *,
    n_runs: int = _MC_RUNS,
    seed: int = _MC_SEED,
) -> dict[str, Any]:
    pnl = _pnl_series(trades)
    if len(pnl) < 3:
        return {
            "runs": 0,
            "note": "Need at least 3 trades for a meaningful Monte Carlo shuffle.",
        }

    rng = np.random.default_rng(seed)
    finals: list[float] = []
    max_dds: list[float] = []
    for _ in range(n_runs):
        shuffled = rng.permutation(pnl.to_numpy())
        eq = np.cumprod(1.0 + shuffled)
        finals.append(float(eq[-1]))
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / peak
        max_dds.append(float(dd.min() * 100.0))

    finals_a = np.asarray(finals)
    dds_a = np.asarray(max_dds)
    ret_pct = (finals_a - 1.0) * 100.0
    p_half = float(np.mean(finals_a < 0.5) * 100.0)
    p_profit = float(np.mean(finals_a > 1.0) * 100.0)

    return {
        "runs": n_runs,
        "median_final_return_pct": round(float(np.median(ret_pct)), 2),
        "p5_final_return_pct": round(float(np.percentile(ret_pct, 5)), 2),
        "p95_final_return_pct": round(float(np.percentile(ret_pct, 95)), 2),
        "median_max_drawdown_pct": round(float(np.median(dds_a)), 2),
        "p5_max_drawdown_pct": round(float(np.percentile(dds_a, 5)), 2),
        "probability_profit_pct": round(p_profit, 1),
        "probability_half_equity_pct": round(p_half, 1),
        "note": (
            "Trade sequence shuffled randomly — estimates luck risk of "
            "catastrophic streaks independent of strategy edge."
        ),
    }


def run_out_of_sample(
    trades: list[dict[str, Any]],
    *,
    period: str | None = None,
    costs_pct: float = 0.0008,
    is_frac: float = 0.7,
) -> dict[str, Any]:
    if len(trades) < 8:
        return {
            "available": False,
            "note": "Need at least 8 trades to split in-sample vs out-of-sample.",
        }

    dated = []
    for t in trades:
        raw = t.get("exit_time") or t.get("Datetime")
        try:
            ts = pd.Timestamp(raw) if raw is not None else None
        except Exception:
            ts = None
        dated.append((ts, t))
    if all(x[0] is not None for x in dated):
        dated.sort(key=lambda x: x[0])
        ordered = [t for _, t in dated]
    else:
        ordered = list(trades)

    split = max(3, int(len(ordered) * is_frac))
    split = min(split, len(ordered) - 3)
    is_trades = ordered[:split]
    oos_trades = ordered[split:]
    is_m = compute_core_metrics(is_trades, period=period, costs_pct=costs_pct)
    oos_m = compute_core_metrics(oos_trades, period=period, costs_pct=costs_pct)

    def _delta(a: float | None, b: float | None) -> float | None:
        if a is None or b is None:
            return None
        return round(float(b) - float(a), 3)

    degradation = {
        "total_return_pct": _delta(is_m.get("total_return_pct"), oos_m.get("total_return_pct")),
        "profit_factor": _delta(is_m.get("profit_factor"), oos_m.get("profit_factor")),
        "win_rate_pct": _delta(is_m.get("win_rate_pct"), oos_m.get("win_rate_pct")),
        "expectancy_pct": _delta(is_m.get("expectancy_pct"), oos_m.get("expectancy_pct")),
    }
    oos_ret = oos_m.get("total_return_pct") or 0
    is_ret = is_m.get("total_return_pct") or 0
    robust = bool(oos_ret > 0 and (is_ret <= 0 or oos_ret >= 0.4 * is_ret))

    return {
        "available": True,
        "in_sample_trades": len(is_trades),
        "out_of_sample_trades": len(oos_trades),
        "in_sample": {
            "total_return_pct": is_m.get("total_return_pct"),
            "win_rate_pct": is_m.get("win_rate_pct"),
            "profit_factor": is_m.get("profit_factor"),
            "expectancy_pct": is_m.get("expectancy_pct"),
            "max_drawdown_pct": is_m.get("max_drawdown_pct"),
        },
        "out_of_sample": {
            "total_return_pct": oos_m.get("total_return_pct"),
            "win_rate_pct": oos_m.get("win_rate_pct"),
            "profit_factor": oos_m.get("profit_factor"),
            "expectancy_pct": oos_m.get("expectancy_pct"),
            "max_drawdown_pct": oos_m.get("max_drawdown_pct"),
        },
        "oos_minus_is": degradation,
        "looks_robust": robust,
        "note": (
            "First ~70% of trades = in-sample proxy; last ~30% = blind out-of-sample. "
            "Large OOS collapse vs IS often means curve-fitting."
        ),
    }


def assess_strategy(
    metrics: dict[str, Any],
    *,
    monte_carlo: dict[str, Any] | None = None,
    oos: dict[str, Any] | None = None,
    costs_pct: float = 0.0008,
) -> dict[str, Any]:
    good: list[str] = []
    bad: list[str] = []
    improve: list[str] = []

    n = int(metrics.get("num_trades") or 0)
    wr = metrics.get("win_rate_pct")
    pf = metrics.get("profit_factor")
    payoff = metrics.get("payoff_ratio")
    exp = metrics.get("expectancy_pct")
    cagr = metrics.get("cagr_pct")
    ret = metrics.get("total_return_pct")
    dd = abs(float(metrics.get("max_drawdown_pct") or 0))
    sharpe = metrics.get("sharpe_ratio")
    sortino = metrics.get("sortino_ratio")
    calmar = metrics.get("calmar_ratio")
    dd_len = metrics.get("max_drawdown_duration_trades")
    consec_loss = int(metrics.get("max_consecutive_losses") or 0)

    if n >= 30:
        good.append(f"We have enough trades to learn from ({n} completed). That is a usable sample, not a lucky handful.")
    elif n >= 10:
        improve.append(
            f"Only {n} trades so far — treat the result as a hint. Re-run on a longer period or more tickers before sizing up."
        )
    else:
        bad.append(f"Too few trades ({n}) to trust. This can easily be luck, not a real edge.")
        improve.append("Re-run on 2–5 years of history, or scan more liquid tickers, until you have dozens of trades.")

    if exp is not None and exp > 0:
        good.append(
            f"The average trade makes money after costs (about {exp:.3f}% per trade). That means there is a real edge in this window."
        )
    elif exp is not None and exp <= 0:
        bad.append(
            f"The average trade loses after costs (about {exp:.3f}% per trade). Taking more of these trades will not help."
        )
        improve.append(
            "Take fewer weak setups, exit losers faster, or let winners run longer so the average trade turns positive."
        )

    if pf is not None:
        if 1.5 <= pf <= 3.0:
            good.append(
                f"Profits are comfortably larger than losses (profit factor {pf:.2f}). This is the healthy 1.5–3 range."
            )
        elif pf > 4.0:
            bad.append(
                f"Results look almost too good (profit factor {pf:.2f}). That often means the rules were fitted too tightly to past charts."
            )
            improve.append(
                "Simplify the rules, freeze them, and check the blind (out-of-sample) half again before believing the number."
            )
        elif pf >= 1.0:
            improve.append(
                f"You barely make more than you lose (profit factor {pf:.2f}). Aim closer to 1.5+ before putting serious money on it."
            )
        else:
            bad.append(f"Losses beat profits overall (profit factor {pf:.2f}). This combo loses money in the test.")
            improve.append("Do not trade this live. Change exits/entries or pick a different strategy for this ticker.")
    elif metrics.get("profit_factor_display") == "∞":
        good.append("No losing trades showed up in this sample — impressive, but easy to over-trust.")
        improve.append("You need more trades (including some losers) before calling this durable. Re-test on a longer window.")

    if wr is not None and payoff is not None:
        if wr < 40 and payoff >= 2.0:
            good.append(
                f"You win only about {wr:.0f}% of the time, but winners are about {payoff:.2f}× bigger than losers — that can still be a solid approach."
            )
        elif wr >= 55 and payoff < 1.0:
            improve.append(
                f"You win often ({wr:.0f}%), but winners are smaller than losers (payoff {payoff:.2f}:1). Let winners run more, or cut losers sooner."
            )
        elif wr < 35 and payoff < 1.5:
            bad.append(
                f"Low win rate ({wr:.0f}%) and winners not big enough vs losers (payoff {payoff}). The edge looks fragile."
            )
            improve.append("Either improve entry quality (higher win rate) or improve reward-to-risk (bigger winners / smaller losers).")

    if cagr is not None and cagr > 10:
        good.append(f"Annualized growth looks strong (about {cagr:.1f}% per year if this pace continued).")
    elif cagr is not None and cagr < 0:
        bad.append(f"On a yearly basis the account shrinks (about {cagr:.1f}% CAGR). This destroys capital over time.")

    if dd <= 15:
        good.append(f"The worst peak-to-trough drop stayed manageable (about {dd:.1f}%).")
    elif dd <= 30:
        improve.append(
            f"Worst drop was about {dd:.1f}%. Trade smaller so you can emotionally and financially survive a full drawdown."
        )
    else:
        bad.append(
            f"Worst drop was severe (about {dd:.1f}%). Most people quit before the strategy recovers."
        )
        improve.append(
            "Add a hard ‘stop trading if account drops X%’ rule, reduce position size, or skip high-volatility regimes."
        )

    if dd_len is not None and n > 0 and dd_len >= max(10, n // 3):
        bad.append(
            f"The account stayed underwater for a long stretch ({dd_len} trades). That is hard to sit through with real money."
        )
        improve.append("Shorten how long you hold losers, or add filters that pause trading in choppy/no-edge markets.")

    if sharpe is not None:
        if sharpe >= 2.0:
            good.append(f"Reward vs bumpiness looks excellent (Sharpe {sharpe:.2f}).")
        elif sharpe >= 1.0:
            good.append(f"Reward vs bumpiness is acceptable (Sharpe {sharpe:.2f}).")
        elif sharpe < 0.5:
            bad.append(
                f"Returns do not compensate for how bumpy the ride is (Sharpe {sharpe:.2f})."
            )
            improve.append("Cut noisy/low-quality signals so the equity curve is smoother, or improve win quality.")

    if sortino is not None and sortino >= 2.0:
        good.append(
            f"Downside risk looks well controlled relative to return (Sortino {sortino:.2f})."
        )
    if calmar is not None and calmar >= 3.0:
        good.append(
            f"Yearly growth is strong compared with the worst drop (Calmar {calmar:.2f})."
        )
    elif calmar is not None and calmar < 0.5 and (cagr or 0) > 0:
        improve.append(
            f"Growth vs pain is weak (Calmar {calmar:.2f}). Either grow faster or shrink the worst drawdown."
        )

    if consec_loss >= 6:
        bad.append(
            f"There was a streak of {consec_loss} losses in a row. Plan your size for that, or you will over-react live."
        )
        improve.append(
            "Decide in advance: pause after N losses, and size positions so an unlucky streak is survivable."
        )

    good.append(
        f"Every trade already includes a cost haircut of about {costs_pct * 10_000:.1f} basis points "
        "(fees + slightly worse fills)."
    )
    if costs_pct < 0.0003:
        improve.append(
            "The cost assumption looks optimistic. Re-run with higher costs (roughly 8–15 bps) to see if the edge survives."
        )
    if n > 80 and costs_pct < 0.001:
        improve.append(
            "You trade often — fees add up. Stress-test again with higher commission/slippage before going live."
        )

    if oos and oos.get("available"):
        if oos.get("looks_robust"):
            good.append(
                "The ‘blind’ second half of trades still looked okay vs the first half — early sign it is not only curve-fitted."
            )
        else:
            bad.append(
                "The blind second half was much weaker than the first half — this may have been fitted to past data."
            )
            improve.append(
                "Freeze the rules. Test on a new ticker or a newer period. Do not keep tweaking until the blind half looks good."
            )

    if monte_carlo and monte_carlo.get("runs"):
        p_half = monte_carlo.get("probability_half_equity_pct") or 0
        p5_dd = monte_carlo.get("p5_max_drawdown_pct")
        if p_half >= 10:
            bad.append(
                f"In random reshuffles, about {p_half:.0f}% of paths end below half the starting account — path luck risk is high."
            )
            improve.append("Risk less per trade and require a stronger profit factor before using real capital.")
        elif p_half <= 2 and (monte_carlo.get("probability_profit_pct") or 0) >= 70:
            good.append(
                f"In random reshuffles, about {monte_carlo.get('probability_profit_pct')}% of paths stay profitable, "
                f"and ending below half-account is rare (~{p_half:.1f}%)."
            )
        if p5_dd is not None and abs(float(p5_dd)) >= 40:
            improve.append(
                f"In an unlucky shuffle, drawdown can reach about {p5_dd}%. Size the strategy for that nightmare case, not only the average case."
            )

    if ret is not None and ret > 0 and not bad:
        good.append("After costs, the strategy finished this window in profit.")
    if not good and not bad:
        improve.append("Collect more trades and re-run this report before deciding the strategy is viable.")

    score = 5.0
    if exp is not None:
        score += 1.5 if exp > 0 else -2.0
    if pf is not None:
        if 1.5 <= pf <= 3.5:
            score += 1.5
        elif pf > 4:
            score -= 0.5
        elif pf < 1:
            score -= 2.0
    if sharpe is not None:
        score += min(max(float(sharpe), -1), 2) * 0.8
    if dd > 30:
        score -= 1.5
    if n < 10:
        score -= 1.5
    if oos and oos.get("available") and not oos.get("looks_robust"):
        score -= 1.0
    score = max(0.0, min(10.0, score))
    if score >= 7.5:
        verdict = "PASS — interesting enough to paper-trade next; do not jump straight to full live size."
    elif score >= 5.0:
        verdict = "MIXED — there may be an edge, but risks or thin data need fixing first."
    else:
        verdict = "FAIL — do not risk live capital on this version as-is."

    return {
        "score": round(score, 1),
        "verdict": verdict,
        "good": good,
        "bad": bad,
        "improve": improve,
    }


def build_advanced_report(
    trades: list[dict[str, Any]] | None,
    *,
    period: str | None = None,
    costs_pct: float = 0.0008,
    label: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trades = trades or []
    metrics = compute_core_metrics(trades, period=period, costs_pct=costs_pct)
    monte = run_monte_carlo(trades)
    oos = run_out_of_sample(trades, period=period, costs_pct=costs_pct)
    assessment = assess_strategy(metrics, monte_carlo=monte, oos=oos, costs_pct=costs_pct)

    return {
        "label": label,
        "context": context or {},
        "core_performance": {
            "cagr_pct": metrics.get("cagr_pct"),
            "total_return_pct": metrics.get("total_return_pct"),
            "win_rate_pct": metrics.get("win_rate_pct"),
            "payoff_ratio": metrics.get("payoff_ratio"),
            "profit_factor": metrics.get("profit_factor"),
            "profit_factor_display": metrics.get("profit_factor_display"),
            "expectancy_pct": metrics.get("expectancy_pct"),
            "avg_win_pct": metrics.get("avg_win_pct"),
            "avg_loss_pct": metrics.get("avg_loss_pct"),
            "num_trades": metrics.get("num_trades"),
            "best_trade_pct": metrics.get("best_trade_pct"),
            "worst_trade_pct": metrics.get("worst_trade_pct"),
            "years_analyzed": metrics.get("years_analyzed"),
        },
        "risk_drawdown": {
            "max_drawdown_pct": metrics.get("max_drawdown_pct"),
            "max_drawdown_duration_trades": metrics.get("max_drawdown_duration_trades"),
            "max_consecutive_wins": metrics.get("max_consecutive_wins"),
            "max_consecutive_losses": metrics.get("max_consecutive_losses"),
            "annual_volatility_pct": metrics.get("annual_volatility_pct"),
        },
        "risk_adjusted": {
            "sharpe_ratio": metrics.get("sharpe_ratio"),
            "sortino_ratio": metrics.get("sortino_ratio"),
            "calmar_ratio": metrics.get("calmar_ratio"),
        },
        "execution_costs": {
            "costs_pct": metrics.get("costs_pct"),
            "costs_bps": metrics.get("costs_bps"),
            "slippage_note": (
                "Each round-turn is penalized by the configured costs_pct "
                "(commission + slippage proxy). Raise it to stress-test HFT-style systems."
            ),
        },
        "robustness": {
            "out_of_sample": oos,
            "monte_carlo": monte,
        },
        "assessment": assessment,
        "metrics": metrics,
    }


def enrich_stats_dict(
    stats: dict[str, Any],
    *,
    period: str | None = None,
    costs_pct: float = 0.0008,
) -> dict[str, Any]:
    """Merge advanced fields into a backtest_signals-style stats dict."""
    trades = stats.get("trades") or []
    if not isinstance(trades, list):
        trades = []
    advanced = build_advanced_report(trades, period=period, costs_pct=costs_pct)
    metrics = advanced.get("metrics") or {}
    out = dict(stats)
    for key in (
        "cagr_pct", "payoff_ratio", "profit_factor", "profit_factor_display",
        "expectancy_pct", "avg_win_pct", "avg_loss_pct",
        "sharpe_ratio", "sortino_ratio", "calmar_ratio",
        "annual_volatility_pct", "max_drawdown_duration_trades",
        "max_consecutive_wins", "max_consecutive_losses",
        "best_trade_pct", "worst_trade_pct", "years_analyzed",
        "costs_pct", "costs_bps",
    ):
        if key in metrics and metrics[key] is not None:
            out[key] = metrics[key]
    out["advanced_report"] = {
        k: advanced[k]
        for k in (
            "core_performance", "risk_drawdown", "risk_adjusted",
            "execution_costs", "robustness", "assessment",
        )
    }
    return out
