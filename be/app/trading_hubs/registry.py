"""Registry of Swing / Intraday / Scalping / Smart Money hub sections."""

from __future__ import annotations

import dataclasses
import inspect
from typing import Any

from app.trading_hubs import (
    intra_hedging_engine,
    intra_hwp_engine,
    intraday_7_wasted_engine,
    intraday_alpha_945_engine,
    intraday_bramhastra_engine,
    intraday_london_breakout_engine,
    intraday_fib945_engine,
    intraday_mtf_breakout_retest_engine,
    intraday_vwap_fade_engine,
    scalp_2min_engine,
    scalp_arc_engine,
    scalp_crt_fvg_engine,
    scalp_ichimoku_crash_engine,
    scalp_multi_indicator_engine,
    scalp_ny_open_bias_engine,
    scalp_rectangle_engine,
    scalp_heikin_ashi_engine,
    scalp_livefree_fx_engine,
    scalp_smc_engine,
    scalp_sr_mss_engine,
    scalp_weekly_engine,
    weekly_candle_continuation_engine,
    sc_fvg_engine,
    smb_snp_engine,
    smc_cisd_engine,
    smc_five_filter_engine,
    smc_htf_zone_sweep_engine,
    smc_golden_bullet_engine,
    smc_lewiskelly_engine,
    smc_liquidity_engine,
    smc_liquidity_silver_bullet_engine,
    smc_mtf_day_plan_engine,
    smc_sc_best_engine,
    smc_ttg_sniper_engine,
    footprint_engine,
    reversal_strategy_engine,
    smc_weekly_sweep_cisd_engine,
    support_resistance_engine,
    swing_5_strategies_engine,
    swing_bb_vwap_reversal_engine,
    swing_trading_st_engine,
    swing_trend_breakout_engine,
    swing_trend_velocity_engine,
    swing_trading_st_ha_ema_engine,
    swing_trading_st_kiss_engine,
    swing_trading_st_mtf_mss_engine,
    swing_trading_st_simple_steal_engine,
    swing_trading_st_supertrend_engine,
)
from app.trading_hubs.swing_trading_st_engine import STRATEGY_CONTINUATION, STRATEGY_MEAN_REVERSION

HubSection = dict[str, Any]


def _section(
    *,
    id: str,
    hub: str,
    label: str,
    description: str,
    module: Any,
    config_cls: type,
    config_options: dict[str, Any] | None = None,
    fixed_universe: list[str] | None = None,
    fixed_universe_label: str | None = None,
    multi_strategy: bool = False,
    strategy_keys: list[str] | None = None,
    strategy_labels: dict[str, str] | None = None,
    timeframe_options: list[str] | None = None,
    guide: str | None = None,
) -> HubSection:
    return {
        "id": id,
        "hub": hub,
        "label": label,
        "description": description,
        "module": module,
        "config_cls": config_cls,
        "config_options": config_options or {},
        # Optional extended documentation shown in a collapsible panel on the
        # Trading Hub page itself (separate from the short one-line `description`).
        "guide": guide,
        # When set, the FE hides the asset-class / ticker picker and the scan
        # ignores client-selected tickers (engine uses this fixed list instead).
        "fixed_universe": fixed_universe,
        "fixed_universe_label": fixed_universe_label,
        # When set, this section is a multi-strategy/multi-timeframe scanner
        # (e.g. Swing 5 Strategies) that doesn't fit the generic single-config
        # scan flow — the FE routes it to a dedicated panel + endpoint instead
        # of the standard run_section_scan path.
        "multi_strategy": multi_strategy,
        "strategy_keys": strategy_keys or [],
        "strategy_labels": strategy_labels or {},
        "timeframe_options": timeframe_options or [],
    }


