"""
mtf_scanner_engine.py
---------------------
Institutional Multi-Timeframe Scanner — 7-component confluence engine.

Components (weighted):
  Trend 25% · Momentum 20% · Price Action 15% · S/R 15%
  Volume 10% · Volatility/Breakout 10% · Structure 5%
"""

from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np
import pandas as pd
from scipy import stats
from scipy.signal import argrelextrema

from app.market_pulse.gap_trading import fetch_data_for_gap_scan

TF_ORDER = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]

TIMEFRAMES: dict[str, dict[str, str]] = {
    "1m":  {"label": "1-Minute  (Scalping)",   "style": "Scalp",     "hold": "1–15 minutes"},
    "5m":  {"label": "5-Minute  (Scalping)",   "style": "Scalp",     "hold": "15–60 minutes"},
    "15m": {"label": "15-Minute (Intraday)",   "style": "Intraday",  "hold": "15 min – 2 hours"},
    "30m": {"label": "30-Minute (Intraday)",   "style": "Intraday",  "hold": "1 – 3 hours"},
    "1h":  {"label": "1-Hour    (Swing)",      "style": "Swing",     "hold": "4 hours – 2 days"},
    "4h":  {"label": "4-Hour    (Swing)",      "style": "Swing",     "hold": "1 – 5 days"},
    "1d":  {"label": "Daily     (Position)",   "style": "Position",  "hold": "1 – 4 weeks"},
    "1w":  {"label": "Weekly    (Position)",   "style": "Position",  "hold": "1 – 3 months"},
}

SETUP_PRIORITY = {
    "READY": 100,
    "WATCH": 70,
    "LOW CONFIDENCE": 40,
    "NO SETUP": 10,
}

MIN_BARS = 30


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out.columns = [str(c).lower() for c in out.columns]
    required = {"open", "high", "low", "close"}
    if not required.issubset(set(out.columns)):
        return pd.DataFrame()
    if "volume" not in out.columns:
        out["volume"] = 0.0
    if not isinstance(out.index, pd.DatetimeIndex):
        try:
            out.index = pd.to_datetime(out.index)
        except Exception:
            pass
    if out.index.tzinfo is not None:
        out.index = out.index.tz_localize(None)
    return out.dropna(subset=["open", "high", "low", "close"])


def _resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df.resample("4h").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna()


