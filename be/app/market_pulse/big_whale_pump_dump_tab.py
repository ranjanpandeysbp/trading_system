"""
big_whale_pump_dump_tab.py
--------------------------
Market Pulse — Big Whale Pump & Dump (DexScreener + explorer workflow).
"""

from __future__ import annotations

from contextlib import nullcontext

import pandas as pd
from app.market_pulse.big_whale_pump_dump_engine import (
    CHAIN_META,
    WhaleScanConfig,
    run_big_whale_scan,
)
from app.market_pulse.news_scanner import _render_news_scanner_styles

_PREFIX = "big_whale"
_PAYLOAD_KEY = "big_whale_pump_dump_payload"

STRATEGY_EXPLANATION = """
### Big Whale Pump & Dump — Video Playbook

Find cryptocurrency coins **before** a major pump by following on-chain capital flow:

| Step | Action | This app |
|------|--------|----------|
| **1 · Track whales** | Monitor large wallets; look back **24h** for the biggest pumps | DexScreener boosted + DEX pairs filtered by **24h % change** |
| **2 · Scan big trades** | On pumped coins, filter **largest trades** | Ranks top **24h volume** pairs (proxy for whale-sized flow) + DexScreener pair link |
| **3 · Linked wallets** | Trace wallets from large trades via **Solscan** / **BscScan** | Explorer links on each token (manual trace on Holders / Transfers) |
| **4 · Token transfers** | See which **new coins** those wallets are accumulating | **Accumulation** list — buy pressure + moderate pump + volume |
| **5 · Liquidity** | Track **liquidity inflows** — capital gathering before pump | **Liquidity leaders** ranked by USD liquidity + volume |

**Trade output:** **BUY / SELL** with **confidence %**, **SL %**, **TP %** (DEX meme defaults ~3% / 15%, adjusted for liquidity & pump extension).

---

**Data source:** [DexScreener](https://dexscreener.com) public API (Solana, BNB Chain, optional Base/Ethereum).

**Limits:** Free APIs do not expose individual wallet addresses — steps 3–4 use **explorer deep-links** for manual research (as in the video). CEX whales (CoinDCX) are not on-chain; use DEX-focused meme / micro-cap workflow.

> **Disclaimer:** Pump-and-dump hunting is extremely high risk. Paid boosts ≠ quality.  
> Thin pools, rug pulls, and stop hunts are common. **Research tool only — NOT FINANCIAL ADVICE.**
"""


def _render_strategy_explanation() -> None:
    with st.expander("📖 Strategy explanation — Big Whale Pump & Dump", expanded=False):
        st.markdown(STRATEGY_EXPLANATION)


def _trade_badge(setup: dict | None) -> str:
    if not setup:
        return "⚪ WAIT"
    if setup.get("take_trade") and setup.get("direction") == "LONG":
        return "🟢 BUY"
    if setup.get("take_trade") and setup.get("direction") == "SHORT":
        return "🔴 SELL"
    d = setup.get("direction", "WAIT")
    if d == "LONG":
        return "👁️ WATCH BUY"
    if d == "SHORT":
        return "👁️ WATCH SELL"
    return "⚪ WAIT"


def _render_trade_setup(setup: dict | None) -> None:
    if not setup:
        return
    badge = _trade_badge(setup)
    conf = setup.get("confidence_pct", 0)
    sl = setup.get("sl_pct", 0)
    tp = setup.get("tp_pct", 0)
    if setup.get("take_trade"):
        st.success(
            f"**{badge}** · conf **{conf:.0f}%** · SL **-{sl:.2f}%** · TP **+{tp:.2f}%**"
            + (f" · R:R **{setup.get('rr_ratio')}**" if setup.get("rr_ratio") else "")
        )
    else:
        st.caption(
            f"{badge} · conf {conf:.0f}% · ref SL -{sl:.2f}% · TP +{tp:.2f}%"
        )
    for r in setup.get("reasons") or []:
        st.caption(f"· {r}")