HUB_SECTIONS: list[HubSection] = [
    _section(
        id="swing_trading_st",
        hub="swing",
        label="Capitulation & Continuation Breakout",
        description="Daily swing — mean reversion capitulation or continuation breakout.",
        module=swing_trading_st_engine,
        config_cls=swing_trading_st_engine.STConfig,
        config_options={
            "strategy": {
                "type": "select",
                "label": "Strategy",
                "choices": [
                    {"value": STRATEGY_MEAN_REVERSION, "label": "Mean Reversion (Capitulation)"},
                    {"value": STRATEGY_CONTINUATION, "label": "Continuation Breakout"},
                ],
                "default": STRATEGY_CONTINUATION,
            },
        },
    ),
    _section(
        id="support_resistance",
        hub="swing",
        label="Support and Resistance",
        description=(
            "Break-and-retest zones on a higher timeframe (not exact lines) — a broken resistance zone "
            "becomes new support and vice versa. Waits for price to tap back into the zone, then a lower-"
            "timeframe market-structure break confirms entry. Works across Groww India, US, Crypto, and Commodities."
        ),
        module=support_resistance_engine,
        config_cls=support_resistance_engine.SupportResistanceConfig,
        config_options={
            "htf": {
                "type": "select",
                "label": "Zone timeframe (HTF)",
                "choices": [{"value": v, "label": v} for v in support_resistance_engine.HTF_OPTIONS],
                "default": "4h",
            },
            "ltf": {
                "type": "select",
                "label": "Entry confirmation timeframe (LTF)",
                "choices": [{"value": v, "label": v} for v in support_resistance_engine.LTF_OPTIONS],
                "default": "1m",
            },
        },
        guide="""### Support and Resistance — break, retest, confirm
[The Strategy That Made Me My First $1,000,000 Trading](https://www.youtube.com/watch?v=d5T-k_-ejd0&t=29s)

**The core idea:** resistance is a "roof" where sellers have stepped in before; support is a "floor" where buyers
have stepped in before. A strongly-broken roof often becomes the new floor on the next visit (and the mirror image
for a broken floor becoming a new roof) — this is the break-and-retest rule the whole strategy is built on.

| Step | Rule |
|------|------|
| **1. Draw zones, not lines** | On the higher timeframe, a resistance zone runs from the highest wick down to the highest candle body in a rejection cluster; a support zone runs from the lowest wick up to the lowest body. Price reacts to a zone, not an exact price. |
| **2. Break and retest** | A zone that gets strongly broken flips role — old resistance becomes new support, old support becomes new resistance — for the next time price returns to it. |
| **3. Alert, don't stare** | Nothing happens while price sits between zones — this hub only lights up once price actually taps back into one. |
| **4. Lower-timeframe confirmation** | Once tapped, market structure on the LTF is read: approaching support, price should be making lower highs/lows. The trigger is a clean break above the most recent lower high (mirror image at resistance: break below the most recent higher low). Never enter on the tap alone. |
| **5. Entry** | At the structure break. **Stop:** beyond the zone (or the pre-entry extreme). **Target:** the next recent structural high/low — usually the opposing zone. |

**When to use:** a deliberately boring, low-screen-time strategy — you're meant to set the zone, walk away, and only
engage once price taps it and structure confirms. Works the same way across every asset class this hub supports.
""",
    ),
    _section(
        id="reversal_strategy",
        hub="swing",
        label="Reversal Strategy",
        description=(
            "A 6-step counter-trend/range reversal checklist: Market Condition → Market Phase (run exhaustion) → "
            "Support/Resistance (horizontal zones, round numbers, trendlines) → MACD Divergence → Deceleration → "
            "Candlestick Trigger (Low/High Test, Tweezer, Doji, Inside Bar). Deliberately trades less — a choppy "
            "market condition rejects the setup outright. Works across Groww India, US, Crypto, and Commodities."
        ),
        module=reversal_strategy_engine,
        config_cls=reversal_strategy_engine.ReversalConfig,
        config_options={
            "timeframe": {
                "type": "select",
                "label": "Timeframe",
                "choices": [{"value": v, "label": v} for v in reversal_strategy_engine.TIMEFRAME_OPTIONS],
                "default": "1d",
            },
            "tp_mode": {
                "type": "select",
                "label": "Take-profit mode",
                "choices": [
                    {"value": "auto", "label": "Auto (50 EMA in a trend, next level while ranging)"},
                    {"value": "ema_target", "label": "50 EMA target"},
                    {"value": "range_target", "label": "Next major level target"},
                ],
                "default": "auto",
            },
        },
        guide="""### Reversal Strategy — the 6-step counter-trend/range checklist
[The ONLY Reversal Trading Strategy You'll Ever Need (Step-by-Step)](https://www.youtube.com/watch?v=Lz9XmfDLXxI&t=155s)

**The core idea:** unlike trend-following, which leans on moving averages, reversal trading leans on momentum
divergence and exhaustion at a level — you're betting the current move is running out of steam, not that it
will continue.

| Step | What it checks |
|---|---|
| **1. Market Condition** | Bullish (higher highs/higher lows), bearish (lower lows/lower highs), ranging (oscillating between a clear top and bottom), or choppy — choppy markets are skipped outright. |
| **2. Market Phase** | Trends move in runs then pullbacks; a reversal wants the exhaustion of a run (an extended push, measured against ATR), not a fresh pullback already in progress. |
| **3. Support/Resistance** | Horizontal zones from swing rejection clusters (with a note when price sits near a round-number "handle"), plus angular trendlines from the last two swing points. |
| **4. MACD Divergence** | Price makes a new high/low that MACD does not confirm — momentum fading right at the level. |
| **5. Deceleration** | Candle bodies get progressively smaller on approach to the level — the prevailing move visibly losing steam. |
| **6. Candlestick Trigger** | The actual entry trigger: Low/High Test candle, Tweezer Top/Bottom, Doji, or Inside Bar on the signal candle. |

**Execution:** entry a touch beyond the signal candle's extreme in the reversal direction; stop just beyond its
opposite extreme (this app uses a small ATR-based buffer in place of the video's "3-5 pips", since it trades
equities/crypto/commodities, not forex). Minimum 1:1 reward:risk is enforced.

**Take profit — pick a mode:** *Auto* targets the 50 EMA when the market condition is trending (Option 1 from the
video — price reverting to the mean it stretched away from), or the next major horizontal level when the market
condition is ranging (Option 3). You can also pin it to one mode directly.

**When to use:** a patience-first, sit-on-your-hands strategy — pending setups can go unconfirmed for days, and a
choppy market condition means no trade at all. It complements (not replaces) the trend-following hubs elsewhere
in Swing Trading.
""",
    ),
    _section(
        id="swing_trading_st_mtf_mss",
        hub="swing",
        label="Weekly Fakeout + 15m MSS",
        description="Weekly levels, daily fakeout screen, 15m market structure shift.",
        module=swing_trading_st_mtf_mss_engine,
        config_cls=swing_trading_st_mtf_mss_engine.MTFMSSConfig,
    ),
    _section(
        id="swing_trading_st_supertrend",
        hub="swing",
        label="SuperTrend + SMA 10 Swing & Pyramiding",
        description="SuperTrend with SMA trail — swing or pyramid mode.",
        module=swing_trading_st_supertrend_engine,
        config_cls=swing_trading_st_supertrend_engine.STSuperTrendConfig,
        config_options={
            "mode": {
                "type": "select",
                "label": "Mode",
                "choices": [
                    {"value": swing_trading_st_supertrend_engine.MODE_SWING, "label": "Swing"},
                    {"value": swing_trading_st_supertrend_engine.MODE_PYRAMID, "label": "Pyramid"},
                ],
                "default": swing_trading_st_supertrend_engine.MODE_SWING,
            },
        },
    ),
    _section(
        id="swing_trading_st_kiss",
        hub="swing",
        label="KISS Swing Systematic",
        description="Weekly HA filter with 1h/4h KISS systematic entries.",
        module=swing_trading_st_kiss_engine,
        config_cls=swing_trading_st_kiss_engine.KISSConfig,
    ),
    _section(
        id="swing_trading_st_ha_ema",
        hub="swing",
        label="Daily HA Bias + 34 EMA Intraday",
        description="Daily Heikin-Ashi bias with 5m/15m 34 EMA execution.",
        module=swing_trading_st_ha_ema_engine,
        config_cls=swing_trading_st_ha_ema_engine.HAEmaConfig,
    ),
    _section(
        id="intra_hedging",
        hub="intraday",
        label="Intra-Hedging (Sector Long/Short)",
        description=(
            "Long the strongest, short the weakest, sized beta-neutral so the pair is market-direction-neutral — "
            "trades the spread between momentum, not overall Nifty direction. Surfaces up to several non-overlapping "
            "pairs at once, each with its own comparable confidence score. Scan either the 28 tracked Nifty sector "
            "indices, or one chosen index's individual constituent stocks; India only. "
            "Works intraday (5m-1h, same-day) or as a swing rotation (4h/1d/1wk, held over days-weeks)."
        ),
        module=intra_hedging_engine,
        config_cls=intra_hedging_engine.IntraHedgingConfig,
        config_options={
            "momentum_timeframe": {
                "type": "select",
                "label": "Momentum timeframe (5m-1h = intraday session, 4h/1d/1wk = swing lookback)",
                "choices": [{"value": v, "label": v} for v in intra_hedging_engine.MOMENTUM_TIMEFRAME_OPTIONS],
                "default": "15m",
            },
            "universe_mode": {
                "type": "select",
                "label": "Scan sector indices, or one index's individual stocks?",
                "choices": [
                    {"value": "sector", "label": "Sector indices (28 tracked Nifty sectors)"},
                    {"value": "stock", "label": "Individual stocks (pick an index below)"},
                ],
                "default": "sector",
            },
            "stock_index": {
                "type": "select",
                "label": "Index to pull constituent stocks from (only used when scanning by Stock, above)",
                "choices": [{"value": v, "label": v} for v in intra_hedging_engine.STOCK_MODE_INDEX_OPTIONS],
                "default": "NIFTY BANK",
            },
            "max_pairs": {
                "type": "number",
                "label": "Max hedge pairs to surface (each non-overlapping, ranked by confidence)",
                "min": 1, "max": 5, "step": 1,
                "default": 3,
            },
        },
        fixed_universe=list(intra_hedging_engine.SECTOR_UNIVERSE),
        fixed_universe_label=f"All {len(intra_hedging_engine.SECTOR_UNIVERSE)} major Nifty sector indices (Banking, IT, Energy, Auto, FMCG, Pharma, Metal, Realty, Infrastructure, Media, and more)",
        guide="""### Intra-Hedging — sector relative-strength long/short (beta-neutral)

**The core idea:** this is a classic institutional Long/Short Equity approach applied to Nifty sectors — buy the
strongest sector, short the weakest, and size both legs so their Beta-weighted exposure matches. By doing this you
strip out the broad Nifty's own direction and only trade the DIFFERENCE in momentum between the two sectors. If the
whole market suddenly moves against you, the short leg (or long leg) offsets the loss on the other side.

| Step | What it does |
|---|---|
| **1. Universe** | Tracks every major Nifty sectoral index this app can resolve OHLC for (28 sectors) — the heavyweights (Banking, IT, Financial Services, Energy) and smaller/thematic ones (Defence, Tourism, Housing, ...) alike. A handful of newer sector indices have no listed Yahoo ticker and fall back to an equal-weight constituent-stock proxy. |
| **2. Momentum ranking** | Ranks every tracked sector strongest to weakest by momentum on the selected timeframe. Intraday timeframes (5m/15m/30m/1h) measure today's session close vs. session open; swing timeframes (4h/1d/1wk) measure a close-to-close return over a timeframe-appropriate lookback (≈4 trading days on 4h, ≈1 week on 1d, ≈1 month on 1wk). |
| **3. Divergence gate** | If the spread between the strongest and weakest sector is too small, there's no clear rotation happening right now — the strategy sits out rather than forcing a weak pair (do NOT force a trade on a flat, non-divergent read). |
| **4. Long/Short pair** | The strongest sector is the LONG leg; the weakest is the SHORT leg. |
| **5. Beta-neutral sizing** | Each leg's Beta vs. Nifty 50 (90-day daily returns) sets its capital split — the higher-Beta leg gets LESS capital, so both sides carry the same volatility-weighted exposure and net portfolio Beta is ~0. |
| **6. Execution** | ETF route (every verified, liquid NSE-listed ETF for that sector is listed — not just one; short-selling ETFs intraday in the cash market is often broker-restricted, so the short leg typically needs sector futures) or the Stock route (buy/short the sector's top 5 weighted constituent stocks directly — faster fills, no minor-ETF liquidity issues). Both routes are shown for each leg, with sectors that have no sufficiently liquid ETF clearly marked. |

**Intraday vs. swing — pick the timeframe to match how you want to trade this:**
- **Intraday (5m/15m/30m/1h):** run the live scan after the first 30 minutes of trading (never right at the open —
  that window is noisy, not yet showing real institutional flow). This is a same-day, flat-by-close read — it does
  not carry overnight risk. Short legs typically need futures since India cash-market intraday shorting is often
  broker-restricted.
- **Swing (4h/1d/1wk):** run the scan any time; momentum is a multi-day/week lookback return rather than a
  same-session read. Positions are meant to be held for days to weeks (holding-period guidance scales with the
  timeframe) and re-checked periodically rather than flattened same-day — re-run the scan every few days to a
  week and rotate into the new leaders if the ranking has clearly shifted. Short legs here can't be carried
  overnight in the cash market either — use sector futures for a multi-day short.

Either way: check the `pair_recommendation` fields / the strongest and weakest sector's own reasons for the exact
Long/Short pair, capital split, and execution instructions (every verified ETF for that sector, plus its top 5
weighted stocks). If the scan reports the spread is below the divergence threshold, there's no clean pairs setup
right now — wait rather than forcing a weak trade.

**Data & math:** momentum is measured on this app's own Groww/yfinance/constituent-proxy feed (session-based for
intraday, lookback-return-based for swing); Beta is `covariance(sector, Nifty 50) / variance(Nifty 50)` on trailing
daily returns (same 90-day window regardless of momentum timeframe); capital split is
`long_weight = short_beta / (long_beta + short_beta)`, `short_weight = long_beta / (long_beta + short_beta)` —
inverting the higher-Beta side's allocation so both legs hit the book with equal volatility. Not a backtested edge —
a structured framework for a well-known relative-strength pairs concept. Research / education only, not financial
advice.
""",
    ),
    _section(
        id="intraday_alpha_945",
        hub="intraday",
        label="9:45 AM Alpha Scanner",
        description="Opening 30m range breakout after 9:45 IST with relative strength filters.",
        module=intraday_alpha_945_engine,
        config_cls=intraday_alpha_945_engine.Alpha945Config,
    ),
    _section(
        id="intraday_fib_945",
        hub="intraday",
        label="9:45 Fib 50% Bias + 10 EMA",
        description="Post-9:45 Fibonacci 50% bias with 10 EMA alignment.",
        module=intraday_fib945_engine,
        config_cls=intraday_fib945_engine.Fib945Config,
    ),
    _section(
        id="intraday_vwap_fade",
        hub="intraday",
        label="VWAP Fade Value Area",
        description="Fade extensions from VWAP value area with time stop.",
        module=intraday_vwap_fade_engine,
        config_cls=intraday_vwap_fade_engine.VwapFadeConfig,
    ),
    _section(
        id="scalp_rectangle",
        hub="scalping",
        label="1m Rectangle Sniper Entry",
        description="1-minute rectangle consolidation breakout sniper entries.",
        module=scalp_rectangle_engine,
        config_cls=scalp_rectangle_engine.RectangleConfig,
    ),
    _section(
        id="smc_cisd",
        hub="smart_money",
        label="CISD Entry Rule",
        description="Liquidity sweep → CISD break → institutional entry.",
        module=smc_cisd_engine,
        config_cls=smc_cisd_engine.CISDConfig,
    ),
    _section(
        id="smc_five_filter",
        hub="smart_money",
        label="5 SMC Filter",
        description=(
            "The 5 checks that separate an A+ Smart Money trade from a bad one: "
            "Permission (unmitigated HTF zone) → Footprint (liquidity sweep origin) → "
            "Inefficiency (FVG) → Location (discount/premium) → Exit Test (HTF liquidity target with room). "
            "All 5 must pass, then one of 3 entry models executes."
        ),
        module=smc_five_filter_engine,
        config_cls=smc_five_filter_engine.FiveFilterConfig,
        config_options={
            "htf": {
                "type": "select",
                "label": "HTF bias timeframe (Permission / Footprint / Inefficiency / Location / Exit Test)",
                "choices": [{"value": v, "label": v} for v in smc_five_filter_engine.HTF_OPTIONS],
                "default": "4h",
            },
            "ltf": {
                "type": "select",
                "label": "Execution timeframe (LTF)",
                "choices": [{"value": v, "label": v} for v in smc_five_filter_engine.LTF_OPTIONS],
                "default": "15m",
            },
            "entry_model": {
                "type": "select",
                "label": "Entry model",
                "choices": [{"value": v, "label": v} for v in smc_five_filter_engine.ENTRY_MODEL_OPTIONS],
                "default": "Conservative",
            },
        },
        guide="""### 5 SMC Filter — the 5 checks that separate A+ trades from bad ones
[The 5 Smart Money Filters That Separate A+ Trades From Bad Trades](https://www.youtube.com/watch?v=uzeLz80FVVY&t=54s)

| Filter | What it checks |
|---|---|
| **1. Permission** | Price must come from an UNMITIGATED higher-timeframe supply/demand zone — that zone alone tells you which side you're allowed to trade (demand = buys only, supply = sells only). |
| **2. Footprint** | The zone's origin must be a liquidity sweep of a prior swing, followed by a sharp displacement — the real fingerprint of smart money, not random consolidation. |
| **3. Inefficiency** | An unfilled Fair Value Gap must sit in the same leg — the imbalance that makes the zone "magnetic". |
| **4. Location** | The zone must sit in the discount half of the range for buys, or the premium half for sells. Mid-range setups are rejected outright. |
| **5. Exit Test** | There must be untouched higher-timeframe liquidity ahead of price, far enough away to clear a minimum reward:risk. No target room = no trade. |

All 5 must pass together for a setup to count as A+ — the live scan shows each filter's pass/fail individually.

**3 entry models, once a setup passes all 5 filters:**
- **Aggressive** — enter the moment price is inside the zone (limit at the zone midpoint), stop just beyond the zone. Rarely misses a trade, but no reversal confirmation — higher stop-out risk.
- **Conservative** — wait for price to tap the zone AND a lower-timeframe Change of Character (ChoCh) to confirm the reversal. Tighter stop, better R:R, but can miss fast-moving trades.
- **Ultra-Conservative** — stacks a second confirmation on top of Conservative: after the ChoCh, also wait for a same-direction lower-timeframe continuation Fair Value Gap before entering. The closest practical proxy to the video's full multi-timeframe cascade (4h → 1h → 15m → 1m) using the two configurable timeframes here (HTF bias + LTF execution) — exceptional R:R and precision, but the most frequently missed entries of the three.

**When to use:** when you want the strategy to say no far more often than yes — this hub deliberately trades less, waiting only for setups where every one of the 5 filters lines up.
""",
    ),
    _section(
        id="footprint",
        hub="smart_money",
        label="Footprint",
        description=(
            "Order-flow confirmation at a key HTF support/resistance level, via an OHLCV-derived "
            "delta proxy (this app has no real bid/ask tick data): Delta (who won the recent bars) → "
            "Imbalances (3+ stacked one-sided bars) → Absorption (high volume, small body — a wall quietly "
            "absorbing the pressure). All three must confirm, in that order, before entry."
        ),
        module=footprint_engine,
        config_cls=footprint_engine.FootprintConfig,
        config_options={
            "htf": {
                "type": "select",
                "label": "Key level timeframe (HTF)",
                "choices": [{"value": v, "label": v} for v in footprint_engine.HTF_OPTIONS],
                "default": "4h",
            },
            "ltf": {
                "type": "select",
                "label": "Order-flow / execution timeframe (LTF)",
                "choices": [{"value": v, "label": v} for v in footprint_engine.LTF_OPTIONS],
                "default": "5m",
            },
        },
        guide="""### Footprint — order-flow confirmation at key levels
[I Studied Order Flow Trading for 5 Years — Footprint Charts Beat Everything](https://www.youtube.com/watch?v=kcglxDJ_ZF0)

**Important:** this app's data sources (Groww/yfinance/CoinDCX) provide OHLCV candles, not literal bid/ask
tick-level footprint data. Buy/sell volume per bar is estimated from where the candle's close sits within its
own high-low range — the same delta-proxy technique already used by the Scanner's Order Flow Imbalance strategy.
Treat this as an honest, OHLCV-derived approximation of order flow, not real Level 2 depth.

| Step | What it checks |
|------|------|
| **1. Delta** | Buyers minus (estimated) sellers over the last few bars. Positive = aggressive buying, negative = aggressive selling — the first filter on which side is winning. |
| **2. Imbalances** | A bar where one side overwhelms the other. Three or more stacked in the same direction is treated as an institutional "fingerprint" carving out a tighter zone. |
| **3. Absorption** | High volume and a big delta, but the price barely moves — an invisible wall quietly absorbing the aggressive side. One of the strongest reversal tells when it happens at a key level. |

**Strict order of operations:** this hub only fires an entry once price has tapped a key HTF support/resistance
zone AND all three steps confirm, in order — Delta favors the reversal, a stacked imbalance run backs it, and an
absorption bar confirms it. Partial confirmation shows as WATCH with exactly which step is still missing.

**When to use:** as a confirmation layer at levels you already care about, not a standalone signal generator —
per the video's own framing, footprint reads what's happening at a level, it doesn't find the level for you.
""",
    ),
    _section(
        id="smc_weekly_sweep_cisd",
        hub="smart_money",
        label="Weekly Liquidity Sweep & CISD",
        description="Previous week high/low sweep with lower-TF CISD confirmation.",
        module=smc_weekly_sweep_cisd_engine,
        config_cls=smc_weekly_sweep_cisd_engine.WeeklySweepCISDConfig,
    ),
    _section(
        id="smc_mtf_day_plan",
        hub="smart_money",
        label="MTF Day Plan OB · FVG · CHoCH",
        description="HTF trend + OB/FVG zones with LTF CHoCH day plan.",
        module=smc_mtf_day_plan_engine,
        config_cls=smc_mtf_day_plan_engine.DayPlanConfig,
    ),
    _section(
        id="smc_golden_bullet",
        hub="smart_money",
        label="Golden Bullet (Liquidity + Kill Zone)",
        description="Liquidity sweep in NY kill zones with HTF bias.",
        module=smc_golden_bullet_engine,
        config_cls=smc_golden_bullet_engine.GoldenBulletConfig,
    ),
    _section(
        id="smc_liquidity_silver_bullet",
        hub="smart_money",
        label="Liquidity, Inducement & Silver Bullet",
        description=(
            "HTF structure bias, then the executable Silver Bullet sequence: liquidity sweep of the day's "
            "high/low during the London or NY session, Market Structure Shift confirmation, entry on the "
            "Fair Value Gap formed during that shift, stop beyond the order block. Min 1:2 R:R. "
            "Video: https://www.youtube.com/watch?v=xnEioNLgNMM"
        ),
        module=smc_liquidity_silver_bullet_engine,
        config_cls=smc_liquidity_silver_bullet_engine.LiquiditySilverBulletConfig,
        config_options={
            "htf_tf": {
                "type": "select",
                "label": "Higher timeframe (structure bias)",
                "choices": [{"value": v, "label": v} for v in smc_liquidity_silver_bullet_engine.HTF_OPTIONS],
                "default": "4h",
            },
            "execution_tf": {
                "type": "select",
                "label": "Execution timeframe (sweep/MSS/FVG)",
                "choices": [{"value": v, "label": v} for v in smc_liquidity_silver_bullet_engine.LTF_OPTIONS],
                "default": "15m",
            },
        },
    ),
    _section(
        id="scalp_arc",
        hub="scalping",
        label="ARC Method Scalping",
        description="Area/Range/Candle boundary fades with John Wick hammer trigger at the four institutional zones.",
        module=scalp_arc_engine,
        config_cls=scalp_arc_engine.ArcConfig,
    ),
    _section(
        id="scalp_crt_fvg",
        hub="scalping",
        label="CRT + FVG Scalping",
        description="HTF Candle-Range-Theory liquidity sweep confirmed by an LTF Fair Value Gap entry.",
        module=scalp_crt_fvg_engine,
        config_cls=scalp_crt_fvg_engine.CrtFvgConfig,
    ),
    _section(
        id="scalp_multi_indicator",
        hub="scalping",
        label="Multi-Indicator Confluence Scalp",
        description="UT Bot + QQE + Vaddah Attar momentum + EMA pullback + volume delta confluence.",
        module=scalp_multi_indicator_engine,
        config_cls=scalp_multi_indicator_engine.MultiIndicatorConfig,
    ),
    _section(
        id="scalp_smc",
        hub="scalping",
        label="SMC Rule-of-3-TFs Scalp",
        description="Premium/discount/OTE zone plus FVG/order-block/CRT-sweep signal fusion across HTF/MTF/LTF.",
        module=scalp_smc_engine,
        config_cls=scalp_smc_engine.ScalpSMCConfig,
    ),
    _section(
        id="scalp_sr_mss",
        hub="scalping",
        label="HTF S/R + 1m MSS Scalp",
        description="1H/4H support/resistance zone tap confirmed by a 1-minute market structure shift.",
        module=scalp_sr_mss_engine,
        config_cls=scalp_sr_mss_engine.SrMssConfig,
    ),
    _section(
        id="scalp_weekly",
        hub="scalping",
        label="Scalp - Weekly",
        description="Previous week's high/low as a liquidity box — false-breakout fade on a lower timeframe.",
        module=scalp_weekly_engine,
        config_cls=scalp_weekly_engine.ScalpWeeklyConfig,
        config_options={
            "execution_tf": {
                "type": "select",
                "label": "Execution timeframe",
                "choices": [{"value": v, "label": v} for v in scalp_weekly_engine.LTF_OPTIONS],
                "default": "1h",
            },
        },
    ),
    _section(
        id="scalp_ichimoku_crash",
        hub="scalping",
        label="Ichimoku Crash Predictor",
        description=(
            "4-condition Ichimoku Cloud alignment (Tenkan/Kijun cross, Chikou confirmation, cloud "
            "resistance) for catching crash-scale moves — AbhishekXTrades. "
            "Video: https://www.youtube.com/watch?v=TqqqxCpPxoM"
        ),
        module=scalp_ichimoku_crash_engine,
        config_cls=scalp_ichimoku_crash_engine.IchimokuCrashConfig,
        config_options={
            "execution_tf": {
                "type": "select",
                "label": "Execution timeframe",
                "choices": [{"value": v, "label": v} for v in scalp_ichimoku_crash_engine.EXECUTION_TF_OPTIONS],
                "default": "4h",
            },
        },
    ),
    _section(
        id="scalp_ny_open_bias",
        hub="scalping",
        label="NY Open 1H Bias",
        description=(
            "The 9:00 AM ET 1-hour candle sets the day's bias (green -> longs only, red -> shorts only), "
            "executed on the 1-minute chart via one of three entry styles: first-5-minute break & retest, "
            "previous day high/low break & retest, or the one-candle-rule support/resistance hold. "
            "Min 1:2 R:R. Video: https://www.youtube.com/watch?v=qhF61rJBOyE — Scarface Trades."
        ),
        module=scalp_ny_open_bias_engine,
        config_cls=scalp_ny_open_bias_engine.NyOpenBiasConfig,
        config_options={
            "entry_style": {
                "type": "select",
                "label": "Entry style",
                "choices": [
                    {"value": v, "label": scalp_ny_open_bias_engine.ENTRY_STYLE_LABELS[v]}
                    for v in scalp_ny_open_bias_engine.ENTRY_STYLE_OPTIONS
                ],
                "default": "five_min_break_retest",
            },
        },
    ),
    _section(
        id="weekly_candle_continuation",
        hub="scalping",
        label="Weekly Candle Continuation",
        description=(
            "Trades WITH market makers extending a trend, not against it: first break of the weekly "
            "high/low is not an entry — wait for a pullback off that push, then a strong displacement "
            "close beyond the confirmation level triggers continuation in the original direction."
        ),
        module=weekly_candle_continuation_engine,
        config_cls=weekly_candle_continuation_engine.WeeklyCandleContinuationConfig,
        config_options={
            "entry_tf": {
                "type": "select",
                "label": "Entry timeframe",
                "choices": [{"value": v, "label": v} for v in weekly_candle_continuation_engine.ENTRY_TF_OPTIONS],
                "default": "1h",
            },
        },
    ),
    _section(
        id="smc_htf_zone_sweep",
        hub="smart_money",
        label="HTF Zone + LTF Liquidity Sweep",
        description=(
            "HTF (1h/4h) trend + fresh FVG/Order Block zone -> wait for pullback into the zone -> "
            "LTF (5m/15m) liquidity grab (stop-hunt wick) confirms entry. Trades with institutional flow, "
            "not against it — never enters at the obvious level, only after the sweep."
        ),
        module=smc_htf_zone_sweep_engine,
        config_cls=smc_htf_zone_sweep_engine.SMCZoneSweepConfig,
        config_options={
            "htf_tf": {
                "type": "select",
                "label": "HTF (structure + zone)",
                "choices": [{"value": v, "label": v} for v in smc_htf_zone_sweep_engine.HTF_OPTIONS],
                "default": "1h",
            },
            "ltf_tf": {
                "type": "select",
                "label": "LTF (liquidity grab confirmation)",
                "choices": [{"value": v, "label": v} for v in smc_htf_zone_sweep_engine.LTF_OPTIONS],
                "default": "15m",
            },
        },
    ),
    _section(
        id="smc_liquidity",
        hub="smart_money",
        label="SMC Liquidity (Sweeps/Grabs/FVG)",
        description="Structural BSL/SSL sweep-vs-grab classification, liquidity runs, and fair-value-gap rebalance entries.",
        module=smc_liquidity_engine,
        config_cls=smc_liquidity_engine.LiquidityConfig,
    ),
    _section(
        id="smc_ttg_sniper",
        hub="smart_money",
        label="SM - TTG - Sniper Entry",
        description="Liquidity sweep + displacement + Order Block + Fair Value Gap tap, HTF-trend-aligned, aggressive or conservative (MSS-confirmed) entry.",
        module=smc_ttg_sniper_engine,
        config_cls=smc_ttg_sniper_engine.TTGSniperConfig,
        config_options={
            "ltf": {
                "type": "select",
                "label": "Execution timeframe (LTF)",
                "choices": [{"value": v, "label": v} for v in smc_ttg_sniper_engine.LTF_OPTIONS],
                "default": "15m",
            },
            "htf": {
                "type": "select",
                "label": "HTF trend bias",
                "choices": [{"value": v, "label": v} for v in smc_ttg_sniper_engine.HTF_OPTIONS],
                "default": "1h",
            },
            "entry_mode": {
                "type": "select",
                "label": "Entry mode",
                "choices": [{"value": v, "label": v} for v in smc_ttg_sniper_engine.ENTRY_MODE_OPTIONS],
                "default": "Aggressive",
            },
        },
    ),
    _section(
        id="smb_snp",
        hub="smart_money",
        label="SMB \"Fashionably Late\"",
        description="9 EMA x VWAP cross-up after a low-of-day grind inside a session time window, sized off the LOD unit at 3:1 R:R.",
        module=smb_snp_engine,
        config_cls=smb_snp_engine.SmbSnpConfig,
    ),
    _section(
        id="swing_trading_st_simple_steal",
        hub="swing",
        label="Little Rizzy (Trendline Measured Move)",
        description="Trendline across swing highs/lows projects a measured-move target, confirmed by Bollinger Bands.",
        module=swing_trading_st_simple_steal_engine,
        config_cls=swing_trading_st_simple_steal_engine.SimpleStealConfig,
    ),
    _section(
        id="swing_5_strategies",
        hub="swing",
        label="Swing Trading — 5 Strategies",
        description=(
            "Breakouts · Episodic Pivots (Gap and Go) · Pullbacks · Uptrending Bounces · Bottom Bounces "
            "(falling knife) — five long-only swing setups from a professional trader's breakdown. Pick "
            "one or more strategies and one or more timeframes to scan."
        ),
        module=swing_5_strategies_engine,
        config_cls=swing_5_strategies_engine.Swing5Config,
        multi_strategy=True,
        strategy_keys=swing_5_strategies_engine.STRATEGY_KEYS,
        strategy_labels=swing_5_strategies_engine.STRATEGY_LABELS,
        timeframe_options=swing_5_strategies_engine.TIMEFRAME_OPTIONS,
    ),
    _section(
        id="swing_trend_breakout",
        hub="swing",
        label="Trend Following Breakout (Index Filter)",
        description=(
            "Index above its 20 SMA -> momentum leader near its 52-week high with a confirmed weekly "
            "uptrend -> daily swing-high breakout after a pullback. Long-only; works just as well on "
            "sectoral/index ETFs as individual stocks."
        ),
        module=swing_trend_breakout_engine,
        config_cls=swing_trend_breakout_engine.SwingTrendBreakoutConfig,
        config_options={
            "market_filter": {
                "type": "select",
                "label": "Market trend filter (index 20 SMA)",
                "choices": [
                    {"value": "on", "label": "On — require Nifty/SPY/BTC above its 20 SMA"},
                    {"value": "off", "label": "Off — scan regardless of market trend"},
                ],
                "default": "on",
            },
            "stop_method": {
                "type": "select",
                "label": "Stop-loss method",
                "choices": [
                    {"value": "breakout_candle_low", "label": "Breakout candle low (tighter)"},
                    {"value": "swing_low", "label": "Recent swing low (wider)"},
                ],
                "default": "breakout_candle_low",
            },
        },
    ),
    _section(
        id="swing_trend_velocity",
        hub="swing",
        label="Trend Velocity — 50/250 MA + ROC Scale-Out",
        description=(
            "Systematic position-trading system (Malik's \"White Light\" bot): golden rule is price above "
            "BOTH the 50-day and 250-day moving averages for long (mirror for short), with a rate-of-change "
            "deceleration check that scales the position down without abandoning the trend. Low-frequency, "
            "held for months to years, no tactical stop-loss. Video: https://www.youtube.com/watch?v=pBS5vrqrUjk"
        ),
        module=swing_trend_velocity_engine,
        config_cls=swing_trend_velocity_engine.TrendVelocityConfig,
    ),
    _section(
        id="swing_bb_vwap_reversal",
        hub="swing",
        label="BB + VWAP Reversal",
        description=(
            "Bollinger Bands(20, mult 1) + VWAP(source Close) multi-timeframe reversal. HTF (1h/4h) sets "
            "the bias; on the LTF (5m/15m), a candle opening above VWAP and closing below the lower band "
            "shorts, the mirror opening below VWAP and closing above the upper band buys. Book ~50% at "
            "1:2, trail toward 1:3 while price holds the correct side of VWAP. "
            "Video: https://www.youtube.com/watch?v=5s_6CLbEa2g"
        ),
        module=swing_bb_vwap_reversal_engine,
        config_cls=swing_bb_vwap_reversal_engine.BbVwapReversalConfig,
        config_options={
            "htf_tf": {
                "type": "select",
                "label": "Higher timeframe (trend bias)",
                "choices": [{"value": v, "label": v} for v in swing_bb_vwap_reversal_engine.HTF_OPTIONS],
                "default": "1h",
            },
            "execution_tf": {
                "type": "select",
                "label": "Execution timeframe (entry trigger)",
                "choices": [{"value": v, "label": v} for v in swing_bb_vwap_reversal_engine.LTF_OPTIONS],
                "default": "15m",
            },
        },
    ),
    _section(
        id="intraday_mtf_breakout_retest",
        hub="intraday",
        label="Daniel Holmes MTF Breakout & Retest",
        description="Daily bias filter, 15m equal-body support/resistance, clean-traffic chop filter, breakout-then-retest entry.",
        module=intraday_mtf_breakout_retest_engine,
        config_cls=intraday_mtf_breakout_retest_engine.MtfBreakoutRetestConfig,
    ),
    _section(
        id="intraday_7_wasted",
        hub="intraday",
        label="7 Wasted - 5m OR Breakout & Retest",
        description="5-minute opening-range breakout with daily-bullish-bias gate and retest-of-OR-high entry at 2:1 R:R.",
        module=intraday_7_wasted_engine,
        config_cls=intraday_7_wasted_engine.Intra7WastedConfig,
    ),
    _section(
        id="intraday_london_breakout",
        hub="intraday",
        label="London Session Breakout",
        description=(
            "5m London-style range breakout: build high/low box in the early/pre-session window, "
            "enter on first active-session break with breakout-candle stop and 2:1 R:R. "
            "US uses Pre-Market→RTH; Crypto uses Low Activity→Global Peak (IST); "
            "India and Commodity keep their existing session maps."
        ),
        module=intraday_london_breakout_engine,
        config_cls=intraday_london_breakout_engine.LondonBreakoutConfig,
        config_options={
            "rr_ratio": {
                "type": "number",
                "label": "Risk : Reward",
                "default": 2.0,
                "min": 1.0,
                "max": 5.0,
                "step": 0.5,
            },
            "range_start": {
                "type": "text",
                "label": "Range start HH:MM (blank = asset default)",
                "default": "",
            },
            "range_end": {
                "type": "text",
                "label": "Range end HH:MM (blank = asset default)",
                "default": "",
            },
            "trade_start": {
                "type": "text",
                "label": "Trade start HH:MM (blank = asset default)",
                "default": "",
            },
            "trade_end": {
                "type": "text",
                "label": "Trade end HH:MM (blank = asset default)",
                "default": "",
            },
        },
        guide="""### London Session Breakout — range box → first break
[Easiest Way To Start Day Trading From Scratch](https://www.youtube.com/watch?v=8KblOEu56dM&t=2247s)

**Rules (5m):**
1. Draw a box from the absolute high to absolute low of the **range window**.
2. In the **trade window**, take the **first** 5m candle that breaks the box —
   long above the range high, short below the range low.
3. **Stop** at the opposite extreme of that breakout candle.
4. **Target** a strict **2:1** risk-to-reward. One trade per session.

**Asset-class session windows:**
| Asset class | Range box | Trade window | TZ / notes |
|---|---|---|---|
| **US** | Pre-Market **04:00–09:30 ET** | RTH **09:30–16:00 ET** | After-Hours 16:00–20:00 ET noted, not used for entries |
| **Crypto** | Low Activity **04:00–11:00 IST** | Global Peak **17:30–01:30 IST** | Local Prime 18:30–23:30 IST sits inside peak (12:00–20:00 UTC) |
| **India** | **09:15–11:30 IST** | **11:30–15:30 IST** | NSE cash open → close (unchanged) |
| **Commodity** | London **03:00–08:00 ET** | **08:00–16:00 ET** | Unchanged London-style map |

Optional HH:MM overrides in config replace the defaults for that scan.
""",
    ),
    _section(
        id="intraday_bramhastra",
        hub="intraday",
        label="Bramhastra Strategy — 1H Range + 5m Two-Stage Breakout",
        description=(
            "Pure price-action, indicator-free breakout: mark the session's first 1-hour candle's high/low, "
            "then on 5m wait for a candle to CLOSE beyond it (confirmation), then wait for a later candle to "
            "break the confirmation candle's own extreme (entry trigger). Fixed % stop, configurable R:R. "
            "Works across India, US, Crypto, and Commodities — indices, stocks, or crypto pairs."
        ),
        module=intraday_bramhastra_engine,
        config_cls=intraday_bramhastra_engine.BramhastraConfig,
        config_options={
            "max_sl_pct": {
                "type": "number",
                "label": "Max stop-loss (% of price)",
                "default": 0.2,
                "min": 0.05,
                "max": 2.0,
                "step": 0.05,
            },
            "rr_ratio": {
                "type": "number",
                "label": "Risk : Reward",
                "default": 1.3,
                "min": 1.0,
                "max": 3.0,
                "step": 0.1,
            },
            "monster_range_pct": {
                "type": "number",
                "label": "Skip session if 1H range ≥ this % of price (\"monster candle\")",
                "default": 0.7,
                "min": 0.2,
                "max": 3.0,
                "step": 0.1,
            },
        },
        guide="""### Bramhastra Strategy — 1-Hour range, 5-minute two-stage breakout
[Bramhastra Strategy | Trade Swings](https://www.youtube.com/watch?v=KMbMaRH_FEw)

A pure price-action, indicator-free intraday strategy — usable for both options buying and options selling — on
indices (Nifty, Bank Nifty, Fin Nifty), single stocks, crypto, or commodities.

**Timeframes:** Observation **1 Hour** · Execution **5 Minutes** · Indicators used: **none**.

| Step | Rule |
|---|---|
| **1. Mark the first hour** | Open the chart on 1H and look at the session's very first candle (color doesn't matter). Once that hour is complete, draw a line at its **High** and its **Low**. |
| **2. Switch to 5-minute** | After marking the High/Low, move to the 5-minute chart for everything that follows. |
| **3. Confirm (Stage A)** | Wait for a 5m candle to **CLOSE** beyond the 1H range — above the High for a long setup, below the Low for a short. A wick-only break that doesn't close beyond the line is a **fake breakout** — ignore it, a proper close is mandatory. Once confirmed, mark **that candle's own High (long) / Low (short)**. |
| **4. Trigger (Stage B)** | Entry fires when a **later** candle actually breaks the confirmation candle's marked level. Long = Call Buy / Put Sell. Short = Put Buy / Call Sell. |
| **5. Stop-loss** | Keep it strict — the video suggests a max of ~50 points on Nifty spot (~20-25 points on the options premium), which this hub applies as a **fixed % of price** so it scales sensibly to any instrument (default 0.2%). |
| **6. Target / R:R** | Aim for at least **1:1 to 1:1.5**. Typical options-premium targets run 35-45 points against a 20-25 point stop in the video's own examples. Trail the stop if you know how, and 1:3-1:4 becomes possible. |

**When to avoid this setup:**
- **Monster first-hour candle** — if the 1H range is unusually wide (150-200+ Nifty points, ≈0.6-0.8% of spot), skip the
  strategy for the rest of the day. A huge first-hour move usually means the rest of the day chops and stops out
  breakout attempts. This hub checks the range as a % of price (default skip threshold 0.7%, adjustable above) so it
  applies the same idea to any instrument.
- **Fake breakouts** — a break that doesn't CLOSE beyond the range is never treated as a confirmation, by construction.

**One trade per session** — whichever side (long or short) triggers first wins; the other side is ignored for the rest
of the day. Session boundaries (first-hour window, execution close) reuse this app's per-asset-class session profile
(India 09:15 IST, US 09:30 ET, Crypto 17:30 IST, Commodity 09:30 ET) — the same "first hour of the day" idea applied
correctly to each market's own open.
""",
    ),
    _section(
        id="intra_hwp",
        hub="intraday",
        label="Intra HWP - Two-Sided Gap Fill + 21 EMA",
        description="Fixed 5m/21 EMA gap-tag-and-reverse strategy — target Today's Open, stop beyond the swing extreme since the tag.",
        module=intra_hwp_engine,
        config_cls=intra_hwp_engine.HwpConfig,
    ),
    _section(
        id="scalp_heikin_ashi",
        hub="scalping",
        label="Scalp - Heikin Ashi",
        description="100 EMA trend filter + two-candle flat Heikin Ashi pullback confirmed by a high-volume Doji, strict 1:1 R:R, market-specific morning session window.",
        module=scalp_heikin_ashi_engine,
        config_cls=scalp_heikin_ashi_engine.HeikinAshiScalpConfig,
    ),
    _section(
        id="scalp_livefree_fx",
        hub="scalping",
        label="Scalp - LiveFree FX 5m",
        description="HTF bias (1D/4H/1H) + Asia/London/NY kill zones + London liquidity sweep + 5m Break of Structure entry. Video: https://www.youtube.com/watch?v=a74KPzR7phE",
        module=scalp_livefree_fx_engine,
        config_cls=scalp_livefree_fx_engine.LiveFreeConfig,
        config_options={
            "session_profile": {
                "type": "select",
                "label": "Session profile",
                "choices": [
                    {"value": "auto", "label": "Auto (India → IST / others → EST)"},
                    {"value": "fx_est", "label": "FX / ICT EST kill zones"},
                    {"value": "india_ist", "label": "India IST cash-session analogue"},
                ],
                "default": "auto",
            },
        },
    ),
    _section(
        id="sc_fvg",
        hub="smart_money",
        label="SC - FVG (Reversal at Key Levels)",
        description="15m HTF resistance/support zone + 5m Fair Value Gap exhaustion + 1m rejection candle & structure shift entry, fixed 3:1 R:R.",
        module=sc_fvg_engine,
        config_cls=sc_fvg_engine.ScFvgConfig,
    ),
    _section(
        id="scalp_2min",
        hub="scalping",
        label="Scalp-2mins",
        description=(
            "2-minute 10/20 EMA pullback scalp on Nifty / Bank Nifty / Sensex with ITM "
            "option-leg selection. India index options only — not available for Crypto, US, "
            "or commodities."
        ),
        module=scalp_2min_engine,
        config_cls=scalp_2min_engine.Scalp2MinConfig,
        fixed_universe=list(scalp_2min_engine.INDEX_NAMES),
        fixed_universe_label="Nifty 50 · Bank Nifty · Sensex (India index options)",
    ),
    _section(
        id="smc_sc_best",
        hub="smart_money",
        label="SC-Best (5 SMC Entry Models)",
        description="Context (HTF bias/sweep) → Confirmation (LTF MSS) → Execution via Breaker Block, Fair Value Gap, Mitigation Block, Inversion FVG, or Order Block — resting limit orders at the structural origin, never a chase.",
        module=smc_sc_best_engine,
        config_cls=smc_sc_best_engine.SCBestConfig,
        config_options={
            "ltf": {
                "type": "select",
                "label": "LTF confirmation/execution timeframe",
                "choices": [{"value": v, "label": v} for v in smc_sc_best_engine.LTF_OPTIONS],
                "default": "15m",
            },
        },
    ),
    _section(
        id="smc_lewiskelly",
        hub="smart_money",
        label="C-LewisKelly (Direction · Liquidity · Location · Confirmation)",
        description="15m external structure sets bias, session/PDH-PDL liquidity sets targets, a 15m Order Block + FVG confluence is the POI, and a 1m Change of Character at that POI confirms entry.",
        module=smc_lewiskelly_engine,
        config_cls=smc_lewiskelly_engine.LewisKellyConfig,
        config_options={
            "htf_tf": {
                "type": "select",
                "label": "Direction / POI timeframe",
                "choices": [{"value": v, "label": v} for v in smc_lewiskelly_engine.HTF_OPTIONS],
                "default": "15m",
            },
        },
    ),
]

