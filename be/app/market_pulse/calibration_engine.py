"""
calibration_engine.py
----------------------
Walk-forward calibration harness — the audit's Fix 04. Nearly every engine
in this app emits a confidence % from a hand-tuned formula (fixed weights,
round-number thresholds) that has never been checked against what actually
happened afterward. "70% confidence" should mean "this confidence bucket
has actually resolved favorably 70% of the time," not "a formula produced
the number 70."

`walk_forward_backtest()` replays a signal function bar-by-bar over real
history, calling it only with the data that would have been available at
that point (no lookahead), then simulates what a real trade would have
experienced — first-touch target/stop against intrabar highs/lows, not just
a close-to-close return — and buckets the realized outcomes by the
confidence the signal itself reported at the time.

This is deliberately generic: any engine whose per-bar signal can be
expressed as `fn(history_df) -> {"direction": "LONG"|"SHORT", "confidence_pct": float} | None`
can be calibrated with it, without changing the engine itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

SignalFn = Callable[[pd.DataFrame], dict[str, Any] | None]

_LONG_LABELS = ("LONG", "UP", "BULLISH", "BUY")
_SHORT_LABELS = ("SHORT", "DOWN", "BEARISH", "SELL")

_CONFIDENCE_BUCKETS = [(0, 55), (55, 65), (65, 75), (75, 85), (85, 101)]


@dataclass
class CalibrationBucket:
    label: str
    n: int
    win_rate_pct: float
    avg_forward_return_pct: float


@dataclass
class CalibrationResult:
    total_signals: int
    buckets: list[CalibrationBucket]
    overall_win_rate_pct: float
    notes: list[str] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)


def walk_forward_backtest(
    df: pd.DataFrame,
    signal_fn: SignalFn,
    *,
    warmup_bars: int = 100,
    forward_bars: int = 10,
    target_pct: float = 1.0,
    stop_pct: float = 1.0,
    target_atr_mult: float | None = None,
    stop_atr_mult: float | None = None,
    atr_period: int = 14,
    step: int = 1,
) -> CalibrationResult:
    """Walk forward through `df`, calling `signal_fn` on the closed-bar
    history available at each step, and check what actually happened over
    the next `forward_bars`: did price hit the target in the signaled
    direction before hitting the stop against it (first-touch against
    intrabar high/low)? A window that resolves neither way (TIMEOUT) is
    scored by its mark-to-close return but excluded from the win-rate
    denominator — an undecided trade isn't a loss, but it isn't a win either.

    Target/stop distance is `target_pct`/`stop_pct` (flat, same for every
    instrument) by default. Pass `target_atr_mult`/`stop_atr_mult` instead to
    scale the distance by each bar's own ATR — a fixed % target treats a
    4%-ATR index and a 15%-ATR small-cap identically, which can flatten a
    real edge into noise for the volatile name and never let a calm name's
    edge resolve before the forward window runs out; ATR-scaled targets are
    the more honest test and the two shouldn't be compared directly.

    `step` > 1 skips bars between evaluations to speed up a long backtest at
    the cost of fewer samples — use 1 for a real calibration run.
    """
    n = len(df)
    if n < warmup_bars + forward_bars + 5:
        return CalibrationResult(
            total_signals=0, buckets=[], overall_win_rate_pct=0.0,
            notes=["Not enough history for a meaningful walk-forward run."],
        )

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values

    atr_values = None
    if target_atr_mult is not None or stop_atr_mult is not None:
        from app.market_pulse.indicators import add_atr

        atr_col = f"atr_{atr_period}"
        work = df if atr_col in df.columns else add_atr(df.copy(), atr_period)
        atr_values = work[atr_col].values

    records: list[dict[str, Any]] = []
    for i in range(warmup_bars, n - forward_bars, step):
        history = df.iloc[: i + 1]
        try:
            sig = signal_fn(history)
        except Exception:
            continue
        if not sig:
            continue
        direction = sig.get("direction")
        confidence = sig.get("confidence_pct")
        if confidence is None:
            continue
        is_long = direction in _LONG_LABELS
        is_short = direction in _SHORT_LABELS
        if not (is_long or is_short):
            continue

        entry = float(close[i])
        if entry <= 0:
            continue

        if atr_values is not None and not np.isnan(atr_values[i]) and atr_values[i] > 0:
            atr = float(atr_values[i])
            target_dist = atr * target_atr_mult if target_atr_mult is not None else entry * target_pct / 100
            stop_dist = atr * stop_atr_mult if stop_atr_mult is not None else entry * stop_pct / 100
        else:
            target_dist = entry * target_pct / 100
            stop_dist = entry * stop_pct / 100

        if is_long:
            target, stop = entry + target_dist, entry - stop_dist
        else:
            target, stop = entry - target_dist, entry + stop_dist

        outcome = "TIMEOUT"
        forward_ret = 0.0
        for j in range(i + 1, min(i + 1 + forward_bars, n)):
            if is_long:
                if low[j] <= stop:
                    outcome, forward_ret = "LOSS", (stop - entry) / entry * 100
                    break
                if high[j] >= target:
                    outcome, forward_ret = "WIN", (target - entry) / entry * 100
                    break
            else:
                if high[j] >= stop:
                    outcome, forward_ret = "LOSS", (entry - stop) / entry * 100
                    break
                if low[j] <= target:
                    outcome, forward_ret = "WIN", (entry - target) / entry * 100
                    break
        if outcome == "TIMEOUT":
            end_close = float(close[min(i + forward_bars, n - 1)])
            forward_ret = (end_close - entry) / entry * 100
            if is_short:
                forward_ret = -forward_ret

        records.append({"confidence": float(confidence), "outcome": outcome, "forward_ret": forward_ret})

    result = bucket_records(records)
    result.records = records
    return result


MultiSignalFn = Callable[[dict[str, pd.DataFrame]], dict[str, Any] | None]


def walk_forward_backtest_multi(
    dfs: dict[str, pd.DataFrame],
    signal_fn: MultiSignalFn,
    *,
    primary_tf: str,
    warmup_bars: int = 100,
    forward_bars: int = 10,
    target_pct: float = 1.0,
    stop_pct: float = 1.0,
    target_atr_mult: float | None = None,
    stop_atr_mult: float | None = None,
    atr_period: int = 14,
    step: int = 1,
) -> CalibrationResult:
    """Multi-timeframe sibling of `walk_forward_backtest` — for strategies
    that need more than one timeframe at once (e.g. "weekly bias + daily
    fakeout + 15m execution"), which most Trading Hub strategies are.

    `dfs` is every timeframe the strategy needs, already fetched in full
    (`{"1w": weekly_df, "1d": daily_df, "15m": ltf_df, ...}`). `primary_tf`
    is the execution timeframe — the one whose bars drive the walk-forward
    loop and the entry/target/stop simulation. At each step, every other
    timeframe in `dfs` is sliced down to only the bars that would actually
    have closed by that exact point in time (matched against the primary
    timeframe's current bar timestamp), so a weekly or daily context frame
    never leaks a bar from its own future into the signal function — the
    same no-lookahead guarantee as the single-timeframe harness, just
    enforced across every timeframe at once rather than just one.

    `signal_fn` receives `{tf: sliced_df, ...}` (same keys as `dfs`) and
    must return the same `{"direction", "confidence_pct"}` shape.
    """
    primary = dfs.get(primary_tf)
    if primary is None or primary.empty:
        return CalibrationResult(
            total_signals=0, buckets=[], overall_win_rate_pct=0.0,
            notes=[f"No data for primary timeframe '{primary_tf}'."],
        )

    n = len(primary)
    if n < warmup_bars + forward_bars + 5:
        return CalibrationResult(
            total_signals=0, buckets=[], overall_win_rate_pct=0.0,
            notes=["Not enough history for a meaningful walk-forward run."],
        )

    close = primary["close"].values
    high = primary["high"].values
    low = primary["low"].values
    primary_index = primary.index

    atr_values = None
    if target_atr_mult is not None or stop_atr_mult is not None:
        from app.market_pulse.indicators import add_atr

        atr_col = f"atr_{atr_period}"
        work = primary if atr_col in primary.columns else add_atr(primary.copy(), atr_period)
        atr_values = work[atr_col].values

    other_tfs = [tf for tf in dfs if tf != primary_tf]

    records: list[dict[str, Any]] = []
    for i in range(warmup_bars, n - forward_bars, step):
        as_of = primary_index[i]
        history: dict[str, pd.DataFrame] = {primary_tf: primary.iloc[: i + 1]}
        skip = False
        for tf in other_tfs:
            odf = dfs[tf]
            sliced = odf[odf.index <= as_of]
            if sliced.empty:
                skip = True
                break
            history[tf] = sliced
        if skip:
            continue

        try:
            sig = signal_fn(history)
        except Exception:
            continue
        if not sig:
            continue
        direction = sig.get("direction")
        confidence = sig.get("confidence_pct")
        if confidence is None:
            continue
        is_long = direction in _LONG_LABELS
        is_short = direction in _SHORT_LABELS
        if not (is_long or is_short):
            continue

        entry = float(close[i])
        if entry <= 0:
            continue

        if atr_values is not None and not np.isnan(atr_values[i]) and atr_values[i] > 0:
            atr = float(atr_values[i])
            target_dist = atr * target_atr_mult if target_atr_mult is not None else entry * target_pct / 100
            stop_dist = atr * stop_atr_mult if stop_atr_mult is not None else entry * stop_pct / 100
        else:
            target_dist = entry * target_pct / 100
            stop_dist = entry * stop_pct / 100

        if is_long:
            target, stop = entry + target_dist, entry - stop_dist
        else:
            target, stop = entry - target_dist, entry + stop_dist

        outcome = "TIMEOUT"
        forward_ret = 0.0
        for j in range(i + 1, min(i + 1 + forward_bars, n)):
            if is_long:
                if low[j] <= stop:
                    outcome, forward_ret = "LOSS", (stop - entry) / entry * 100
                    break
                if high[j] >= target:
                    outcome, forward_ret = "WIN", (target - entry) / entry * 100
                    break
            else:
                if high[j] >= stop:
                    outcome, forward_ret = "LOSS", (entry - stop) / entry * 100
                    break
                if low[j] <= target:
                    outcome, forward_ret = "WIN", (entry - target) / entry * 100
                    break
        if outcome == "TIMEOUT":
            end_close = float(close[min(i + forward_bars, n - 1)])
            forward_ret = (end_close - entry) / entry * 100
            if is_short:
                forward_ret = -forward_ret

        records.append({"confidence": float(confidence), "outcome": outcome, "forward_ret": forward_ret})

    result = bucket_records(records)
    result.records = records
    return result


def bucket_records(records: list[dict[str, Any]]) -> CalibrationResult:
    """Aggregate a flat list of {"confidence","outcome","forward_ret"} records
    into confidence buckets — factored out of `walk_forward_backtest` so
    records from multiple tickers/runs can be pooled into one combined
    calibration table instead of only ever seeing one ticker's (thin,
    noisy) per-run buckets."""
    if not records:
        return CalibrationResult(
            total_signals=0, buckets=[], overall_win_rate_pct=0.0,
            notes=["No usable directional signals in this record set."],
        )

    buckets: list[CalibrationBucket] = []
    for lo, hi in _CONFIDENCE_BUCKETS:
        in_bucket = [r for r in records if lo <= r["confidence"] < hi]
        if not in_bucket:
            continue
        decided = [r for r in in_bucket if r["outcome"] in ("WIN", "LOSS")]
        wins = sum(1 for r in decided if r["outcome"] == "WIN")
        win_rate = (wins / len(decided) * 100) if decided else 0.0
        avg_ret = float(np.mean([r["forward_ret"] for r in in_bucket]))
        buckets.append(CalibrationBucket(
            label=f"{lo}-{min(hi, 100)}%", n=len(in_bucket),
            win_rate_pct=round(win_rate, 1), avg_forward_return_pct=round(avg_ret, 3),
        ))

    total_decided = [r for r in records if r["outcome"] in ("WIN", "LOSS")]
    total_wins = sum(1 for r in total_decided if r["outcome"] == "WIN")
    overall = (total_wins / len(total_decided) * 100) if total_decided else 0.0

    notes = []
    thin_buckets = [b.label for b in buckets if b.n < 20]
    if thin_buckets:
        notes.append(f"Buckets with <20 samples (treat as directional, not reliable): {', '.join(thin_buckets)}.")

    return CalibrationResult(
        total_signals=len(records), buckets=buckets, overall_win_rate_pct=round(overall, 1), notes=notes,
    )