def fetch_mtf_data(
    symbol: str,
    tf: str,
    market: str,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 300,
) -> pd.DataFrame:
    """Fetch OHLCV for one timeframe via Groww/CoinDCX with yfinance fallback."""
    df = fetch_data_for_gap_scan(symbol, tf, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty:
        return df
    if tf == "4h" and len(df) >= MIN_BARS:
        # Ensure 4H bars when API returned finer resolution
        if len(df) > limit * 2:
            df = _resample_4h(df)
    return df.tail(limit)


def bias_label(score: float) -> str:
    if score >= 65:
        return "BULLISH"
    if score >= 55:
        return "MILDLY BULLISH"
    if score <= 35:
        return "BEARISH"
    if score <= 45:
        return "MILDLY BEARISH"
    return "NEUTRAL"


def trend_arrow_label(score: float) -> str:
    if score >= 65:
        return "▲ BULLISH"
    if score >= 55:
        return "↗ MILDLY BULLISH"
    if score <= 35:
        return "▼ BEARISH"
    if score <= 45:
        return "↘ MILDLY BEARISH"
    return "→ NEUTRAL"


class MTFAnalyzer:
    """7-component institutional MTF scoring engine."""

    def __init__(self, df: pd.DataFrame):
        self.df = normalize_ohlcv(df)
        self.close = self.df["close"]
        self.high = self.df["high"]
        self.low = self.df["low"]
        self.open = self.df["open"]
        self.vol = self.df["volume"]
        self.n = len(self.df)
        self.scores: dict[str, tuple[float, int, str]] = {}
        if self.n >= MIN_BARS:
            self._compute_all()

    def _compute_all(self) -> None:
        self._trend()
        self._momentum()
        self._price_action()
        self._support_resistance()
        self._volume()
        self._volatility_breakout()
        self._structure()

    # ── 1. TREND (25%) ──────────────────────────────────────────────────────
    def _trend(self) -> None:
        c = self.close
        sma20 = c.rolling(20).mean()
        sma50 = c.rolling(50).mean()
        sma200 = c.rolling(200).mean() if self.n >= 200 else None
        ema9 = c.ewm(span=9, adjust=False).mean()
        ema21 = c.ewm(span=21, adjust=False).mean()

        score = 50.0
        signals: list[str] = []

        if c.iloc[-1] > sma20.iloc[-1]:
            score += 5
            signals.append("P>SMA20")
        else:
            score -= 5
        if c.iloc[-1] > sma50.iloc[-1]:
            score += 5
            signals.append("P>SMA50")
        else:
            score -= 5
        if sma200 is not None:
            if c.iloc[-1] > sma200.iloc[-1]:
                score += 7
                signals.append("P>SMA200")
            else:
                score -= 7

        if sma20.iloc[-1] > sma50.iloc[-1]:
            score += 5
            signals.append("SMA20>SMA50")
        else:
            score -= 5
        if ema9.iloc[-1] > ema21.iloc[-1]:
            score += 4
            signals.append("EMA9>EMA21")
        else:
            score -= 4

        if self.n >= 55:
            slope = (sma50.iloc[-1] - sma50.iloc[-5]) / sma50.iloc[-5] * 100
            if slope > 0.1:
                score += 4
                signals.append("SMA50↑slope")
            elif slope < -0.1:
                score -= 4

        if self.n >= 20:
            y = c.iloc[-20:].values
            x = np.arange(20)
            m, _, r, _, _ = stats.linregress(x, y)
            r2 = r ** 2
            if m > 0 and r2 > 0.6:
                score += 6
                signals.append(f"LR↑ R²={r2:.2f}")
            elif m < 0 and r2 > 0.6:
                score -= 6

        self.scores["Trend"] = (max(0, min(100, score)), 25, " | ".join(signals) or "Mixed")

    # ── 2. MOMENTUM (20%) ───────────────────────────────────────────────────
    def _momentum(self) -> None:
        c = self.close
        score = 50.0
        signals: list[str] = []

        delta = c.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        rv = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0

        if rv > 70:
            score += 3
            signals.append(f"RSI={rv:.1f} OB")
        elif rv > 55:
            score += 8
            signals.append(f"RSI={rv:.1f} Bull")
        elif rv > 45:
            score += 2
            signals.append(f"RSI={rv:.1f} Neutral")
        elif rv > 30:
            score -= 8
            signals.append(f"RSI={rv:.1f} Bear")
        else:
            score -= 3
            signals.append(f"RSI={rv:.1f} OS")

        if len(rsi.dropna()) >= 5:
            rsi_slope = rsi.iloc[-1] - rsi.iloc[-5]
            if rsi_slope > 3:
                score += 4
                signals.append("RSI↑")
            elif rsi_slope < -3:
                score -= 4

        low14 = self.low.rolling(14).min()
        high14 = self.high.rolling(14).max()
        stoch_k = 100 * (c - low14) / (high14 - low14).replace(0, np.nan)
        stoch_d = stoch_k.rolling(3).mean()
        sk = float(stoch_k.iloc[-1]) if not pd.isna(stoch_k.iloc[-1]) else 50.0
        sd = float(stoch_d.iloc[-1]) if not pd.isna(stoch_d.iloc[-1]) else 50.0
        if sk > sd and sk < 80:
            score += 5
            signals.append(f"Stoch↑{sk:.0f}")
        elif sk < sd and sk > 20:
            score -= 5
            signals.append(f"Stoch↓{sk:.0f}")

        ema12 = c.ewm(span=12, adjust=False).mean()
        ema26 = c.ewm(span=26, adjust=False).mean()
        mline = ema12 - ema26
        msig = mline.ewm(span=9, adjust=False).mean()
        mhist = mline - msig
        if mline.iloc[-1] > msig.iloc[-1]:
            score += 6
            signals.append("MACD Bull")
        else:
            score -= 6
        if mhist.iloc[-1] > 0 and mhist.iloc[-1] > mhist.iloc[-2]:
            score += 4
            signals.append("MACD Hist↑")
        elif mhist.iloc[-1] < 0 and mhist.iloc[-1] < mhist.iloc[-2]:
            score -= 4

        roc = c.pct_change(10) * 100
        if roc.iloc[-1] > 0:
            score += 4
            signals.append(f"ROC+{roc.iloc[-1]:.2f}")
        else:
            score -= 4

        hh = self.high.rolling(14).max()
        ll = self.low.rolling(14).min()
        wr = -100 * (hh - c) / (hh - ll).replace(0, np.nan)
        wrv = float(wr.iloc[-1]) if not pd.isna(wr.iloc[-1]) else -50.0
        if wrv > -20:
            signals.append(f"W%R={wrv:.0f}OB")
        elif wrv < -80:
            signals.append(f"W%R={wrv:.0f}OS")
        elif wrv > -50:
            score += 3
            signals.append(f"W%R={wrv:.0f}↑")
        else:
            score -= 3

        self.scores["Momentum"] = (max(0, min(100, score)), 20, " | ".join(signals))

    # ── 3. PRICE ACTION (15%) ───────────────────────────────────────────────
    def _price_action(self) -> None:
        score = 50.0
        signals: list[str] = []

        o = self.open.values
        h = self.high.values
        l = self.low.values
        c = self.close.values

        for i in range(-3, 0):
            body = abs(c[i] - o[i])
            rng = h[i] - l[i]
            if rng == 0:
                continue
            body_pct = body / rng

            if body_pct < 0.1:
                signals.append(f"Doji@{i}")

            if i == -1 and self.n >= 2:
                prev_body = abs(c[-2] - o[-2])
                if c[-1] > o[-1] and c[-2] < o[-2] and body > prev_body:
                    score += 10
                    signals.append("BullEngulf")
                elif c[-1] < o[-1] and c[-2] > o[-2] and body > prev_body:
                    score -= 10
                    signals.append("BearEngulf")

            if i == -1:
                upper_wick = h[i] - max(c[i], o[i])
                lower_wick = min(c[i], o[i]) - l[i]
                if lower_wick > 2 * body and upper_wick < body:
                    score += 8
                    signals.append("Hammer")
                if upper_wick > 2 * body and lower_wick < body:
                    score -= 8
                    signals.append("ShootingStar")
                if lower_wick > 0.6 * rng:
                    score += 6
                    signals.append("BullPinBar")
                if upper_wick > 0.6 * rng:
                    score -= 6
                    signals.append("BearPinBar")

        if self.n >= 2 and h[-1] < h[-2] and l[-1] > l[-2]:
            signals.append("InsideBar")

        if c[-1] > o[-1]:
            score += 4
        else:
            score -= 4

        rng = h[-1] - l[-1]
        if rng > 0:
            close_pos = (c[-1] - l[-1]) / rng
            if close_pos > 0.7:
                score += 5
                signals.append(f"CloseHigh{close_pos:.0%}")
            elif close_pos < 0.3:
                score -= 5
                signals.append(f"CloseLow{close_pos:.0%}")

        if self.n >= 4:
            if all(c[-i] > o[-i] for i in range(1, 4)):
                score += 7
                signals.append("3WhiteSoldiers")
            if all(c[-i] < o[-i] for i in range(1, 4)):
                score -= 7
                signals.append("3BlackCrows")

        self.scores["PriceAction"] = (max(0, min(100, score)), 15, " | ".join(signals) or "No pattern")

    # ── 4. SUPPORT / RESISTANCE (15%) ───────────────────────────────────────
    def _support_resistance(self) -> None:
        score = 50.0
        signals: list[str] = []
        curr = float(self.close.iloc[-1])

        ph = float(self.high.iloc[-2])
        pl = float(self.low.iloc[-2])
        pc = float(self.close.iloc[-2])
        pivot = (ph + pl + pc) / 3
        r1 = 2 * pivot - pl
        s1 = 2 * pivot - ph

        if curr > pivot:
            score += 5
            signals.append(f"P>Pivot({pivot:.2f})")
        else:
            score -= 5

        pct_to_r1 = (r1 - curr) / curr * 100
        pct_to_s1 = (curr - s1) / curr * 100
        signals.append(f"R1:{r1:.2f}(+{pct_to_r1:.1f}%) S1:{s1:.2f}(-{pct_to_s1:.1f}%)")

        if self.n >= 20:
            highs = self.high.values
            lows = self.low.values
            order = max(3, min(10, self.n // 15))
            hi_idx = argrelextrema(highs, np.greater, order=order)[0]
            lo_idx = argrelextrema(lows, np.less, order=order)[0]
            swing_highs = highs[hi_idx][-5:] if len(hi_idx) >= 1 else np.array([])
            swing_lows = lows[lo_idx][-5:] if len(lo_idx) >= 1 else np.array([])

            res = [r for r in swing_highs if r > curr * 1.001]
            if len(res):
                nearest_res = min(res)
                dist = (nearest_res - curr) / curr * 100
                signals.append(f"SwingRes:{nearest_res:.2f}(+{dist:.1f}%)")
                if dist < 0.5:
                    score -= 5
                elif dist > 3:
                    score += 3

            sup = [s for s in swing_lows if s < curr * 0.999]
            if len(sup):
                nearest_sup = max(sup)
                dist = (curr - nearest_sup) / curr * 100
                signals.append(f"SwingSup:{nearest_sup:.2f}(-{dist:.1f}%)")
                if dist < 0.5:
                    score += 5
                elif dist > 3:
                    score -= 3

        hi52 = float(self.high.iloc[-min(52, self.n):].max())
        lo52 = float(self.low.iloc[-min(52, self.n):].min())
        pos = (curr - lo52) / (hi52 - lo52) * 100 if hi52 != lo52 else 50.0
        signals.append(f"52Pos:{pos:.0f}%")
        if pos > 80:
            score += 6
        elif pos < 20:
            score -= 6

        if curr > 0:
            mag = round(curr, -int(math.floor(math.log10(curr)) - 1))
            dist_to_round = abs(curr - mag) / curr * 100
            if dist_to_round < 0.3:
                signals.append(f"NearRound({mag:.2f})")

        self.scores["SuppRes"] = (max(0, min(100, score)), 15, " | ".join(signals))

    # ── 5. VOLUME (10%) ───────────────────────────────────────────────────────
    def _volume(self) -> None:
        score = 50.0
        signals: list[str] = []
        vol = self.vol
        c = self.close

        vol_ma20 = vol.rolling(20).mean()
        curr_vol = float(vol.iloc[-1])
        avg_vol = float(vol_ma20.iloc[-1]) if not pd.isna(vol_ma20.iloc[-1]) else curr_vol
        vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 1.0

        if vol_ratio >= 2.0:
            score += 12
            signals.append(f"Vol {vol_ratio:.1f}x🔥")
        elif vol_ratio >= 1.5:
            score += 8
            signals.append(f"Vol {vol_ratio:.1f}x↑")
        elif vol_ratio >= 1.2:
            score += 4
            signals.append(f"Vol {vol_ratio:.1f}x")
        elif vol_ratio < 0.7:
            score -= 6
            signals.append(f"Vol {vol_ratio:.1f}x↓")

        if c.iloc[-1] > c.iloc[-2]:
            if vol_ratio >= 1.2:
                score += 5
                signals.append("BullVolConf")
        elif vol_ratio >= 1.2:
            score -= 5
            signals.append("BearVolConf")

        obv = (np.sign(c.diff()) * vol).fillna(0).cumsum()
        obv_slope = obv.iloc[-1] - obv.iloc[-min(10, self.n - 1)]
        if obv_slope > 0:
            score += 6
            signals.append("OBV↑")
        else:
            score -= 6
            signals.append("OBV↓")

        fi = c.diff() * vol
        fi_ma = fi.rolling(13).mean()
        if fi_ma.iloc[-1] > 0:
            score += 4
            signals.append("FI+")
        else:
            score -= 4

        if self.n >= 20:
            tp = (self.high + self.low + c) / 3
            vwap = (tp * vol).rolling(20).sum() / vol.rolling(20).sum().replace(0, np.nan)
            if not pd.isna(vwap.iloc[-1]):
                if c.iloc[-1] > vwap.iloc[-1]:
                    score += 5
                    signals.append(f"P>VWAP({vwap.iloc[-1]:.2f})")
                else:
                    score -= 5
                    signals.append(f"P<VWAP({vwap.iloc[-1]:.2f})")

        try:
            import pandas_ta as pta
            cmf_s = pta.cmf(self.high, self.low, c, vol, length=20)
            if cmf_s is not None and len(cmf_s.dropna()):
                cv = float(cmf_s.iloc[-1])
                if cv > 0.1:
                    score += 5
                    signals.append(f"CMF={cv:.2f}+")
                elif cv < -0.1:
                    score -= 5
                    signals.append(f"CMF={cv:.2f}-")
        except Exception:
            pass

        self.scores["Volume"] = (max(0, min(100, score)), 10, " | ".join(signals))

    # ── 6. VOLATILITY & BREAKOUT (10%) ────────────────────────────────────────
    def _volatility_breakout(self) -> None:
        score = 50.0
        signals: list[str] = []
        c = self.close
        h = self.high
        l = self.low
        curr = float(c.iloc[-1])

        bb_mid = c.rolling(20).mean()
        bb_std = c.rolling(20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        bb_pct = (curr - bb_lower.iloc[-1]) / (bb_upper.iloc[-1] - bb_lower.iloc[-1])
        signals.append(f"BB%B={bb_pct:.2f}")

        if bb_pct > 1.0:
            score -= 8
            signals.append("BB UpperBreak")
        elif bb_pct > 0.8:
            score += 6
            signals.append("BB Upper Zone")
        elif bb_pct < 0.0:
            score += 8
            signals.append("BB LowerBounce")
        elif bb_pct < 0.2:
            score -= 6
            signals.append("BB Lower Zone")
        else:
            score += 2

        tr = pd.concat([
            h - l,
            (h - c.shift()).abs(),
            (l - c.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        atr_val = float(atr.iloc[-1])
        atr_pct = atr_val / curr * 100 if curr else 0
        signals.append(f"ATR={atr_pct:.2f}%")

        dc_h = h.rolling(20).max().iloc[-1]
        dc_l = l.rolling(20).min().iloc[-1]
        if curr >= dc_h:
            score += 10
            signals.append("DC UpperBreakout")
        elif curr <= dc_l:
            score -= 10
            signals.append("DC LowerBreakdown")

        try:
            import pandas_ta as pta
            adx_df = pta.adx(h, l, c, length=14)
            if adx_df is not None and not adx_df.empty:
                adx_val = float(adx_df.iloc[-1, 0])
                dip = float(adx_df.iloc[-1, 1]) if adx_df.shape[1] > 1 else 0
                dim = float(adx_df.iloc[-1, 2]) if adx_df.shape[1] > 2 else 0
                signals.append(f"ADX={adx_val:.1f}")
                if adx_val > 25:
                    if dip > dim:
                        score += 8
                        signals.append(f"+DI>{dim:.0f}")
                    else:
                        score -= 8
                        signals.append(f"-DI>{dip:.0f}")
        except Exception:
            pass

        self.scores["Volatility"] = (max(0, min(100, score)), 10, " | ".join(signals))

    # ── 7. STRUCTURE (5%) ─────────────────────────────────────────────────────
    def _structure(self) -> None:
        score = 50.0
        signals: list[str] = []

        if self.n < 20:
            self.scores["Structure"] = (50, 5, "Insufficient data")
            return

        h = self.high.values
        l = self.low.values
        order = max(3, self.n // 20)
        hi_idx = argrelextrema(h, np.greater, order=order)[0]
        lo_idx = argrelextrema(l, np.less, order=order)[0]

        if len(hi_idx) >= 3:
            last3_hi = h[hi_idx[-3:]]
            if last3_hi[-1] > last3_hi[-2] > last3_hi[-3]:
                score += 10
                signals.append("HH↑↑↑")
            elif last3_hi[-1] < last3_hi[-2] < last3_hi[-3]:
                score -= 10
                signals.append("LH↓↓↓")

        if len(lo_idx) >= 3:
            last3_lo = l[lo_idx[-3:]]
            if last3_lo[-1] > last3_lo[-2] > last3_lo[-3]:
                score += 10
                signals.append("HL↑↑↑ (Bull Struct)")
            elif last3_lo[-1] < last3_lo[-2] < last3_lo[-3]:
                score -= 10
                signals.append("LL↓↓↓ (Bear Struct)")

        try:
            import pandas_ta as pta
            ichi = pta.ichimoku(self.high, self.low, self.close)
            if ichi is not None and len(ichi) >= 2:
                span_a = float(ichi[0].iloc[-1])
                span_b = float(ichi[1].iloc[-1])
                curr = float(self.close.iloc[-1])
                cloud_top = max(span_a, span_b)
                cloud_bot = min(span_a, span_b)
                if curr > cloud_top:
                    score += 8
                    signals.append("Above Cloud")
                elif curr < cloud_bot:
                    score -= 8
                    signals.append("Below Cloud")
                else:
                    signals.append("Inside Cloud")
                signals.append("BullCloud" if span_a > span_b else "BearCloud")
        except Exception:
            pass

        self.scores["Structure"] = (max(0, min(100, score)), 5, " | ".join(signals) or "Neutral")

    def composite_score(self) -> float:
        if not self.scores:
            return 50.0
        total_weight = sum(w for _, w, _ in self.scores.values())
        weighted_sum = sum(s * w for s, w, _ in self.scores.values())
        return weighted_sum / total_weight if total_weight else 50.0

    def confidence(self) -> float:
        if not self.scores:
            return 0.0
        scores = [s for s, _, _ in self.scores.values()]
        mean = float(np.mean(scores))
        std = float(np.std(scores))
        distance = abs(mean - 50)
        agreement = max(0, 100 - std * 1.5)
        return min(100.0, (distance / 50) * agreement)

    def risk_reward(self) -> dict:
        try:
            tr = pd.concat([
                self.high - self.low,
                (self.high - self.close.shift()).abs(),
                (self.low - self.close.shift()).abs(),
            ], axis=1).max(axis=1)
            atr = float(tr.rolling(14).mean().iloc[-1])
            curr = float(self.close.iloc[-1])
            sc = self.composite_score()
            if sc >= 55:
                sl = curr - 1.5 * atr
                tp1 = curr + 1.5 * atr
                tp2 = curr + 3.0 * atr
                return {
                    "direction": "LONG", "sl": sl, "tp1": tp1, "tp2": tp2,
                    "atr": atr, "rr1": 1.0, "rr2": 2.0,
                }
            if sc <= 45:
                sl = curr + 1.5 * atr
                tp1 = curr - 1.5 * atr
                tp2 = curr - 3.0 * atr
                return {
                    "direction": "SHORT", "sl": sl, "tp1": tp1, "tp2": tp2,
                    "atr": atr, "rr1": 1.0, "rr2": 2.0,
                }
            return {"direction": "NEUTRAL", "atr": atr}
        except Exception:
            return {"direction": "NEUTRAL"}

    def to_dict(self, tf: str) -> dict:
        composite = self.composite_score()
        conf = self.confidence()
        rr = self.risk_reward()
        curr = float(self.close.iloc[-1])
        chg = float((curr - self.close.iloc[-2]) / self.close.iloc[-2] * 100) if self.n >= 2 else 0.0
        components = {
            name: {"score": sc, "weight": wt, "signals": sig}
            for name, (sc, wt, sig) in self.scores.items()
        }
        return {
            "timeframe": tf,
            "label": TIMEFRAMES.get(tf, {}).get("label", tf),
            "composite": round(composite, 1),
            "confidence": round(conf, 1),
            "bias": bias_label(composite),
            "bias_arrow": trend_arrow_label(composite),
            "direction": rr.get("direction", "NEUTRAL"),
            "price": curr,
            "change_pct": round(chg, 2),
            "components": components,
            "trade_levels": _format_trade_levels(rr, curr),
            "trade_setup": build_trade_setup(
                tf, composite, conf, _format_trade_levels(rr, curr),
            ),
        }


def compute_setup_confidence(composite: float, indicator_confidence: float) -> float:
    """Blend indicator agreement with directional edge from neutral (50)."""
    edge = abs(composite - 50) / 50.0
    return round(min(100.0, indicator_confidence * 0.55 + edge * 100 * 0.45), 1)


def classify_setup_status(composite: float, indicator_confidence: float, direction: str) -> tuple[str, str]:
    if direction == "NEUTRAL" or (45 < composite < 55):
        return "NO SETUP", "Neutral composite — no directional edge on this TF"
    if indicator_confidence < 40:
        return "LOW CONFIDENCE", f"Indicators split ({indicator_confidence:.0f}%) — stay out or size down"
    if (composite >= 65 or composite <= 35) and indicator_confidence >= 55:
        return "READY", "High-conviction setup — composite and indicators aligned"
    if composite >= 55 or composite <= 45:
        return "WATCH", "Bias forming — confirm with price action before entry"
    return "NO SETUP", "No actionable edge on this timeframe"


def build_trade_setup(
    tf: str,
    composite: float,
    indicator_confidence: float,
    trade_levels: dict,
) -> dict:
    """Per-TF trading setup with SL/TP %, hold duration, and setup confidence."""
    meta = TIMEFRAMES.get(tf, {})
    direction = trade_levels.get("direction", "NEUTRAL")
    status, hint = classify_setup_status(composite, indicator_confidence, direction)
    setup_confidence = compute_setup_confidence(composite, indicator_confidence)

    setup: dict[str, Any] = {
        "timeframe": tf,
        "label": meta.get("label", tf),
        "style": meta.get("style", "—"),
        "hold_duration": meta.get("hold", "—"),
        "status": status,
        "hint": hint,
        "direction": direction if status != "NO SETUP" else "—",
        "composite": round(composite, 1),
        "indicator_confidence": round(indicator_confidence, 1),
        "setup_confidence": setup_confidence,
        "priority": SETUP_PRIORITY.get(status, 0),
        "actionable": status in ("READY", "WATCH") and direction in ("LONG", "SHORT"),
    }

    if direction in ("LONG", "SHORT") and trade_levels.get("entry"):
        setup.update({
            "entry": trade_levels.get("entry"),
            "sl": trade_levels.get("sl"),
            "tp1": trade_levels.get("tp1"),
            "tp2": trade_levels.get("tp2"),
            "sl_pct": trade_levels.get("sl_pct"),
            "tp1_pct": trade_levels.get("tp1_pct"),
            "tp2_pct": trade_levels.get("tp2_pct"),
            "rr1": trade_levels.get("rr1", 1.0),
            "rr2": trade_levels.get("rr2", 2.0),
            "atr": trade_levels.get("atr"),
        })
    return setup


def build_trade_setups(tf_results: dict[str, dict]) -> list[dict]:
    """All per-TF setups sorted by priority then setup confidence."""
    setups = []
    for tf in TF_ORDER:
        if tf not in tf_results:
            continue
        r = tf_results[tf]
        setup = r.get("trade_setup") or build_trade_setup(
            tf,
            r.get("composite", 50),
            r.get("confidence", 0),
            r.get("trade_levels") or {},
        )
        setups.append(setup)
    setups.sort(
        key=lambda s: (s.get("priority", 0), s.get("setup_confidence", 0)),
        reverse=True,
    )
    return setups


def group_setups_by_style(setups: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {"Scalp": [], "Intraday": [], "Swing": [], "Position": []}
    for s in setups:
        style = s.get("style", "")
        if style in groups:
            groups[style].append(s)
    return {k: v for k, v in groups.items() if v}


def pick_best_setup(setups: list[dict]) -> Optional[dict]:
    actionable = [s for s in setups if s.get("actionable")]
    if not actionable:
        return setups[0] if setups else None
    return max(
        actionable,
        key=lambda s: (s.get("priority", 0), s.get("setup_confidence", 0)),
    )


def pick_style_setups(setups: list[dict]) -> dict[str, Optional[dict]]:
    """Best actionable setup per trading style (scalp / intraday / swing / position)."""
    by_style: dict[str, Optional[dict]] = {}
    for style in ("Scalp", "Intraday", "Swing", "Position"):
        candidates = [
            s for s in setups
            if s.get("style") == style and s.get("actionable")
        ]
        by_style[style] = max(
            candidates,
            key=lambda s: (s.get("priority", 0), s.get("setup_confidence", 0)),
            default=None,
        )
    return by_style


def _format_trade_levels(rr: dict, curr: float) -> dict:
    if rr.get("direction") == "NEUTRAL" or not rr.get("atr"):
        return {"direction": "NEUTRAL", "atr": rr.get("atr")}
    atr = float(rr["atr"])
    direction = rr["direction"]
    sl = float(rr["sl"])
    tp1 = float(rr["tp1"])
    tp2 = float(rr["tp2"])
    sl_pct = abs(sl - curr) / curr * 100
    tp1_pct = abs(tp1 - curr) / curr * 100
    tp2_pct = abs(tp2 - curr) / curr * 100
    return {
        "direction": direction,
        "entry": curr,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "atr": atr,
        "sl_pct": round(sl_pct, 2),
        "tp1_pct": round(tp1_pct, 2),
        "tp2_pct": round(tp2_pct, 2),
        "rr1": 1.0,
        "rr2": 2.0,
    }


def analyze_timeframe(
    df: pd.DataFrame,
    tf: str,
) -> Optional[dict]:
    df = normalize_ohlcv(df)
    if df.empty or len(df) < MIN_BARS:
        return None
    return MTFAnalyzer(df).to_dict(tf)


def build_confluence(tf_results: dict[str, dict], trade_setups: list[dict] | None = None) -> dict:
    """Cross-timeframe confluence summary."""
    if not tf_results:
        return {"verdict": "NO DATA", "suggested_play": []}

    scores = [r["composite"] for r in tf_results.values()]
    confs = [r["confidence"] for r in tf_results.values()]
    n = len(scores)
    avg_score = sum(scores) / n
    avg_conf = sum(confs) / n

    bull = sum(1 for s in scores if s >= 60)
    bear = sum(1 for s in scores if s <= 40)
    neutral = n - bull - bear

    if bull >= n * 0.65:
        verdict = "STRONG BULLISH CONFLUENCE"
        verdict_type = "strong_bull"
    elif bear >= n * 0.65:
        verdict = "STRONG BEARISH CONFLUENCE"
        verdict_type = "strong_bear"
    elif bull > bear:
        verdict = "MILD BULLISH BIAS"
        verdict_type = "mild_bull"
    elif bear > bull:
        verdict = "MILD BEARISH BIAS"
        verdict_type = "mild_bear"
    else:
        verdict = "MIXED / NEUTRAL"
        verdict_type = "mixed"

    suggested: list[str] = []
    if avg_score >= 62:
        suggested = [
            "SCALP: Immediate long entries on lower TFs",
            "SWING: Initiate long on daily/4h pullback to key support",
        ]
    elif avg_score <= 38:
        suggested = [
            "SCALP: Short on bounce rejections at resistance",
            "SWING: Enter short on failed breakouts / distribution zones",
        ]
    else:
        suggested = [
            "Wait for breakout confirmation or strong S/R bounce",
            "Use tighter sizing; trend not confirmed across TFs",
        ]

    setups = trade_setups if trade_setups is not None else build_trade_setups(tf_results)
    ready_setups = [s for s in setups if s.get("status") == "READY"]
    watch_setups = [s for s in setups if s.get("status") == "WATCH"]

    return {
        "avg_score": round(avg_score, 1),
        "avg_confidence": round(avg_conf, 1),
        "bull_count": bull,
        "bear_count": bear,
        "neutral_count": neutral,
        "total_tfs": n,
        "verdict": verdict,
        "verdict_type": verdict_type,
        "bias": bias_label(avg_score),
        "bias_arrow": trend_arrow_label(avg_score),
        "suggested_play": suggested,
        "actionable": verdict_type in ("strong_bull", "strong_bear") and avg_conf >= 40,
        "ready_setup_count": len(ready_setups),
        "watch_setup_count": len(watch_setups),
    }


def analyze_ticker(
    symbol: str,
    timeframes: list[str],
    market: str,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 300,
) -> dict:
    """Analyze one ticker across selected timeframes."""
    tf_results: dict[str, dict] = {}
    errors: dict[str, str] = {}

    for tf in timeframes:
        if tf not in TIMEFRAMES:
            continue
        df = fetch_mtf_data(symbol, tf, market, groww_token, exchange, limit)
        if df.empty or len(df) < MIN_BARS:
            errors[tf] = f"Insufficient data ({len(df)} bars)"
            continue
        result = analyze_timeframe(df, tf)
        if result:
            tf_results[tf] = result
        else:
            errors[tf] = "Analysis failed"

    trade_setups = build_trade_setups(tf_results)
    confluence = build_confluence(tf_results, trade_setups=trade_setups)
    best_setup = pick_best_setup(trade_setups)
    style_setups = pick_style_setups(trade_setups)
    primary_tf = max(tf_results, key=lambda t: tf_results[t]["confidence"]) if tf_results else None

    return {
        "symbol": symbol,
        "market": market,
        "timeframes": tf_results,
        "errors": errors,
        "confluence": confluence,
        "trade_setups": trade_setups,
        "grouped_setups": group_setups_by_style(trade_setups),
        "best_setup": best_setup,
        "style_setups": style_setups,
        "primary_timeframe": primary_tf,
        "bars_loaded": limit,
    }


def run_mtf_scan(
    tickers: list[str],
    timeframes: list[str],
    market: str,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 300,
) -> dict[str, dict]:
    """Scan multiple tickers; returns {ticker: analysis}."""
    results: dict[str, dict] = {}
    for ticker in tickers:
        results[ticker] = analyze_ticker(
            ticker, timeframes, market, groww_token, exchange, limit,
        )
    return results