def _rows_table(items: list[dict], columns: list[str]) -> None:
    if not items:
        st.caption("None matched this step.")
        return
    rows = []
    for p in items:
        row = {c: p.get(c, "—") for c in columns}
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _render_token_cards(items: list[dict], title: str) -> None:
    if title:
        st.markdown(f"##### {title}")
    if not items:
        st.caption("No matches.")
        return
    for p in items[:8]:
        sym = p.get("symbol", "?")
        chain = p.get("chain_label", p.get("chain_id", ""))
        pump = p.get("pump_24h_pct", 0)
        vol = p.get("volume_24h_usd", 0)
        liq = p.get("liquidity_usd", 0)
        st.markdown(
            f"**{sym}** · {chain} · 24h **{pump:+.1f}%** · "
            f"Vol **${vol:,.0f}** · Liq **${liq:,.0f}** · "
            f"Buy pressure **{p.get('buy_pressure_pct', 0)}%** · "
            f"Whale score **{p.get('whale_activity_score', 0)}**"
        )
        _render_trade_setup(p.get("trade_setup"))
        links = p.get("linked_actions") or []
        if p.get("dexscreener_url"):
            st.markdown(f"- [DexScreener pair]({p['dexscreener_url']})")
        if p.get("token_explorer_url"):
            st.markdown(f"- [Explorer — holders & transfers]({p['token_explorer_url']})")
        note = p.get("big_trade_note") or p.get("accumulation_note") or p.get("verdict_note") or p.get("explorer_note")
        if note:
            st.caption(note)
        st.markdown("---")