HUB_META = {
    "swing": {
        "id": "swing",
        "label": "Swing Trading",
        "description": "Multi-day & intraday ST systems — capitulation, MSS, SuperTrend, KISS, HA+EMA.",
    },
    "intraday": {
        "id": "intraday",
        "label": "Intraday",
        "description": "Session-timed scanners and opening-range breakout systems for NSE.",
    },
    "scalping": {
        "id": "scalping",
        "label": "Scalping",
        "description": "High-frequency 1m setups — rectangle sniper entries and quick R:R scalps.",
    },
    "smart_money": {
        "id": "smart_money",
        "label": "Smart Money",
        "description": "SMC liquidity, sweep, and institutional delivery models — multi-TF for India.",
    },
}

_SECTION_BY_ID = {s["id"]: s for s in HUB_SECTIONS}


def get_section(section_id: str) -> HubSection | None:
    return _SECTION_BY_ID.get(section_id)


def build_config(config_cls: type, overrides: dict[str, Any] | None) -> Any:
    if not overrides:
        return config_cls()
    fields = {f.name: f for f in dataclasses.fields(config_cls)}
    cleaned: dict[str, Any] = {}
    for k, v in overrides.items():
        if k not in fields:
            continue
        if v is None or v == "":
            continue
        f = fields[k]
        typ = f.type
        origin = getattr(typ, "__origin__", None)
        if origin is not None:
            args = [a for a in getattr(typ, "__args__", ()) if a is not type(None)]
            typ = args[0] if args else typ
        try:
            if typ is float or typ == "float":
                cleaned[k] = float(v)
            elif typ is int or typ == "int":
                cleaned[k] = int(float(v))
            elif typ is bool or typ == "bool":
                cleaned[k] = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
            else:
                cleaned[k] = v
        except (TypeError, ValueError):
            cleaned[k] = v
    return config_cls(**cleaned)


