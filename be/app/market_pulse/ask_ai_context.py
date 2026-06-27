"""
Collect section-specific analysis context for the Ask AI panel (from session state).
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
MAX_CTX_CHARS = 14_000


def _trunc(text: str, limit: int = MAX_CTX_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n...[truncated {len(text) - limit} chars]"


def serialize_for_ask_ai(obj: Any, *, limit: int = MAX_CTX_CHARS) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return _trunc(obj, limit)
    if isinstance(obj, pd.DataFrame):
        return _trunc(obj.head(50).to_string(), limit)
    if isinstance(obj, pd.Series):
        return _trunc(obj.head(50).to_string(), limit)
    try:
        return _trunc(json.dumps(obj, indent=1, default=str), limit)
    except (TypeError, ValueError):
        return _trunc(str(obj), limit)


def clear_ask_ai_context(section_id: str) -> None:
    st.session_state.pop(f"ask_ai_ctx_{section_id}", None)


def register_ask_ai_context(section_id: str, context: Any, *, label: str = "") -> None:
    block = serialize_for_ask_ai(context)
    if not block:
        return
    key = f"ask_ai_ctx_{section_id}"
    existing = st.session_state.get(key, "")
    header = f"=== {label} ===\n" if label else ""
    chunk = f"{header}{block}"
    st.session_state[key] = f"{existing}\n\n{chunk}".strip() if existing else chunk


def get_ask_ai_context(section_id: str) -> str:
    return st.session_state.get(f"ask_ai_ctx_{section_id}", "")


def publish_section_display(section_id: str, text: str) -> None:
    """Snapshot on-screen analysis output (call from @st.fragment section renderers)."""
    block = (text or "").strip()
    if block:
        st.session_state[f"ask_ai_display_{section_id}"] = _trunc(block)


def _format_tomorrow_outlook(outlook: dict) -> str:
    lines = [
        "=== TOMORROW'S MARKET OUTLOOK ===",
        f"Label: {outlook.get('emoji', '')} {outlook.get('label', '')}",
        f"Verdict: {outlook.get('verdict', 'N/A')}",
        f"Outlook Score: {outlook.get('score', 'N/A')}",
        f"Confidence: {outlook.get('confidence', 'N/A')}",
        f"Summary: {outlook.get('explanation', '')}",
    ]
    for d in outlook.get("drivers") or []:
        lines.append(f"  • {d}")
    return "\n".join(lines)


def _format_today_sentiment(sent: dict) -> str:
    lines = [
        "=== TODAY'S MARKET SENTIMENT ===",
        f"Label: {sent.get('emoji', '')} {sent.get('label', '')}",
        f"Verdict: {sent.get('verdict', 'N/A')}",
        f"Composite Score: {sent.get('score', 'N/A')}",
    ]
    for s in sent.get("signals") or []:
        lines.append(f"  • {s}")
    return "\n".join(lines)


def format_outlook_payload_for_ai(payload: dict) -> str:
    """Human-readable outlook context matching the Command Center banners."""
    parts: list[str] = []
    if payload.get("tomorrow_outlook"):
        parts.append(_format_tomorrow_outlook(payload["tomorrow_outlook"]))
    if payload.get("market_sentiment"):
        parts.append(_format_today_sentiment(payload["market_sentiment"]))

    fii = payload.get("fii_dii_data")
    if fii:
        parts.append("=== FII / DII FLOWS ===\n" + serialize_for_ask_ai(fii, limit=1200))

    opt_sent = payload.get("sentiment")
    if opt_sent:
        parts.append("=== NIFTY OPTIONS SENTIMENT ===\n" + serialize_for_ask_ai(opt_sent, limit=1200))

    opt = payload.get("option_data")
    if opt:
        parts.append(
            "=== NIFTY OPTIONS CHAIN (summary) ===\n"
            f"Underlying: {opt.get('underlying')} | PCR OI: {opt.get('pcr_oi')} | "
            f"PCR Vol: {opt.get('pcr_vol')} | Max Pain: {opt.get('max_pain')}"
        )

    md = payload.get("market_data") or {}
    if md:
        key_names = [
            "Nifty 50", "Bank Nifty", "Sensex", "Nifty IT", "Nifty Midcap 150",
            "India VIX", "Gift Nifty", "S&P 500 Futures", "Nasdaq Futures", "Dow Futures",
        ]
        q_lines = ["=== KEY MARKET QUOTES ==="]
        for name in key_names:
            d = md.get(name) or {}
            price, pct = d.get("price"), d.get("pct")
            if price is not None:
                pct_s = f"{pct:+.2f}%" if pct is not None else "N/A"
                q_lines.append(f"{name}: {price} ({pct_s})")
        parts.append("\n".join(q_lines))

    breadth = payload.get("breadth_data")
    if breadth and breadth.get("indices"):
        n500 = breadth["indices"].get("NIFTY 500") or {}
        if n500:
            parts.append(
                f"=== NIFTY 500 BREADTH ===\n"
                f"Advances: {n500.get('advances')} | Declines: {n500.get('declines')}"
            )
    return "\n\n".join(parts)


def format_news_scanner_payload_for_ai(payload: dict) -> str:
    """Full news-scanner context for Ask AI."""
    parts = [format_outlook_payload_for_ai(payload)]
    td = payload.get("turnover_delivery_data")
    if td:
        parts.append("=== DELIVERY / TURNOVER ===\n" + serialize_for_ask_ai(td, limit=2000))
    news = payload.get("news_articles") or []
    if news:
        headlines = [f"  • {a.get('title', '')[:120]}" for a in news[:12]]
        parts.append("=== RECENT NEWS HEADLINES ===\n" + "\n".join(headlines))
    calls = payload.get("analyst_calls") or []
    if calls:
        call_lines = []
        for c in calls[:15]:
            call_lines.append(
                f"  • {c.get('action', '—')} {c.get('stock', '—')} "
                f"({c.get('brokerage', '—')}): {c.get('title', '')[:100]}"
            )
        parts.append("=== ANALYST CALLS / BROKERAGE RECOS ===\n" + "\n".join(call_lines))
    india_ev = payload.get("india_events") or []
    global_ev = payload.get("global_events") or []
    if india_ev or global_ev:
        ev_lines = []
        for e in (india_ev + global_ev)[:12]:
            ev_lines.append(f"  • [{e.get('impact', '')}] {e.get('title', '')} — {e.get('date', '')}")
        parts.append("=== UPCOMING MACRO EVENTS ===\n" + "\n".join(ev_lines))
    ai_html = st.session_state.get("ns_ai_summary_html")
    if ai_html:
        parts.append("=== AI MARKET SUMMARY (from scanner) ===\n" + str(ai_html)[:4000])
    return "\n\n".join(p for p in parts if p)


def _summarize_pa_like_results(results: dict, *, max_rows: int = 20) -> str:
    lines = [f"Result rows: {len(results)}"]
    for i, (key, row) in enumerate(results.items()):
        if i >= max_rows:
            lines.append(f"... and {len(results) - max_rows} more")
            break
        if "error" in row:
            lines.append(f"{key}: ERROR — {row['error']}")
            continue
        analysis = row.get("analysis") or {}
        sr = analysis.get("support_resistance") or {}
        setups = analysis.get("trade_setups") or []
        trend = analysis.get("trend") or analysis.get("ema", {}).get("trend", "N/A")
        rsi = analysis.get("rsi", {}).get("value", "N/A")
        setup_txt = setups[0].get("type", "none") if setups else "none"
        lines.append(
            f"{key}: trend={trend} RSI={rsi} "
            f"S1={sr.get('s1', '—')} R1={sr.get('r1', '—')} setup={setup_txt}"
        )
    return "\n".join(lines)


def _ctx_command_outlook() -> str | None:
    payload = st.session_state.get("cc_outlook_payload")
    if payload:
        return format_outlook_payload_for_ai(payload)
    # Shared payload if user refreshed via News Scanner only
    payload = st.session_state.get("ns_scanner_payload")
    if payload:
        return format_outlook_payload_for_ai(payload)
    return None


def _ctx_news_scanner() -> str | None:
    payload = st.session_state.get("ns_scanner_payload")
    if payload:
        return format_news_scanner_payload_for_ai(payload)
    return None


def _ctx_nifty_breadth() -> str | None:
    breadth = st.session_state.get("nifty_breadth_data")
    if not breadth:
        return None
    indices = breadth.get("indices") or {}
    loaded = int(st.session_state.get("nifty_breadth_loaded_count") or 0)
    sr_map = st.session_state.get("nifty_breadth_sr_map") or {}
    units = st.session_state.get("nifty_breadth_units") or []
    names = [u["name"] for u in units[:loaded] if u.get("name")]
    if not names:
        names = list(indices.keys())[:20]
    lines = [f"Nifty breadth snapshot: {len(indices)} indices, {loaded} loaded in UI"]
    for name in names[:25]:
        b = indices.get(name, {})
        sr = sr_map.get(name, {})
        lines.append(
            f"{name}: ▲{b.get('advances', 0)} ▼{b.get('declines', 0)} "
            f"chg={b.get('pct', 0):+.2f}% S1={sr.get('s1', '—')} R1={sr.get('r1', '—')}"
        )
    return "\n".join(lines)


def _ctx_nifty_monthly() -> str | None:
    breadth = st.session_state.get("nifty_monthly_breadth")
    if not breadth:
        return None
    monthly = breadth.get("monthly") or {}
    loaded = int(st.session_state.get("nifty_monthly_loaded_count") or 0)
    units = st.session_state.get("nifty_monthly_units") or []
    lines = [f"1M performance: {len(monthly)} indices, {loaded} sections loaded"]
    for unit in units[1:loaded + 1]:
        if unit.get("kind") != "index":
            continue
        name = unit.get("name")
        data = monthly.get(name, {})
        lines.append(f"{name}: 1M {data.get('pct_30d', 0):+.2f}%")
        if len(lines) > 30:
            break
    return "\n".join(lines)


def _ctx_market_gainers_losers() -> str | None:
    payload = st.session_state.get("market_gainers_losers_payload")
    if not payload or not isinstance(payload, dict):
        return None
    lines = [
        f"Markets: {payload.get('markets')} · "
        f"Loaded: {payload.get('loaded_count', 0)}/{payload.get('unit_count', 0)}",
    ]
    for res in (payload.get("results") or [])[:15]:
        movers = res.get("movers") or {}
        if res.get("error"):
            lines.append(f"{res.get('label')}: ERROR {res['error']}")
            continue
        g = movers.get("gainers", [])[:3]
        l = movers.get("losers", [])[:3]
        lines.append(
            f"{res.get('label')} gainers={[x.get('symbol') for x in g]} "
            f"losers={[x.get('symbol') for x in l]}"
        )
    return "\n".join(lines)


def _ctx_nifty_gainers_losers() -> str | None:
    breadth = st.session_state.get("nifty_gainers_losers_breadth")
    if not breadth:
        return None
    indices = breadth.get("indices") or {}
    loaded = int(st.session_state.get("nifty_gl_loaded_count") or 0)
    fo = st.session_state.get("nifty_gl_fo_movers") or {}
    lines = [f"Gainers/losers: {loaded} index sections loaded"]
    for name, movers in list(fo.items())[:15]:
        if not movers:
            continue
        g = movers.get("gainers", [])[:3]
        l = movers.get("losers", [])[:3]
        lines.append(
            f"{name} ({indices.get(name, {}).get('pct', 0):+.2f}%): "
            f"gainers={[x.get('symbol') for x in g]} losers={[x.get('symbol') for x in l]}"
        )
    return "\n".join(lines)


def _ctx_sector_rotation() -> str | None:
    payload = st.session_state.get("sector_rotation_payload")
    return serialize_for_ask_ai(payload) if payload else None


def _ctx_sector_rotation_intraday() -> str | None:
    payload = st.session_state.get("sector_rotation_intraday_payload")
    return serialize_for_ask_ai(payload) if payload else None


def _ctx_sector_rotation_us() -> str | None:
    payload = st.session_state.get("sector_rotation_us_payload")
    return serialize_for_ask_ai(payload) if payload else None


def _ctx_sector_rotation_us_intraday() -> str | None:
    payload = st.session_state.get("sector_rotation_us_intraday_payload")
    return serialize_for_ask_ai(payload) if payload else None


def _ctx_sector_rotation_crypto() -> str | None:
    payload = st.session_state.get("sector_rotation_crypto_payload")
    return serialize_for_ask_ai(payload) if payload else None


def _ctx_sector_rotation_crypto_intraday() -> str | None:
    payload = st.session_state.get("sector_rotation_crypto_intraday_payload")
    return serialize_for_ask_ai(payload) if payload else None


def _ctx_opposite_hedge_mtf() -> str | None:
    payload = st.session_state.get("opposite_hedge_mtf_payload")
    if not payload:
        return None
    lines = [
        f"Capital: ₹{payload.get('capital', 0):,.0f}",
        f"Data feed: {payload.get('data_feed', 'yfinance')}",
        f"Plans: {payload.get('plan_count', 0)} windows",
    ]
    c = payload.get("consensus") or {}
    if c:
        lines.append(
            f"Consensus LONG {c.get('long_ticker')} {c.get('long_alloc_pct')}% "
            f"conf {c.get('long_confidence_pct')}% SL -{c.get('long_sl_pct')}% TP +{c.get('long_tp_pct')}%"
        )
        lines.append(
            f"Consensus SHORT {c.get('short_ticker')} {c.get('short_alloc_pct')}% "
            f"conf {c.get('short_confidence_pct')}% SL -{c.get('short_sl_pct')}% TP +{c.get('short_tp_pct')}%"
        )
    for p in (payload.get("plans") or [])[:6]:
        lg, sh = p.get("long", {}), p.get("short", {})
        lines.append(
            f"  {p.get('window_label')}: LONG {lg.get('ticker')} {lg.get('alloc_pct')}% "
            f"SHORT {sh.get('ticker')} {sh.get('alloc_pct')}% edge {p.get('spread_edge_pct')}%"
        )
    return "\n".join(lines)


def _format_mtf_bias_scan_line(r: dict) -> str:
    base = (
        f"  {r['ticker']}: {r['confidence_pct']} score {r['weighted_score']:+.2f} — {r['close_bias']}"
    )
    if r.get("sl_pct") is not None:
        base += (
            f" | {r.get('trade_direction', '—')} @ {r.get('trade_tf', '—')} "
            f"SL -{r['sl_pct']:.2f}% TP +{r.get('tp_pct', 0):.2f}% "
            f"hold {r.get('hold_duration', '—')} ({r.get('setup_status', '—')})"
        )
    return base


def _ctx_mtf_intraday_bias() -> str | None:
    payload = st.session_state.get("mtf_intraday_bias_payload")
    if not payload:
        return None
    lines = [
        f"Analyzed: {payload.get('analyzed_count', 0)}/{payload.get('ticker_count', 0)}",
        f"Timeframes: {payload.get('timeframe_summary', '—')}",
        "Bullish:",
    ]
    for r in (payload.get("bullish") or [])[:8]:
        lines.append(_format_mtf_bias_scan_line(r))
    lines.append("Bearish:")
    for r in (payload.get("bearish") or [])[:8]:
        lines.append(_format_mtf_bias_scan_line(r))
    return "\n".join(lines)


def _ctx_mtf_intraday_bias_crypto() -> str | None:
    from app.market_pulse.crypto_session import CRYPTO_SESSION_LABEL

    payload = st.session_state.get("mtf_intraday_bias_crypto_payload")
    if not payload:
        return None
    lines = [
        "Market: CoinDCX USDT (crypto)",
        f"Session: {payload.get('session_label', CRYPTO_SESSION_LABEL)}",
        f"Analyzed: {payload.get('analyzed_count', 0)}/{payload.get('ticker_count', 0)}",
        f"Timeframes: {payload.get('timeframe_summary', '—')}",
        "Bullish:",
    ]
    for r in (payload.get("bullish") or [])[:8]:
        lines.append(_format_mtf_bias_scan_line(r))
    lines.append("Bearish:")
    for r in (payload.get("bearish") or [])[:8]:
        lines.append(_format_mtf_bias_scan_line(r))
    return "\n".join(lines)


def _ctx_stock_price_rotation_us() -> str | None:
    payload = st.session_state.get("stock_price_rotation_us_payload")
    return serialize_for_ask_ai(payload) if payload else None


def _ctx_stock_price_rotation_crypto() -> str | None:
    payload = st.session_state.get("stock_price_rotation_crypto_payload")
    return serialize_for_ask_ai(payload) if payload else None


def _ctx_stock_price_rotation() -> str | None:
    payload = st.session_state.get("stock_price_rotation_payload")
    return serialize_for_ask_ai(payload) if payload else None


def _ctx_commodity_screener() -> str | None:
    payload = st.session_state.get("commodity_screener_payload")
    return serialize_for_ask_ai(payload) if payload else None


def _ctx_accurate_strategy() -> str | None:
    payload = st.session_state.get("accurate_strategy_payload")
    if not payload or not isinstance(payload, dict):
        return None
    lines = [
        f"Market: {payload.get('market')} · TF: {payload.get('timeframe')}",
    ]
    for res in payload.get("results") or []:
        if res.get("error"):
            lines.append(f"{res.get('ticker')}: ERROR {res.get('error')}")
            continue
        latest = res.get("latest_signal") or {}
        lines.append(
            f"{res.get('ticker')} @ {res.get('price')} | signals={res.get('signal_count')} | "
            f"OB={len(res.get('order_blocks') or [])} FVG={len(res.get('fvgs') or [])} "
            f"SR={len(res.get('sr_zones') or [])}"
        )
        if latest:
            lines.append(
                f"  SETUP {latest.get('side')} conf={latest.get('confluence_score')}% "
                f"SL -{latest.get('sl_pct')}% TP +{latest.get('tp_pct')}% "
                f"entry {latest.get('entry')} stop {latest.get('stop')} target {latest.get('target')}"
            )
        summ = res.get("summary") or res.get("raw_summary") or {}
        if summ:
            lines.append(
                f"  backtest: {summ.get('total_trades', 0)} trades "
                f"win={summ.get('win_rate_pct')}% pnl={summ.get('total_pnl')}"
            )
    return "\n".join(lines) if len(lines) > 1 else None


def _ctx_pump_dump_breakout() -> str | None:
    payload = st.session_state.get("pump_dump_breakout_payload")
    if not payload or not isinstance(payload, dict):
        return None
    lines = [f"Market: {payload.get('market')} · TF: {payload.get('timeframe')}"]
    for res in payload.get("results") or []:
        if res.get("error"):
            lines.append(f"{res.get('symbol')}: ERROR {res.get('error')}")
            continue
        live = res.get("live") or {}
        setup = live.get("latest_signal") or {}
        lines.append(
            f"{res.get('symbol')} screen={'PASS' if res.get('screened') else 'FAIL'} "
            f"24h={res.get('change_24h_pct')}% consolidating={live.get('is_consolidating')}"
        )
        if setup:
            lines.append(
                f"  SIGNAL {setup.get('side')} SL -{setup.get('sl_pct')}% "
                f"TP +{setup.get('tp_pct')}% entry={setup.get('entry')}"
            )
        bt = res.get("backtest") or {}
        if bt.get("trades"):
            lines.append(
                f"  backtest: {bt.get('trades')} trades win={bt.get('win_rate_pct')}% "
                f"net=${bt.get('net_pnl_$')}"
            )
    return "\n".join(lines) if len(lines) > 1 else None


def _ctx_big_whale_pump_dump() -> str | None:
    payload = st.session_state.get("big_whale_pump_dump_payload")
    if not payload or not isinstance(payload, dict) or payload.get("error"):
        return payload.get("error") if isinstance(payload, dict) else None
    lines = [f"Scanned {payload.get('scanned_at', '')} boosts={payload.get('boosts_found', 0)}"]
    summ = payload.get("summary") or {}
    lines.append(
        f"pumped={summ.get('pumped_count')} big_trades={summ.get('big_trade_count')} "
        f"trades={summ.get('trade_signals', 0)} top={summ.get('top_pump_symbol')} {summ.get('top_pump_pct')}%"
    )
    for t in (payload.get("trade_recommendations") or [])[:8]:
        lines.append(
            f"  TRADE {t.get('symbol')} {t.get('verdict')} conf={t.get('confidence_pct')}% "
            f"SL -{t.get('sl_pct')}% TP +{t.get('tp_pct')}% 24h={t.get('pump_24h_pct')}%"
        )
    for key, label in (
        ("step1_pumped_24h", "PUMPED"),
        ("step2_big_trades", "BIG_VOL"),
        ("step4_accumulation", "ACCUM"),
        ("pre_pump_watchlist", "WATCH"),
    ):
        for p in (payload.get(key) or [])[:5]:
            lines.append(
                f"  {label} {p.get('symbol')} {p.get('chain_label')} "
                f"{p.get('pump_24h_pct')}% vol=${p.get('volume_24h_usd')} "
                f"liq=${p.get('liquidity_usd')} buy={p.get('buy_pressure_pct')}%"
            )
    return "\n".join(lines) if len(lines) > 1 else None


def _ctx_week52() -> str | None:
    results = st.session_state.get("w52_scan_results")
    if results is None:
        return None
    if isinstance(results, pd.DataFrame):
        return serialize_for_ask_ai(results)
    return serialize_for_ask_ai(results)


def _ctx_mega_analyser() -> str | None:
    results = st.session_state.get("mega_results")
    if not results:
        return None
    lines = [
        f"Market: {results.get('market')}",
        f"Tickers: {results.get('tickers')}",
    ]
    for s in (results.get("summaries") or [])[:25]:
        lines.append(
            f"{s.get('ticker', '?')} | {s.get('engine', '?')}: "
            f"{s.get('verdict', s.get('recommendation', ''))[:120]}"
        )
    return "\n".join(lines)


def _ctx_buy_sell_advisor() -> str | None:
    payload = st.session_state.get("buy_sell_advisor_payload")
    if not payload or not isinstance(payload, dict):
        return None
    lines: list[str] = []
    for ac, block in payload.items():
        if not isinstance(block, dict):
            continue
        lines.append(f"=== {ac.upper()} ===")
        for rec in block.get("recommendations") or []:
            lines.append(
                f"{rec.get('ticker')}: take={rec.get('take_trade')} "
                f"{rec.get('direction')} conf={rec.get('confidence_pct')}% "
                f"SL -{rec.get('sl_pct')}% TP +{rec.get('tp_pct')}% | {rec.get('verdict')}"
            )
    return "\n".join(lines) if lines else None


def _ctx_ticker_investigation() -> str | None:
    payload = st.session_state.get("ticker_investigation_payload")
    if not payload or not isinstance(payload, dict):
        return None
    lines: list[str] = []
    for ac, block in payload.items():
        if not isinstance(block, dict):
            continue
        lines.append(f"=== {ac.upper()} ===")
        for res in block.get("results") or []:
            ticker = res.get("ticker", "?")
            display = res.get("display_name") or ticker
            moves = ", ".join(
                f"{w.get('window')}:{w.get('change_pct')}%"
                for w in (res.get("price_windows") or [])[:4]
                if w.get("change_pct") is not None
            )
            imm = (res.get("sr") or {}).get("immediate") or {}
            setup = res.get("trade_setup") or {}
            take = setup.get("take_trade")
            lines.append(
                f"{display} ({ticker}) | moves [{moves}] | S/R bias {imm.get('sr_bias')} "
                f"breakout {imm.get('breakout_chance_pct')}% | news {res.get('news_count', 0)} | "
                f"analyst {len(res.get('analyst_calls') or [])} ({(res.get('analyst_consensus') or {}).get('consensus', '—')})"
            )
            if setup:
                lines.append(
                    f"  TRADE: {'TAKE ' + str(setup.get('direction', '')) if take else 'NO TRADE'} "
                    f"conf {setup.get('confidence_pct')}% SL -{setup.get('sl_pct')}% "
                    f"TP +{setup.get('tp_pct')}% — {setup.get('name', '')[:60]}"
                )
            for c in (res.get("analyst_calls") or [])[:2]:
                lines.append(
                    f"  ★ {c.get('action')} {c.get('call_type')} {c.get('brokerage')} "
                    f"target {c.get('price_target')} — {c.get('title', '')[:70]}"
                )
            for art in (res.get("news") or [])[:2]:
                lines.append(f"  • {art.get('source')}: {art.get('title', '')[:80]}")
    return "\n".join(lines) if lines else None


def _ctx_price_action() -> str | None:
    results = st.session_state.get("pa_all_results")
    if not results:
        return None
    return _summarize_pa_like_results(results)


def _ctx_find_sr() -> str | None:
    results = st.session_state.get("fsr_results")
    if not results:
        return None
    return _summarize_pa_like_results(results)


def _ctx_weak_strong_sr() -> str | None:
    results = st.session_state.get("wssr_results")
    if not results:
        return None
    parts = [f"Market: {st.session_state.get('wssr_results_market', 'N/A')}"]
    for key, d in list(results.items())[:16]:
        if d.get("timeframe") == "MTF" and d.get("mtf"):
            m = d["mtf"]
            p = m.get("trade_plan") or {}
            parts.append(
                f"{d.get('symbol')} MTF: {m.get('verdict')} align {m.get('mtf_alignment_pct')}% "
                f"SL -{p.get('sl_pct')}% TP +{p.get('tp_pct')}% conf {m.get('confidence')}%"
            )
        elif d.get("analysis"):
            a = d["analysis"]
            p = a.get("trade_plan") or {}
            ctx = a.get("sr_context") or {}
            cons = a.get("consolidation") or {}
            sd = a.get("supply_demand") or {}
            zone_note = ""
            if cons.get("is_consolidating"):
                zone_note += f" · consol {cons.get('bias', '—')}"
            if sd.get("active_zone") not in ("none", None, ""):
                zone_note += f" · {sd.get('active_zone')} {sd.get('bias', '')}"
            parts.append(
                f"{d.get('symbol')} {d.get('timeframe')}: {a.get('verdict')} "
                f"S/R {ctx.get('sr_bias')} conf {a.get('confidence')}% "
                f"SL -{p.get('sl_pct')}% TP +{p.get('tp_pct')}%{zone_note}"
            )
    return "\n".join(parts) if len(parts) > 1 else None


def _ctx_stf_shop() -> str | None:
    payload = st.session_state.get("stf_results")
    if not payload:
        return None
    rec = payload.get("recommendation") or {}
    parts = [
        f"ETF Shop 4.0 · effective ₹{rec.get('effective_capital', 0):,.0f} · "
        f"slot ₹{rec.get('slot_size', 0):,.0f} · deployed {rec.get('pct_deployed', 0)}%",
        f"Shop start {rec.get('shop_start_date', '—')} · ann {rec.get('annualized_return_pct', '—')}%",
        f"SIP locked: {', '.join(rec.get('sip_locked_symbols') or []) or 'none'}",
    ]
    buy = rec.get("buy_recommendation") or {}
    parts.append(
        f"Buy ({buy.get('buy_type', '—')}): {buy.get('action')} — {buy.get('reason', '')[:100]}"
    )
    ps = rec.get("primary_sell")
    if ps:
        parts.append(
            f"Sell FIFO: {ps.get('symbol')} +{ps.get('profit_pct')}% / ₹{ps.get('profit_inr')} "
            f"mode {ps.get('sell_mode')}"
        )
    for row in (rec.get("ranked_all") or [])[:5]:
        parts.append(
            f"  #{row.get('rank')} {row.get('symbol')} {row.get('pct_from_dma'):.2f}% vs 20 DMA"
        )
    for row in (rec.get("sip_candidates") or [])[:5]:
        parts.append(
            f"  SIP #{row.get('sip_rank')} {row.get('symbol')} "
            f"{row.get('fall_from_last_buy_pct'):.2f}% from last buy"
        )
    if rec.get("data_errors"):
        parts.append(f"Data errors: {', '.join(rec['data_errors'][:6])}")
    return "\n".join(parts)


def _ctx_pattern_breakout() -> str | None:
    results = st.session_state.get("pbo_results")
    if not results:
        return None
    return _summarize_pa_like_results(results)


def _ctx_fakeout_4h() -> str | None:
    results = st.session_state.get("f4h_results")
    if not results:
        return None
    parts = [f"Market: {st.session_state.get('f4h_results_market', 'N/A')}"]
    for tick, d in list(results.items())[:12]:
        if "error" in d:
            parts.append(f"{tick}: ERROR — {d['error']}")
            continue
        sc = (d.get("analysis") or {}).get("screener") or {}
        parts.append(
            f"{tick}: {sc.get('primary_phase', 'N/A')} — {sc.get('primary_label', '')} "
            f"(actionable={sc.get('actionable', False)})"
        )
    return "\n".join(parts)


def _ctx_fakeout_15m() -> str | None:
    results = st.session_state.get("f15m_results")
    if not results:
        return None
    parts = [f"Market: {st.session_state.get('f15m_results_market', 'N/A')}"]
    for tick, d in list(results.items())[:12]:
        if "error" in d:
            parts.append(f"{tick}: ERROR — {d['error']}")
            continue
        sc = (d.get("analysis") or {}).get("screener") or {}
        parts.append(
            f"{tick}: {sc.get('primary_phase', 'N/A')} — {sc.get('primary_label', '')} "
            f"(actionable={sc.get('actionable', False)})"
        )
    return "\n".join(parts)


def _ctx_mtf_hedging() -> str | None:
    payload = st.session_state.get("mtf_hedging_payload")
    if not payload:
        return None
    lines = [
        f"Market: {payload.get('market')}",
        f"Primary: {payload.get('primary_yf')} · Pair: {payload.get('pair_yf')}",
        f"Timeframes: {payload.get('timeframes')}",
        f"Portfolio value: {payload.get('portfolio_value')}",
    ]
    for role in payload.get("roles") or ("LTF", "MTF", "HTF"):
        block = (payload.get("strategies") or {}).get(role, {})
        tf = block.get("timeframe") or (payload.get("timeframes") or {}).get(role, "")
        lines.append(f"--- {role} ({tf}) ---")
        for key, res in block.items():
            if not res:
                continue
            if key == "beta":
                lines.append(f"  beta: β={res.get('beta')} hedge_units={res.get('hedge_units')}")
            elif key == "pairs":
                lines.append(f"  pairs: z={res.get('z_score')} ratio={res.get('hedge_ratio')} {res.get('signal')}")
            elif key == "crypto":
                lines.append(f"  crypto: corr={res.get('correlation')} ratio={res.get('hedge_ratio')}")
            elif key == "inverse_etf":
                lines.append(f"  inverse: {res.get('inverse_etf')} units={res.get('units_to_buy')}")
            elif key == "delta":
                lines.append(f"  delta: puts={res.get('put_contracts_buy')} strike={res.get('strike_price')}")
            elif key == "portfolio_risk":
                lines.append(
                    f"  risk: vol={res.get('ann_vol_pct')} sharpe={res.get('sharpe_ratio')} "
                    f"VaR={res.get('daily_var_95')}"
                )
    return "\n".join(lines)


def _ctx_mtf_scanner() -> str | None:
    results = st.session_state.get("mtf_results")
    if not results:
        return None
    parts = [f"Market: {st.session_state.get('mtf_results_market', 'N/A')}"]
    for tick, d in list(results.items())[:12]:
        if d.get("error"):
            parts.append(f"{tick}: ERROR — {d['error']}")
            continue
        conf = d.get("confluence") or {}
        best = d.get("best_setup") or {}
        parts.append(
            f"{tick}: {conf.get('verdict', 'N/A')} · avg {conf.get('avg_score', 0):.1f}/100 "
            f"· {conf.get('ready_setup_count', 0)} ready / {conf.get('watch_setup_count', 0)} watch "
            f"· best {best.get('timeframe', '—')} {best.get('status', '—')} "
            f"conf {best.get('setup_confidence', 0):.0f}% hold {best.get('hold_duration', '—')}"
        )
    return "\n".join(parts)


def _ctx_top_down_mtf() -> str | None:
    results = st.session_state.get("tdmtf_results")
    if not results:
        return None
    parts = [
        f"Market: {st.session_state.get('tdmtf_results_market', 'N/A')}",
        f"TFs: {st.session_state.get('tdmtf_htf_tf', '15m')} → "
        f"{st.session_state.get('tdmtf_mtf_tf', '5m')} → "
        f"{st.session_state.get('tdmtf_ltf_tf', '1m')}",
    ]
    for tick, d in list(results.items())[:12]:
        if d.get("error"):
            parts.append(f"{tick}: ERROR — {d['error']}")
            continue
        plan = d.get("trade_plan") or {}
        s1 = d.get("step1") or {}
        parts.append(
            f"{tick}: {d.get('phase', '—')} · {s1.get('bias', '—')} · "
            f"conf {d.get('confidence', 0):.0f}% · "
            f"SL -{plan.get('sl_pct', 0):.2f}% TP +{plan.get('tp_pct', 0):.2f}% · "
            f"hold {plan.get('hold_duration', '—')}"
        )
    return "\n".join(parts)


def _ctx_weekly_stoch_sweet_spot() -> str | None:
    results = st.session_state.get("wstoch_results")
    if not results:
        return None
    parts = [f"Market: {st.session_state.get('wstoch_results_market', 'N/A')}"]
    for tick, d in list(results.items())[:12]:
        if d.get("error"):
            parts.append(f"{tick}: ERROR — {d['error']}")
            continue
        m = d.get("metrics") or {}
        plan = d.get("trade_plan") or {}
        parts.append(
            f"{tick}: {d.get('phase', '—')} · K {d.get('k', 0):.0f} D {d.get('d', 0):.0f} · "
            f"conf {d.get('confidence', 0):.0f}% · vol {'Y' if d.get('vol_confirm') else 'N'} · "
            f"win {m.get('win_rate_pct', 0):.0f}% · ret {m.get('strategy_return_pct', 0):+.1f}% · "
            f"SL -{plan.get('sl_pct', 0):.2f}% TP +{plan.get('tp_pct', 0):.2f}%"
        )
    return "\n".join(parts)


def _ctx_velez_retracement() -> str | None:
    results = st.session_state.get("velez_results")
    if not results:
        return None
    market = st.session_state.get("velez_results_market", "")
    tf = st.session_state.get("velez_chart_tf", "5m")
    parts = [f"Market: {market}", f"Chart TF: {tf}", "Tickers:"]
    for tick, d in list(results.items())[:12]:
        if d.get("error"):
            parts.append(f"  {tick}: ERROR — {d['error']}")
            continue
        a = d.get("analysis") or {}
        plan = a.get("trade_plan") or {}
        parts.append(
            f"  {tick}: {a.get('phase', '—')} · {a.get('primary_label', '')[:80]}"
        )
        if plan:
            parts.append(
                f"    → {plan.get('scenario')} {plan.get('direction')} "
                f"SL -{plan.get('sl_pct', 0):.2f}% TP +{plan.get('tp_pct', 0):.2f}% "
                f"hold {plan.get('hold_duration', '—')}"
            )
    return "\n".join(parts)


def _ctx_kn_smart_rsi_mtf() -> str | None:
    results = st.session_state.get("kn_results")
    if not results:
        return None
    parts = [
        f"Market: {st.session_state.get('kn_results_market', 'N/A')}",
        f"Intraday TF: {st.session_state.get('kn_intraday_tf', '5m')}",
    ]
    for tick, d in list(results.items())[:12]:
        if d.get("error"):
            parts.append(f"{tick}: ERROR — {d['error']}")
            continue
        live = d.get("live") or {}
        plan = d.get("trade_plan") or {}
        parts.append(
            f"{tick}: {d.get('phase', '—')} · {d.get('master_trend', '—')} · "
            f"{live.get('signal', 'HOLD')} · RSI {live.get('rsi', 0):.0f} · "
            f"conf {d.get('confidence', 0):.0f}% · "
            f"SL -{plan.get('sl_pct', 0):.2f}% TP1 +{plan.get('tp_pct', 0):.2f}%"
        )
    return "\n".join(parts)


def _ctx_smart_wave_crypto() -> str | None:
    results = st.session_state.get("sw_results")
    if not results:
        return None
    parts = [
        f"Market: CoinDCX Futures",
        f"Primary TF: {st.session_state.get('sw_tf', '30m')}",
    ]
    for tick, d in list(results.items())[:12]:
        if d.get("error"):
            parts.append(f"{tick}: ERROR — {d['error']}")
            continue
        plan = d.get("trade_plan") or {}
        parts.append(
            f"{tick}: {d.get('phase', '—')} · {d.get('best_strategy', '—')} · "
            f"conf {d.get('confidence', 0):.0f}% · "
            f"MB {'Y' if d.get('mb_eligible') else 'N'} · "
            f"SL -{plan.get('sl_pct', 0):.2f}% TP +{plan.get('tp_pct', 0):.2f}%"
        )
    return "\n".join(parts)


def _ctx_elliott_wave() -> str | None:
    results = st.session_state.get("ew_all_results")
    if not results:
        return None
    return _summarize_pa_like_results(results)


def _ctx_top_bottom() -> str | None:
    results = st.session_state.get("tb_all_results")
    if not results:
        return None
    return _summarize_pa_like_results(results)


def _ctx_sentiment() -> str | None:
    cache = st.session_state.get("sentiment_df_cache") or {}
    if not cache:
        return None
    parts = [f"Market: {st.session_state.get('sentiment_analysis_market', 'N/A')}"]
    for tf, df in list(cache.items())[:3]:
        if isinstance(df, pd.DataFrame) and not df.empty:
            parts.append(f"--- {tf} ({len(df)} rows) ---")
            cols = [c for c in ["Ticker", "Score", "Rating", "Trade Signal", "RSI", "ADX"] if c in df.columns]
            parts.append(serialize_for_ask_ai(df[cols].head(25) if cols else df.head(25), limit=4000))
    return "\n".join(parts)


def _ctx_smc_options() -> str | None:
    if not st.session_state.get("smc_flow_loaded"):
        return None
    results = st.session_state.get("smc_flow_results") or []
    fii = st.session_state.get("smc_fii_dii") or {}
    lines = ["=== FII/DII ===", serialize_for_ask_ai(fii, limit=1500)]
    lines.append(f"=== SMC flow rows ({len(results)}) ===")
    for row in results[:20]:
        lines.append(
            f"{row.get('index', row.get('ticker', '?'))}: "
            f"bias={row.get('bias')} pcr={row.get('pcr')} "
            f"smc={row.get('smc', {}).get('structure', 'N/A')}"
        )
    return "\n".join(lines)


def _ctx_strategy_builder() -> str | None:
    run = st.session_state.get("current_run")
    if not run:
        indicators = st.session_state.get("indicators", [])
        rules_e = st.session_state.get("entry_rules", [])
        rules_x = st.session_state.get("exit_rules", [])
        if not indicators and not rules_e:
            return None
        return serialize_for_ask_ai({
            "indicators": indicators,
            "entry_rules": rules_e,
            "exit_rules": rules_x,
            "note": "No backtest run yet — strategy config only",
        })
    metrics = run.get("results", {}).get("metrics", {})
    return serialize_for_ask_ai({
        "ticker": run.get("ticker"),
        "timeframe": run.get("timeframe"),
        "market": run.get("market"),
        "strategy": run.get("strategy_name"),
        "metrics": metrics,
        "sl_pct": run.get("sl_pct"),
        "tp_pct": run.get("tp_pct"),
    })


def _ctx_multi_combo() -> str | None:
    rows = st.session_state.get("scan_results")
    if not rows:
        return None
    if isinstance(rows, pd.DataFrame):
        return serialize_for_ask_ai(rows.head(40))
    if isinstance(rows, list):
        return serialize_for_ask_ai(rows[:40])
    return serialize_for_ask_ai(rows)


def _ctx_screener() -> str | None:
    results = st.session_state.get("screener_results")
    if not results:
        return None
    parts = [f"Active screener: {st.session_state.get('scr_active_name', 'Custom')}"]
    for name, df in list(results.items())[:5]:
        if isinstance(df, pd.DataFrame) and not df.empty:
            parts.append(f"--- {name} ({len(df)} matches) ---")
            parts.append(serialize_for_ask_ai(df.head(20), limit=3000))
    return "\n".join(parts)


def _ctx_gap_scanner() -> str | None:
    df = st.session_state.get("gap_results_df")
    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        return None
    meta = {
        "market": st.session_state.get("gap_analysis_market"),
        "tickers": st.session_state.get("gap_scan_tickers"),
        "timeframes": st.session_state.get("gap_scan_timeframes"),
        "min_gap_pct": st.session_state.get("gap_scan_min_pct"),
    }
    return f"Scan config:\n{serialize_for_ask_ai(meta, limit=1500)}\n\nResults:\n{serialize_for_ask_ai(df.head(30))}"


def _ctx_swing_trading_st() -> str | None:
    payload = st.session_state.get("swing_trading_st_payload")
    if not payload or not isinstance(payload, dict):
        return None
    lines = [
        f"Market: {payload.get('market')} · Strategy: {payload.get('strategy')}",
        f"TAKE signals: {payload.get('entry_count', 0)}",
    ]
    for res in (payload.get("entries") or payload.get("results") or [])[:12]:
        ticker = res.get("ticker", "?")
        live = res.get("live") or {}
        if res.get("error"):
            lines.append(f"{ticker}: ERROR {res['error']}")
            continue
        lines.append(
            f"{ticker} {live.get('verdict')} conf={live.get('confidence_pct')}% "
            f"SL -{live.get('sl_pct')}% TP +{live.get('tp_pct')}% hold={live.get('hold_duration')} "
            f"entry={live.get('entry_price')} stop={live.get('stop_price')} target={live.get('target_price')}"
        )
        bt = res.get("backtest") or {}
        if bt and not bt.get("error"):
            lines.append(
                f"  BT pnl={bt.get('pnl_pct')}% trades={bt.get('total_trades')} win={bt.get('win_rate_pct')}%"
            )
    return "\n".join(lines)


def _ctx_swing_trading_st_mtf_mss() -> str | None:
    payload = st.session_state.get("swing_trading_st_mtf_mss_payload")
    if not payload or not isinstance(payload, dict):
        return None
    lines = [
        f"Market: {payload.get('market')}",
        f"MSS entries: {payload.get('entry_count', 0)} · Fakeout watch: {payload.get('watch_count', 0)}",
    ]
    for res in (payload.get("entries") or payload.get("results") or [])[:12]:
        ticker = res.get("ticker", "?")
        live = res.get("live") or {}
        if res.get("error"):
            lines.append(f"{ticker}: ERROR {res['error']}")
            continue
        lines.append(
            f"{ticker} {live.get('verdict')} conf={live.get('confidence_pct')}% "
            f"SL -{live.get('sl_pct')}% TP +{live.get('tp_pct')}% hold={live.get('hold_duration')} "
            f"PWH={res.get('current_pwh')} PWL={res.get('current_pwl')}"
        )
        fo = live.get("fakeout") or {}
        if fo:
            lines.append(f"  fakeout={fo.get('type')} date={fo.get('date')}")
        mss = live.get("mss")
        if mss:
            lines.append(f"  MSS {mss.get('direction')} entry={mss.get('entry_price')} stop={mss.get('stop_price')}")
    return "\n".join(lines)


def _ctx_swing_trading_st_supertrend() -> str | None:
    payload = st.session_state.get("swing_trading_st_supertrend_payload")
    if not payload or not isinstance(payload, dict):
        return None
    lines = [
        f"Market: {payload.get('market')} · Mode: {payload.get('mode')}",
        f"Action signals: {payload.get('entry_count', 0)} · Holds: {payload.get('hold_count', 0)}",
    ]
    for res in (payload.get("entries") or payload.get("results") or [])[:12]:
        ticker = res.get("ticker", "?")
        live = res.get("live") or {}
        if res.get("error"):
            lines.append(f"{ticker}: ERROR {res['error']}")
            continue
        lines.append(
            f"{ticker} {live.get('verdict')} signal={live.get('signal')} "
            f"trend={live.get('trend')} conf={live.get('confidence_pct')}% "
            f"SL -{live.get('sl_pct')}% TP +{live.get('tp_pct')}% hold={live.get('hold_duration')} "
            f"SMA={live.get('sma_10')} ST={live.get('supertrend')}"
        )
        bt = res.get("backtest") or {}
        if bt.get("total_trades"):
            lines.append(f"  BT trades={bt.get('total_trades')} win={bt.get('win_rate_pct')}%")
    return "\n".join(lines)


def _ctx_swing_trading_st_kiss() -> str | None:
    payload = st.session_state.get("swing_trading_st_kiss_payload")
    if not payload or not isinstance(payload, dict):
        return None
    lines = [
        f"Market: {payload.get('market')} · Exec TF: {payload.get('execution_tf')}",
        f"Entries: {payload.get('entry_count', 0)} · Watch: {payload.get('watch_count', 0)}",
    ]
    for res in (payload.get("entries") or payload.get("results") or [])[:12]:
        ticker = res.get("ticker", "?")
        live = res.get("live") or {}
        if res.get("error"):
            lines.append(f"{ticker}: ERROR {res['error']}")
            continue
        lines.append(
            f"{ticker} {live.get('verdict')} zone={live.get('zone')} HA={live.get('weekly_ha')} "
            f"conf={live.get('confidence_pct')}% SL -{live.get('sl_pct')}% TP +{live.get('tp_pct')}% "
            f"hold={live.get('hold_duration')}"
        )
    return "\n".join(lines)


def _ctx_swing_trading_st_ha_ema() -> str | None:
    payload = st.session_state.get("swing_trading_st_ha_ema_payload")
    if not payload or not isinstance(payload, dict):
        return None
    lines = [
        f"Market: {payload.get('market')} · TF: {payload.get('execution_tf')}",
        f"Entries: {payload.get('entry_count', 0)} · Watch: {payload.get('watch_count', 0)}",
    ]
    for res in (payload.get("entries") or payload.get("results") or [])[:12]:
        ticker = res.get("ticker", "?")
        live = res.get("live") or {}
        if res.get("error"):
            lines.append(f"{ticker}: ERROR {res['error']}")
            continue
        lines.append(
            f"{ticker} {live.get('verdict')} bias={live.get('market_bias')} "
            f"opt={live.get('option_hint')} conf={live.get('confidence_pct')}% "
            f"SL -{live.get('sl_pct')}% TP +{live.get('tp_pct')}% hold={live.get('hold_duration')}"
        )
    return "\n".join(lines)


def _ctx_intraday_alpha_945() -> str | None:
    payload = st.session_state.get("intraday_alpha_945_payload")
    if not payload or not isinstance(payload, dict):
        return None
    lines = [
        f"Market: {payload.get('market')} · Scan: {payload.get('scan_time_ist', '09:45')} IST",
        f"Passes: {payload.get('entry_count', 0)} · Watch: {payload.get('watch_count', 0)}",
    ]
    for res in (payload.get("entries") or payload.get("results") or [])[:12]:
        ticker = res.get("ticker", "?")
        live = res.get("live") or {}
        if res.get("error"):
            lines.append(f"{ticker}: ERROR {res['error']}")
            continue
        f = live.get("filters") or {}
        lines.append(
            f"{ticker} {live.get('verdict')} conf={live.get('confidence_pct')}% "
            f"SL -{live.get('sl_pct')}% TP +{live.get('tp_pct')}% hold={live.get('hold_duration')} "
            f"day%={f.get('pct_change')} mcap={res.get('mcap_cr')}"
        )
    return "\n".join(lines)


def _ctx_smc_mtf_day_plan() -> str | None:
    payload = st.session_state.get("smc_mtf_day_plan_payload")
    if not payload or not isinstance(payload, dict):
        return None
    lines = [
        f"Market: {payload.get('market')} · "
        f"HTF={payload.get('htf_tf')} MTF={payload.get('mtf_tf')} LTF={payload.get('ltf_tf')}",
        f"Entries: {payload.get('entry_count', 0)} · Watch: {payload.get('watch_count', 0)}",
    ]
    for res in (payload.get("entries") or payload.get("results") or [])[:12]:
        ticker = res.get("ticker", "?")
        live = res.get("live") or {}
        if res.get("error"):
            lines.append(f"{ticker}: ERROR {res['error']}")
            continue
        lines.append(
            f"{ticker} {live.get('verdict')} trend={live.get('htf_trend')} phase={live.get('phase')} "
            f"conf={live.get('confidence_pct')}% SL -{live.get('sl_pct')}% TP +{live.get('tp_pct')}% "
            f"hold={live.get('hold_duration')}"
        )
    return "\n".join(lines)


def _ctx_smc_golden_bullet() -> str | None:
    payload = st.session_state.get("smc_golden_bullet_payload")
    if not payload or not isinstance(payload, dict):
        return None
    lines = [
        f"Market: {payload.get('market')} · Exec: {payload.get('execution_tf')} · HTF: {payload.get('htf_tf')}",
        f"Entries: {payload.get('entry_count', 0)} · Watch: {payload.get('watch_count', 0)}",
    ]
    for res in (payload.get("entries") or payload.get("results") or [])[:12]:
        ticker = res.get("ticker", "?")
        live = res.get("live") or {}
        if res.get("error"):
            lines.append(f"{ticker}: ERROR {res['error']}")
            continue
        lines.append(
            f"{ticker} {live.get('verdict')} htf={live.get('htf_bias')} killzone={live.get('killzone')} "
            f"phase={live.get('phase')} liq={live.get('liquidity_level')} "
            f"conf={live.get('confidence_pct')}% SL -{live.get('sl_pct')}% TP +{live.get('tp_pct')}% "
            f"hold={live.get('hold_duration')}"
        )
    return "\n".join(lines)


def _ctx_smc_weekly_sweep_cisd() -> str | None:
    payload = st.session_state.get("smc_weekly_sweep_cisd_payload")
    if not payload or not isinstance(payload, dict):
        return None
    lines = [
        f"Market: {payload.get('market')} · LTF: {payload.get('execution_tf')}",
        f"Entries: {payload.get('entry_count', 0)} · Await CISD: {payload.get('watch_count', 0)}",
    ]
    for res in (payload.get("entries") or payload.get("results") or [])[:12]:
        ticker = res.get("ticker", "?")
        live = res.get("live") or {}
        if res.get("error"):
            lines.append(f"{ticker}: ERROR {res['error']}")
            continue
        lines.append(
            f"{ticker} {live.get('verdict')} phase={live.get('phase')} "
            f"PWH={res.get('prev_weekly_high') or live.get('prev_weekly_high')} "
            f"PWL={res.get('prev_weekly_low') or live.get('prev_weekly_low')} "
            f"conf={live.get('confidence_pct')}% SL -{live.get('sl_pct')}% TP +{live.get('tp_pct')}% "
            f"hold={live.get('hold_duration')}"
        )
    return "\n".join(lines)


def _ctx_smc_cisd() -> str | None:
    payload = st.session_state.get("smc_cisd_payload")
    if not payload or not isinstance(payload, dict):
        return None
    lines = [
        f"Market: {payload.get('market')} · Exec: {payload.get('execution_tf')} · Bias: {payload.get('bias_tf')}",
        f"Entries: {payload.get('entry_count', 0)} · Await CISD: {payload.get('watch_count', 0)}",
    ]
    for res in (payload.get("entries") or payload.get("results") or [])[:12]:
        ticker = res.get("ticker", "?")
        live = res.get("live") or {}
        if res.get("error"):
            lines.append(f"{ticker}: ERROR {res['error']}")
            continue
        lines.append(
            f"{ticker} {live.get('verdict')} phase={live.get('phase')} cisd={live.get('cisd_level')} "
            f"conf={live.get('confidence_pct')}% SL -{live.get('sl_pct')}% TP +{live.get('tp_pct')}% "
            f"hold={live.get('hold_duration')} htf={live.get('htf_bias')}"
        )
    return "\n".join(lines)


def _ctx_intraday_vwap_fade() -> str | None:
    payload = st.session_state.get("intraday_vwap_fade_payload")
    if not payload or not isinstance(payload, dict):
        return None
    lines = [
        f"Market: {payload.get('market')} · Exec: {payload.get('execution_tf')} · Bias: {payload.get('bias_tf')}",
        f"Entries: {payload.get('entry_count', 0)} · Watch: {payload.get('watch_count', 0)} · Avoid: {payload.get('avoid_count', 0)}",
    ]
    for res in (payload.get("entries") or payload.get("results") or [])[:12]:
        ticker = res.get("ticker", "?")
        live = res.get("live") or {}
        if res.get("error"):
            lines.append(f"{ticker}: ERROR {res['error']}")
            continue
        lines.append(
            f"{ticker} {live.get('verdict')} phase={live.get('phase')} vwap={live.get('vwap')} "
            f"conf={live.get('confidence_pct')}% SL -{live.get('sl_pct')}% TP +{live.get('tp_pct')}% "
            f"hold={live.get('hold_duration')}"
        )
    return "\n".join(lines)


def _ctx_intraday_fib_945() -> str | None:
    payload = st.session_state.get("intraday_fib_945_payload")
    if not payload or not isinstance(payload, dict):
        return None
    lines = [
        f"Market: {payload.get('market')} · TF: {payload.get('execution_tf')}",
        f"Entries: {payload.get('entry_count', 0)} · Watch: {payload.get('watch_count', 0)}",
    ]
    for res in (payload.get("entries") or payload.get("results") or [])[:12]:
        ticker = res.get("ticker", "?")
        live = res.get("live") or {}
        if res.get("error"):
            lines.append(f"{ticker}: ERROR {res['error']}")
            continue
        lines.append(
            f"{ticker} {live.get('verdict')} bias={live.get('bias')} fib50={live.get('fib_50')} "
            f"conf={live.get('confidence_pct')}% SL -{live.get('sl_pct')}% TP +{live.get('tp_pct')}% "
            f"hold={live.get('hold_duration')}"
        )
    return "\n".join(lines)


def _ctx_scalp_rectangle() -> str | None:
    payload = st.session_state.get("scalp_rectangle_payload")
    if not payload or not isinstance(payload, dict):
        return None
    lines = [
        f"Market: {payload.get('market')} · TF: {payload.get('execution_tf', '1m')}",
        f"Entries: {payload.get('entry_count', 0)} · Rectangle armed: {payload.get('watch_count', 0)}",
    ]
    for res in (payload.get("entries") or payload.get("results") or [])[:12]:
        ticker = res.get("ticker", "?")
        live = res.get("live") or {}
        if res.get("error"):
            lines.append(f"{ticker}: ERROR {res['error']}")
            continue
        lines.append(
            f"{ticker} {live.get('verdict')} phase={live.get('phase')} "
            f"rect={live.get('rect_bottom')}–{live.get('rect_top')} "
            f"conf={live.get('confidence_pct')}% SL -{live.get('sl_pct')}% TP +{live.get('tp_pct')}% "
            f"hold={live.get('hold_duration')}"
        )
    return "\n".join(lines)


def _ctx_seasonality() -> str | None:
    results = st.session_state.get("seasonality_results")
    if not results:
        return None
    parts = [
        f"Asset: {st.session_state.get('seasonality_asset_type')}",
        f"Lookback: {st.session_state.get('seasonality_lookback')} years",
    ]
    for ticker, data in list(results.items())[:8]:
        parts.append(f"--- {ticker} ---")
        if isinstance(data, dict):
            bt = data.get("bt_metrics") or data.get("metrics")
            if bt:
                parts.append(serialize_for_ask_ai(bt, limit=800))
    return "\n".join(parts)


def _ctx_demo_trading(market_type: str) -> str | None:
    from app.market_pulse.database import get_demo_trades
    from app.market_pulse.demo_trading import get_logged_in_mobile, compute_trade_pnl, fetch_latest_price
    from app.market_pulse.groww_auth import get_active_groww_token

    mobile = get_logged_in_mobile()
    if not mobile:
        return None
    open_trades = get_demo_trades(mobile, market_type=market_type, status="OPEN")
    closed = get_demo_trades(mobile, market_type=market_type, status="CLOSED")[:10]
    if not open_trades and not closed:
        return None
    groww_token = get_active_groww_token()
    exchange = st.session_state.get("tb_groww_ex", "NSE")
    lines = [f"Demo portfolio ({market_type}): {len(open_trades)} open, {len(closed)} recent closed"]
    for t in open_trades[:15]:
        quote = fetch_latest_price(t["ticker"], t.get("market_label", ""), t["timeframe"], groww_token, exchange)
        px = quote.get("price") if isinstance(quote, dict) else quote
        pnl = compute_trade_pnl(t, px)
        lines.append(
            f"OPEN {t['ticker']} {t['direction']} entry={t['entry_price']} "
            f"pnl={pnl.get('pnl_pct', 0):+.2f}%"
        )
    for t in closed[:5]:
        lines.append(f"CLOSED {t['ticker']} {t['direction']} pnl={t.get('pnl_pct', 'N/A')}")
    return "\n".join(lines)


def store_heatmap_results(
    data_list: list[dict],
    *,
    market: str,
    timeframe: str,
    exchange: str = "",
    mode: str = "",
) -> None:
    """Persist last heatmap scan for Ask AI (heatmap renders inside @st.fragment)."""
    if not data_list:
        return
    st.session_state["heatmap_last_data"] = {
        "market": market,
        "timeframe": timeframe,
        "exchange": exchange,
        "mode": mode,
        "rows": data_list,
        "advances": sum(1 for x in data_list if (x.get("change") or 0) > 0),
        "declines": sum(1 for x in data_list if (x.get("change") or 0) < 0),
    }


def _ctx_heatmap() -> str | None:
    payload = st.session_state.get("heatmap_last_data")
    if not payload:
        market = st.session_state.get("heatmap_market_selector", "")
        return f"Heatmap — no scan loaded yet. Selected market: {market}" if market else None
    rows = payload.get("rows") or []
    lines = [
        "=== LIVE HEATMAP SCAN ===",
        f"Market: {payload.get('market')} | Timeframe: {payload.get('timeframe')}",
        f"Exchange: {payload.get('exchange') or 'N/A'} | Mode: {payload.get('mode') or 'N/A'}",
        f"Advances: {payload.get('advances')} | Declines: {payload.get('declines')} | "
        f"Symbols: {len(rows)}",
        "",
        "=== ALL SYMBOLS (sorted by % change) ===",
    ]
    for r in sorted(rows, key=lambda x: x.get("change", 0), reverse=True)[:50]:
        ch = r.get("change", 0)
        lines.append(
            f"{r.get('ticker')}: price={r.get('price')} change={ch:+.2f}% "
            f"vol_chg={r.get('vol_change', 0):+.0f}% "
            f"S={r.get('support', '—')} R={r.get('resistance', '—')} "
            f"PCR={r.get('pcr', '—')}"
        )
    return "\n".join(lines)


def _ctx_strategy_encyclopedia() -> str | None:
    from app.market_pulse.presets import get_presets_by_category
    from app.market_pulse.strategy_encyclopedia_guide import HUB_SECTIONS

    lines = [
        "=== STRATEGY ENCYCLOPEDIA ===",
        "Application guide covers: 8 hubs, workflows (pre-market, scalp, swing, backtest, custom strategy, crypto, F&O, mega analyser), when-to-use matrix.",
        f"Hub sections documented: {sum(len(v) for v in HUB_SECTIONS.values())} across {len(HUB_SECTIONS)} hubs.",
        "",
    ]

    enc_market = st.session_state.get("enc_market", "Groww (India Stocks)")
    categories = get_presets_by_category(enc_market)
    lines.append(f"=== PRESET CATALOG — {enc_market} ===")
    n = 0
    for cat_name, cat_presets in categories.items():
        lines.append(f"\n--- {cat_name} ---")
        for strat_name, strat_data in cat_presets.items():
            if n >= 40:
                lines.append("... (more strategies in encyclopedia preset catalog)")
                return "\n".join(lines)
            inds = ", ".join(i["type"].upper() for i in strat_data.get("indicators", [])[:5])
            lines.append(
                f"{strat_name}: TF={strat_data.get('recommended_timeframe')} "
                f"SL={strat_data.get('recommended_sl')}% TP={strat_data.get('recommended_tp')}% "
                f"Indicators=[{inds}] — {strat_data.get('description', '')[:100]}"
            )
            n += 1
    return "\n".join(lines) if lines else None


def _ctx_saved_strategies() -> str | None:
    from app.market_pulse.database import get_strategies_by_mobile
    from app.market_pulse.demo_trading import get_logged_in_mobile

    mobile = get_logged_in_mobile()
    if not mobile:
        return None
    saved = get_strategies_by_mobile(mobile)
    if not saved:
        return None
    name = st.session_state.get("inspect_selected_strat")
    lines = [f"Archived strategies: {len(saved)}"]
    if name:
        strat = next((s for s in saved if s["name"] == name), None)
        if strat:
            try:
                metrics = json.loads(strat["metrics"])
            except (json.JSONDecodeError, TypeError):
                metrics = {}
            lines.append(serialize_for_ask_ai({
                "name": strat["name"],
                "ticker": strat.get("ticker"),
                "timeframe": strat.get("timeframe"),
                "market": strat.get("market"),
                "metrics": metrics,
            }, limit=6000))
    return "\n".join(lines)


def _ctx_pump_dump_predictor() -> str | None:
    snap = st.session_state.get("pdp_ask_ai_snapshot")
    if snap:
        return snap
    rows = st.session_state.get("pdp_scan_rows") or []
    if not rows:
        return None
    lines = ["=== PUMP & DUMP SCANNER ===", f"Results: {len(rows)}", ""]
    for r in rows[:25]:
        lines.append(
            f"{r.get('symbol')} {r.get('side')}: score {r.get('score')} — {r.get('verdict')} "
            f"({r.get('signals')} signals) HTF {r.get('htf_trend')}"
        )
    return "\n".join(lines)


def _ctx_strategy_scheduler() -> str | None:
    groww = st.session_state.get("sts_groww_results") or []
    crypto = st.session_state.get("sts_crypto_results") or []
    results = groww + crypto
    if not results:
        results = st.session_state.get("sts_results") or []
    if not results:
        g_cfg = st.session_state.get("sts_groww_scan_config") or {}
        c_cfg = st.session_state.get("sts_crypto_scan_config") or {}
        if not g_cfg and not c_cfg:
            return None
        return (
            "Strategy Scheduler — no scan results yet.\n"
            f"Groww configured: {len(g_cfg.get('tickers', []))} tickers · "
            f"{len(g_cfg.get('strategies', []))} strategies\n"
            f"Crypto configured: {len(c_cfg.get('tickers', []))} pairs · "
            f"{len(c_cfg.get('strategies', []))} strategies"
        )
    trades = [r for r in results if r.get("signal_type") == "trade"]
    lines = [
        "=== STRATEGY SCHEDULER — LATEST SCAN ===",
        f"Total combos: {len(results)} | Trade suggestions: {len(trades)}",
        f"Last run: {st.session_state.get('sts_last_run', '—')}",
        "",
    ]
    for r in results[:40]:
        tp = r.get("trade_plan") or {}
        lines.append(
            f"{r.get('ticker')} | {r.get('timeframe')} | {r.get('strategy', '')[:36]}\n"
            f"  Market: {r.get('market', '—')} | Verdict: {r.get('verdict')} | "
            f"Score: {r.get('score')}/10 | Conf: {tp.get('confidence_pct')}%\n"
            f"  SL: -{tp.get('stop_loss_pct')}% | TP: +{tp.get('take_profit_pct')}% | "
            f"Hold: {(tp.get('holding_period') or '—')[:40]}\n"
            f"  {r.get('summary', '')[:160]}"
        )
    return "\n".join(lines)


def _ctx_ai_strategy_creator() -> str | None:
    parsed = st.session_state.get("ai_temp_parsed_strategy")
    meta = st.session_state.get("ai_temp_metadata")
    draft = st.session_state.get("ai_strategy_text_input", "")
    parts = []
    if draft:
        parts.append(f"Draft strategy text:\n{draft[:4000]}")
    if parsed:
        parts.append("Parsed strategy:\n" + serialize_for_ask_ai(parsed, limit=6000))
    if meta:
        parts.append("Metadata:\n" + serialize_for_ask_ai(meta, limit=1500))
    return "\n\n".join(parts) if parts else None


_SYNC_BUILDERS: dict[str, Any] = {
    "command_outlook": _ctx_command_outlook,
    "mega_analyser": _ctx_mega_analyser,
    "buy_sell_advisor": _ctx_buy_sell_advisor,
    "ticker_investigation": _ctx_ticker_investigation,
    "news_scanner": _ctx_news_scanner,
    "nifty_breadth": _ctx_nifty_breadth,
    "nifty_monthly": _ctx_nifty_monthly,
    "nifty_gainers_losers": _ctx_nifty_gainers_losers,
    "market_gainers_losers": _ctx_market_gainers_losers,
    "stock_price_rotation": _ctx_stock_price_rotation,
    "stock_price_rotation_us": _ctx_stock_price_rotation_us,
    "stock_price_rotation_crypto": _ctx_stock_price_rotation_crypto,
    "commodity_screener": _ctx_commodity_screener,
    "accurate_strategy": _ctx_accurate_strategy,
    "pump_dump_breakout": _ctx_pump_dump_breakout,
    "big_whale_pump_dump": _ctx_big_whale_pump_dump,
    "sector_rotation": _ctx_sector_rotation,
    "sector_rotation_intraday": _ctx_sector_rotation_intraday,
    "sector_rotation_us": _ctx_sector_rotation_us,
    "sector_rotation_us_intraday": _ctx_sector_rotation_us_intraday,
    "sector_rotation_crypto": _ctx_sector_rotation_crypto,
    "sector_rotation_crypto_intraday": _ctx_sector_rotation_crypto_intraday,
    "opposite_hedge_mtf": _ctx_opposite_hedge_mtf,
    "mtf_intraday_bias": _ctx_mtf_intraday_bias,
    "mtf_intraday_bias_crypto": _ctx_mtf_intraday_bias_crypto,
    "week52": _ctx_week52,
    "heatmap": _ctx_heatmap,
    "price_action": _ctx_price_action,
    "find_sr": _ctx_find_sr,
    "weak_strong_sr": _ctx_weak_strong_sr,
    "stf_shop": _ctx_stf_shop,
    "pattern_breakout": _ctx_pattern_breakout,
    "fakeout_4h": _ctx_fakeout_4h,
    "fakeout_15m": _ctx_fakeout_15m,
    "mtf_scanner": _ctx_mtf_scanner,
    "mtf_hedging": _ctx_mtf_hedging,
    "top_down_mtf": _ctx_top_down_mtf,
    "weekly_stoch_sweet_spot": _ctx_weekly_stoch_sweet_spot,
    "kn_smart_rsi_mtf": _ctx_kn_smart_rsi_mtf,
    "velez_retracement": _ctx_velez_retracement,
    "smart_wave_crypto": _ctx_smart_wave_crypto,
    "elliott_wave": _ctx_elliott_wave,
    "sentiment": _ctx_sentiment,
    "top_bottom": _ctx_top_bottom,
    "smc_options": _ctx_smc_options,
    "strategy_builder": _ctx_strategy_builder,
    "saved_strategies": _ctx_saved_strategies,
    "ai_strategy_creator": _ctx_ai_strategy_creator,
    "multi_combo": _ctx_multi_combo,
    "screener": _ctx_screener,
    "gap_scanner": _ctx_gap_scanner,
    "seasonality": _ctx_seasonality,
    "swing_trading_st": _ctx_swing_trading_st,
    "swing_trading_st_mtf_mss": _ctx_swing_trading_st_mtf_mss,
    "swing_trading_st_supertrend": _ctx_swing_trading_st_supertrend,
    "swing_trading_st_kiss": _ctx_swing_trading_st_kiss,
    "swing_trading_st_ha_ema": _ctx_swing_trading_st_ha_ema,
    "intraday_alpha_945": _ctx_intraday_alpha_945,
    "intraday_fib_945": _ctx_intraday_fib_945,
    "intraday_vwap_fade": _ctx_intraday_vwap_fade,
    "scalp_rectangle": _ctx_scalp_rectangle,
    "smc_cisd": _ctx_smc_cisd,
    "smc_weekly_sweep_cisd": _ctx_smc_weekly_sweep_cisd,
    "smc_mtf_day_plan": _ctx_smc_mtf_day_plan,
    "smc_golden_bullet": _ctx_smc_golden_bullet,
    "strategy_encyclopedia": _ctx_strategy_encyclopedia,
    "strategy_scheduler": _ctx_strategy_scheduler,
    "pump_dump_predictor": _ctx_pump_dump_predictor,
}


def sync_ask_ai_context(section_id: str, **kwargs: Any) -> None:
    """Refresh Ask AI context — prefers fragment snapshot, then live session builders."""
    clear_ask_ai_context(section_id)

    display = st.session_state.get(f"ask_ai_display_{section_id}")
    if display:
        register_ask_ai_context(section_id, display, label="On-screen analysis output")

    if section_id == "demo_india":
        ctx = _ctx_demo_trading("india")
    elif section_id == "demo_crypto":
        ctx = _ctx_demo_trading("crypto")
    else:
        builder = _SYNC_BUILDERS.get(section_id)
        ctx = builder() if builder else None
    if ctx:
        register_ask_ai_context(section_id, ctx, label="Session analysis data")

    extra = kwargs.get("extra")
    if extra:
        register_ask_ai_context(section_id, extra, label=kwargs.get("extra_label", "Additional context"))


def snapshot_section_for_ask_ai(section_id: str) -> None:
    """Build context from session state and store as the section's display snapshot."""
    if section_id == "demo_india":
        ctx = _ctx_demo_trading("india")
    elif section_id == "demo_crypto":
        ctx = _ctx_demo_trading("crypto")
    else:
        builder = _SYNC_BUILDERS.get(section_id)
        ctx = builder() if builder else None
    if ctx:
        publish_section_display(section_id, ctx)