def _render_results(payload: dict) -> None:
    if payload.get("error"):
        st.error(payload["error"])
        return

    summ = payload.get("summary") or {}
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("24h pumped", summ.get("pumped_count", 0))
    with c2:
        st.metric("Big trade flags", summ.get("big_trade_count", 0))
    with c3:
        st.metric("Accumulation", summ.get("accumulation_count", 0))
    with c4:
        top = summ.get("top_pump_symbol")
        st.metric("Top pump", f"{top} {summ.get('top_pump_pct', 0):+.0f}%" if top else "—")

    st.caption(
        f"Scanned **{payload.get('scanned_tokens', 0)}** tokens · "
        f"**{payload.get('boosts_found', 0)}** boosts · {payload.get('scanned_at', '')}"
    )

    trades = payload.get("trade_recommendations") or []
    st.markdown("##### 🎯 Trade signals — BUY / SELL (confidence · SL% · TP%)")
    if not trades:
        st.info("No TAKE TRADE signals above confidence threshold — review WATCH setups below.")
    else:
        trade_rows = []
        for t in trades:
            trade_rows.append({
                "Symbol": t.get("symbol"),
                "Chain": t.get("chain_label"),
                "Signal": t.get("verdict"),
                "Conf %": f"{t.get('confidence_pct', 0):.0f}",
                "SL %": f"-{t.get('sl_pct', 0):.2f}",
                "TP %": f"+{t.get('tp_pct', 0):.2f}",
                "R:R": t.get("rr_ratio", "—"),
                "24h %": f"{t.get('pump_24h_pct', 0):+.1f}",
                "Liq $": f"{t.get('liquidity_usd', 0):,.0f}",
            })
        st.dataframe(pd.DataFrame(trade_rows), hide_index=True, width="stretch")
        with st.expander("Trade rationale", expanded=False):
            for t in trades[:10]:
                st.markdown(
                    f"**{t.get('symbol')}** ({t.get('chain_label')}) — {t.get('verdict')} "
                    f"conf {t.get('confidence_pct')}% · SL -{t.get('sl_pct')}% TP +{t.get('tp_pct')}%"
                )
                for r in t.get("reasons") or []:
                    st.caption(f"  · {r}")

    st.markdown("##### ① 24h pumped tokens (whale / trending flow)")
    _render_token_cards(payload.get("step1_pumped_24h") or [], "")

    st.markdown("##### ② Largest trades (24h volume leaders on pumped names)")
    _render_token_cards(payload.get("step2_big_trades") or [], "")

    st.markdown("##### ④ Whale accumulation candidates (buy pressure + new flow)")
    _render_token_cards(payload.get("step4_accumulation") or [], "")

    st.markdown("##### ⑤ Liquidity inflow leaders (capital gathering)")
    _render_token_cards(payload.get("step5_liquidity_inflows") or [], "")

    watch = payload.get("pre_pump_watchlist") or []
    if watch:
        st.markdown("##### 🐋 Pre-pump watchlist (confluence)")
        _render_token_cards(watch, "")

    with st.expander("📋 Full table — pumped 24h", expanded=False):
        cols = [
            "symbol", "chain_label", "pump_24h_pct", "volume_24h_usd", "liquidity_usd",
            "buy_pressure_pct", "whale_activity_score", "is_boosted",
        ]
        rows = []
        for p in payload.get("step1_pumped_24h") or []:
            row = {c: p.get(c, "—") for c in cols}
            ts = p.get("trade_setup") or {}
            row["Signal"] = ts.get("verdict", "—")
            row["Conf %"] = ts.get("confidence_pct", "—")
            row["SL %"] = ts.get("sl_pct", "—")
            row["TP %"] = ts.get("tp_pct", "—")
            rows.append(row)
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def render_big_whale_pump_dump_tab(get_logged_in_mobile=None) -> None:
    """Market Pulse — big whale pump & dump discovery."""
    _render_news_scanner_styles()
    _render_strategy_explanation()

    st.caption(
        "Automates steps **1, 2, 4, 5** via DexScreener; provides **Solscan / BscScan** links for wallet tracing (step 3)."
    )

    chain_options = list(CHAIN_META.keys())
    chains = st.multiselect(
        "Chains",
        chain_options,
        default=["solana", "bsc"],
        format_func=lambda c: CHAIN_META.get(c, {}).get("label", c),
        key=f"{_PREFIX}_chains",
    )

    with st.expander("⚙️ Scan filters", expanded=False):
        min_pump = st.slider("Min 24h pump %", 5.0, 80.0, 10.0, 1.0, key=f"{_PREFIX}_pump")
        min_liq = st.number_input("Min liquidity USD", 5_000, 500_000, 25_000, 5_000, key=f"{_PREFIX}_liq")
        min_vol = st.number_input("Min 24h volume USD", 10_000, 2_000_000, 50_000, 10_000, key=f"{_PREFIX}_vol")
        max_tok = st.slider("Max boosted tokens / chain", 5, 40, 20, key=f"{_PREFIX}_max")
        min_trade_conf = st.slider("Min confidence for TAKE TRADE", 50, 80, 58, 1, key=f"{_PREFIX}_minconf")

    run = st.button(
        "🐋 Scan Big Whale Pump & Dump",
        type="primary",
        key=f"{_PREFIX}_run",
        use_container_width=True,
    )

    if run:
        if not chains:
            st.warning("Select at least one chain.")
        else:
            with nullcontext():
                try:
                    cfg = WhaleScanConfig(
                        chains=chains,
                        min_pump_24h_pct=min_pump,
                        min_liquidity_usd=float(min_liq),
                        min_volume_24h_usd=float(min_vol),
                        max_tokens_per_chain=int(max_tok),
                        min_trade_confidence=float(min_trade_conf),
                    )
                    st.session_state[_PAYLOAD_KEY] = run_big_whale_scan(cfg)
                except Exception as exc:
                    st.session_state[_PAYLOAD_KEY] = {"error": str(exc)[:300]}

    payload = st.session_state.get(_PAYLOAD_KEY)
    if payload:
        st.markdown("---")
        _render_results(payload)