def list_hubs_payload() -> dict:
    hubs = []
    for hub_id, meta in HUB_META.items():
        sections = [
            {
                "id": s["id"],
                "label": s["label"],
                "description": s["description"],
                "guide": s.get("guide"),
                "config_options": s["config_options"],
                "fixed_universe": s.get("fixed_universe"),
                "fixed_universe_label": s.get("fixed_universe_label"),
                "multi_strategy": s.get("multi_strategy", False),
                "strategy_keys": s.get("strategy_keys") or [],
                "strategy_labels": s.get("strategy_labels") or {},
                "timeframe_options": s.get("timeframe_options") or [],
            }
            for s in HUB_SECTIONS
            if s["hub"] == hub_id
        ]
        hubs.append({**meta, "sections": sections})
    return {"hubs": hubs}


def run_section_scan(
    section_id: str,
    tickers: list[str],
    *,
    market: str,
    groww_token: str,
    exchange: str,
    config: dict[str, Any] | None = None,
    run_bt: bool = False,
) -> dict[str, Any]:
    section = get_section(section_id)
    if not section:
        return {"error": f"Unknown section: {section_id}"}
    if section.get("multi_strategy"):
        return {"error": f"{section_id} is a multi-strategy section — use its dedicated scan endpoint instead."}
    mod = section["module"]
    cfg = build_config(section["config_cls"], config)
    kwargs: dict[str, Any] = {
        "cfg": cfg,
        "groww_token": groww_token,
        "exchange": exchange,
    }
    if "run_bt" in inspect.signature(mod.scan_universe).parameters:
        kwargs["run_bt"] = run_bt
    payload = mod.scan_universe(tickers, market, **kwargs)
    return payload or {"error": "Scan returned no data", "results": []}
