"""
big_whale_pump_dump_engine.py
-----------------------------
Big Whale Pump & Dump — on-chain style workflow using DexScreener + explorer links.

Video playbook:
  1. Track 24h pumped tokens (whale / trending flow proxy)
  2. Scan largest trades (volume + txn size proxy on DEX pairs)
  3. Link wallets via Solscan / BscScan (manual trace — explorer URLs)
  4. Flag new tokens whales may be accumulating (boost + volume + buys)
  5. Rank liquidity inflows (liquidity USD + volume vs mcap)

Uses public DexScreener API (no key). Does NOT place orders.
NOT FINANCIAL ADVICE.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import numpy as np
import requests

from app.market_pulse.run_summary import make_trade_plan

logger = logging.getLogger(__name__)

DEX_API = "https://api.dexscreener.com"
_USER_AGENT = "TrueBacktester/1.0 (educational)"

CHAIN_META: dict[str, dict[str, str]] = {
    "solana": {
        "label": "Solana",
        "explorer": "https://solscan.io",
        "token_url": "https://solscan.io/token/{address}",
        "account_url": "https://solscan.io/account/{address}",
        "dexscreener": "https://dexscreener.com/solana/{pair}",
    },
    "bsc": {
        "label": "BNB Chain",
        "explorer": "https://bscscan.com",
        "token_url": "https://bscscan.com/token/{address}",
        "account_url": "https://bscscan.com/address/{address}",
        "dexscreener": "https://dexscreener.com/bsc/{pair}",
    },
    "ethereum": {
        "label": "Ethereum",
        "explorer": "https://etherscan.io",
        "token_url": "https://etherscan.io/token/{address}",
        "account_url": "https://etherscan.io/address/{address}",
        "dexscreener": "https://dexscreener.com/ethereum/{pair}",
    },
    "base": {
        "label": "Base",
        "explorer": "https://basescan.org",
        "token_url": "https://basescan.org/token/{address}",
        "account_url": "https://basescan.org/address/{address}",
        "dexscreener": "https://dexscreener.com/base/{pair}",
    },
}


@dataclass
class WhaleScanConfig:
    chains: list[str] = field(default_factory=lambda: ["solana", "bsc"])
    min_pump_24h_pct: float = 10.0
    min_liquidity_usd: float = 25_000.0
    min_volume_24h_usd: float = 50_000.0
    max_tokens_per_chain: int = 10_000  # no practical per-chain token cap
    accumulation_pump_max_pct: float = 45.0
    accumulation_pump_min_pct: float = 3.0
    big_trade_volume_pctile: float = 70.0
    request_pause_sec: float = 0.12


    big_trade_volume_pctile: float = 70.0
    request_pause_sec: float = 0.12
    min_trade_confidence: float = 58.0


def _sl_tp_for_dex_trade(
    pump_24h: float,
    direction: str,
    liquidity_usd: float,
) -> tuple[float, float]:
    """DEX meme defaults: 3% SL / 15% TP — adjusted for liquidity & setup type."""
    sl, tp = 3.0, 15.0
    if liquidity_usd < 40_000:
        sl = 4.0
        tp = 12.0
    elif liquidity_usd > 400_000:
        sl = 2.5
        tp = 16.0
    if direction == "SHORT":
        sl = max(sl, 3.0)
        tp = min(tp, 14.0) if pump_24h >= 40 else tp
        if pump_24h >= 60:
            sl = 4.5
            tp = 18.0
    elif direction == "LONG":
        if pump_24h < 12:
            tp = 18.0
        elif pump_24h > 35:
            sl = 3.5
            tp = 12.0
    return round(sl, 2), round(tp, 2)


def suggest_whale_trade(
    pair: dict,
    *,
    role: str,
    min_confidence: float = 58.0,
) -> dict[str, Any]:
    """
    BUY/SELL/WAIT from whale-flow role + on-chain metrics.
    roles: accumulation, watchlist, liquidity, pumped_fade, big_trade, momentum
    """
    pump = float(pair.get("pump_24h_pct") or 0)
    buy_p = float(pair.get("buy_pressure_pct") or 50)
    liq = float(pair.get("liquidity_usd") or 0)
    vol = float(pair.get("volume_24h_usd") or 0)
    whale = float(pair.get("whale_activity_score") or 0)

    direction = "WAIT"
    take = False
    conf = 32.0
    reasons: list[str] = []

    if liq < 15_000 or vol < 20_000:
        return _finalize_trade_setup(
            pair, direction="WAIT", confidence=28, sl=3.0, tp=15.0,
            take=False, reasons=["Liquidity/volume too thin for safe sizing"],
        )

    long_roles = {"accumulation", "watchlist", "liquidity", "momentum"}
    short_roles = {"pumped_fade", "big_trade"}

    if role in long_roles:
        acc_score = float(pair.get("accumulation_score") or 0)
        liq_score = float(pair.get("liquidity_inflow_score") or 0)
        if buy_p >= 54 and pump <= 48:
            direction = "LONG"
            conf = 42 + buy_p * 0.28 + whale * 0.12
            if role == "accumulation":
                conf += acc_score * 0.35
                reasons.append("Whale accumulation — buys dominating DEX flow")
            if role == "watchlist":
                conf += 10
                reasons.append("Pre-pump watchlist — liquidity + pump confluence")
            if role == "liquidity":
                conf += liq_score * 0.08
                reasons.append("Heavy liquidity inflow — capital gathering")
            if role == "momentum" and 8 <= pump <= 32:
                conf += pump * 0.35
                reasons.append("Early pump momentum with buy pressure")
            if pair.get("is_boosted"):
                conf += 5
                reasons.append("Paid boost / trending board listing")
            if pump > 40:
                conf -= 12
                reasons.append("Already extended — long confidence reduced")

    if role in short_roles or (role == "pumped_fade" and pump >= 22):
        if pump >= 22 and (buy_p < 50 or pump >= 35):
            short_conf = 40 + min(pump, 90) * 0.38 + (100 - buy_p) * 0.12
            if pair.get("big_trade_flag"):
                short_conf += 12
                reasons.append("Large 24h DEX volume — distribution / whale exit risk")
            if pump >= 40:
                reasons.append("Extended 24h pump — fade breakdown setup")
            if short_conf > conf:
                direction = "SHORT"
                conf = short_conf

    if direction == "WAIT" and role == "big_trade" and pump >= 15:
        if buy_p >= 56:
            direction = "LONG"
            conf = 48 + buy_p * 0.2
            reasons.append("Big volume with buy pressure — momentum long")
        elif buy_p <= 44:
            direction = "SHORT"
            conf = 48 + (100 - buy_p) * 0.2 + pump * 0.2
            reasons.append("Big volume with sell pressure — breakdown short")

    sl, tp = _sl_tp_for_dex_trade(pump, direction, liq)
    conf = max(22.0, min(91.0, conf))
    take = direction in ("LONG", "SHORT") and conf >= min_confidence

    if direction == "LONG" and pump > 55:
        take = False
        conf = min(conf, 52)
        reasons.append("Pump too extended — wait for pullback (no long)")

    return _finalize_trade_setup(
        pair, direction=direction, confidence=conf, sl=sl, tp=tp,
        take=take, reasons=reasons,
    )


def _finalize_trade_setup(
    pair: dict,
    *,
    direction: str,
    confidence: float,
    sl: float,
    tp: float,
    take: bool,
    reasons: list[str],
) -> dict[str, Any]:
    price = float(pair.get("price_usd") or 0)
    dir_u = direction if direction in ("LONG", "SHORT") else "WAIT"
    verdict = "BUY" if dir_u == "LONG" else "SELL" if dir_u == "SHORT" else "WAIT"
    if take and dir_u == "LONG":
        verdict = "TAKE LONG"
    elif take and dir_u == "SHORT":
        verdict = "TAKE SHORT"
    elif dir_u != "WAIT":
        verdict = f"WATCH {verdict}"

    rr = round(tp / sl, 2) if sl > 0 else None
    plan = make_trade_plan(
        direction=dir_u if take else "—",
        timeframe="DEX-24h",
        stop_loss_pct=sl,
        take_profit_pct=tp,
        confidence_pct=confidence,
        style="scalp",
        exit_rule="; ".join(reasons[:3]) if reasons else "Whale flow signal",
    )

    return {
        "take_trade": take,
        "direction": dir_u,
        "verdict": verdict,
        "confidence_pct": round(confidence, 1),
        "sl_pct": sl,
        "tp_pct": tp,
        "rr_ratio": rr,
        "entry_price_usd": price,
        "reasons": reasons[:5],
        "trade_plan": plan,
    }


def _attach_trades(items: list[dict], role: str, min_confidence: float) -> list[dict]:
    out = []
    for p in items:
        row = dict(p)
        row["trade_setup"] = suggest_whale_trade(row, role=role, min_confidence=min_confidence)
        out.append(row)
    return out


def _build_trade_recommendations(lists: list[tuple[str, list[dict]]]) -> list[dict]:
    """Merged ranked trade ideas across pipeline steps."""
    seen: set[str] = set()
    recs: list[dict] = []
    for _role, items in lists:
        for p in items:
            sym = f"{p.get('chain_id')}:{p.get('symbol')}"
            if sym in seen:
                continue
            setup = p.get("trade_setup") or {}
            if not setup.get("take_trade"):
                continue
            seen.add(sym)
            recs.append({
                "symbol": p.get("symbol"),
                "chain_label": p.get("chain_label"),
                "verdict": setup.get("verdict"),
                "direction": setup.get("direction"),
                "confidence_pct": setup.get("confidence_pct"),
                "sl_pct": setup.get("sl_pct"),
                "tp_pct": setup.get("tp_pct"),
                "rr_ratio": setup.get("rr_ratio"),
                "pump_24h_pct": p.get("pump_24h_pct"),
                "liquidity_usd": p.get("liquidity_usd"),
                "price_usd": p.get("price_usd"),
                "dexscreener_url": p.get("dexscreener_url"),
                "reasons": setup.get("reasons", []),
            })
    recs.sort(key=lambda x: (-x.get("confidence_pct", 0), -abs(x.get("pump_24h_pct", 0))))
    return recs


def _get_json(path: str, *, params: dict | None = None) -> Any:
    url = f"{DEX_API}{path}" if path.startswith("/") else path
    try:
        resp = requests.get(
            url,
            params=params,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("DexScreener request failed %s: %s", url, exc)
        return None


def fetch_token_boosts() -> list[dict]:
    """Latest + top boosted tokens (paid promotion = speculative flow)."""
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for path in ("/token-boosts/latest/v1", "/token-boosts/top/v1"):
        data = _get_json(path)
        if not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, dict):
                continue
            chain = str(item.get("chainId") or "")
            addr = str(item.get("tokenAddress") or "")
            if not chain or not addr:
                continue
            key = (chain, addr.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "chain_id": chain,
                "token_address": addr,
                "boost_amount": item.get("amount"),
                "boost_total": item.get("totalAmount"),
                "source": path,
            })
    return out


def fetch_pairs_for_token(chain_id: str, token_address: str) -> list[dict]:
    data = _get_json(f"/token-pairs/v1/{quote(chain_id, safe='')}/{quote(token_address, safe='')}")
    if isinstance(data, list):
        return [p for p in data if isinstance(p, dict)]
    if isinstance(data, dict) and isinstance(data.get("pairs"), list):
        return data["pairs"]
    return []


def _pair_metrics(pair: dict) -> dict[str, Any]:
    base = pair.get("baseToken") or {}
    quote = pair.get("quoteToken") or {}
    liq = pair.get("liquidity") or {}
    vol = pair.get("volume") or {}
    pc = pair.get("priceChange") or {}
    txns = pair.get("txns") or {}
    h24_tx = txns.get("h24") or {}
    buys = int(h24_tx.get("buys") or 0)
    sells = int(h24_tx.get("sells") or 0)
    vol_h24 = float(vol.get("h24") or 0)
    liq_usd = float(liq.get("usd") or 0)
    pump_24h = float(pc.get("h24") or 0)
    price_usd = float(pair.get("priceUsd") or 0)
    mcap = float(pair.get("marketCap") or pair.get("fdv") or 0)
    chain = str(pair.get("chainId") or "")
    pair_addr = str(pair.get("pairAddress") or "")
    token_addr = str(base.get("address") or "")

    buy_pressure = buys / max(buys + sells, 1) * 100
    vol_liq_ratio = vol_h24 / max(liq_usd, 1)
    whale_score = min(100, vol_h24 / 10_000 * 0.3 + (buys + sells) * 0.15 + abs(pump_24h) * 0.5)

    meta = CHAIN_META.get(chain, {})
    dex_url = pair.get("url") or ""
    if not dex_url and chain and pair_addr:
        tpl = meta.get("dexscreener", "https://dexscreener.com/{chain}/{pair}")
        dex_url = tpl.format(chain=chain, pair=pair_addr)

    token_url = meta.get("token_url", "").format(address=token_addr) if token_addr else ""
    explorer_note = (
        f"Open token on {meta.get('label', chain)} explorer → Transfers / Holders to trace whale wallets."
        if token_url else ""
    )

    return {
        "chain_id": chain,
        "chain_label": meta.get("label", chain),
        "dex_id": pair.get("dexId"),
        "pair_address": pair_addr,
        "symbol": base.get("symbol") or "?",
        "name": base.get("name") or base.get("symbol") or "?",
        "token_address": token_addr,
        "quote_symbol": quote.get("symbol"),
        "price_usd": price_usd,
        "pump_24h_pct": round(pump_24h, 2),
        "volume_24h_usd": round(vol_h24, 2),
        "liquidity_usd": round(liq_usd, 2),
        "market_cap_usd": round(mcap, 2) if mcap else None,
        "buys_24h": buys,
        "sells_24h": sells,
        "buy_pressure_pct": round(buy_pressure, 1),
        "vol_liquidity_ratio": round(vol_liq_ratio, 2),
        "whale_activity_score": round(whale_score, 1),
        "dexscreener_url": dex_url,
        "token_explorer_url": token_url,
        "pair_created_at": pair.get("pairCreatedAt"),
        "explorer_note": explorer_note,
    }


def _best_pair(pairs: list[dict]) -> dict | None:
    if not pairs:
        return None
    scored = []
    for p in pairs:
        liq = float((p.get("liquidity") or {}).get("usd") or 0)
        vol = float((p.get("volume") or {}).get("h24") or 0)
        scored.append((liq + vol * 0.1, p))
    return max(scored, key=lambda x: x[0])[1]


def _step1_pumped_pairs(pairs_metrics: list[dict], cfg: WhaleScanConfig) -> list[dict]:
    pumped = [
        p for p in pairs_metrics
        if p["pump_24h_pct"] >= cfg.min_pump_24h_pct
        and p["liquidity_usd"] >= cfg.min_liquidity_usd
        and p["volume_24h_usd"] >= cfg.min_volume_24h_usd
    ]
    pumped.sort(key=lambda x: (-x["pump_24h_pct"], -x["volume_24h_usd"]))
    return pumped


def _step2_big_trades(pumped: list[dict], cfg: WhaleScanConfig) -> list[dict]:
    if not pumped:
        return []
    vols = [p["volume_24h_usd"] for p in pumped]
    threshold = float(np.percentile(vols, cfg.big_trade_volume_pctile)) if vols else 0
    big = [p for p in pumped if p["volume_24h_usd"] >= threshold]
    for p in big:
        p["big_trade_flag"] = True
        p["big_trade_note"] = (
            f"Top {100 - cfg.big_trade_volume_pctile:.0f}% 24h DEX volume "
            f"(${p['volume_24h_usd']:,.0f}) — review largest swaps on DexScreener pair page."
        )
    big.sort(key=lambda x: -x["volume_24h_usd"])
    return big


def _step4_accumulation(candidates: list[dict], cfg: WhaleScanConfig) -> list[dict]:
    """Tokens whales may be entering — moderate pump, buy pressure, boosts."""
    acc = []
    for p in candidates:
        pump = p["pump_24h_pct"]
        if not (cfg.accumulation_pump_min_pct <= pump <= cfg.accumulation_pump_max_pct):
            continue
        if p["buy_pressure_pct"] < 52:
            continue
        if p["volume_24h_usd"] < cfg.min_volume_24h_usd * 0.5:
            continue
        entry = dict(p)
        entry["accumulation_score"] = round(
            p["buy_pressure_pct"] * 0.4 + p["vol_liquidity_ratio"] * 10 + min(pump, 30) * 0.8,
            1,
        )
        entry["accumulation_note"] = (
            "Rising buys + volume — check explorer Transfers for fresh whale wallet entries."
        )
        acc.append(entry)
    acc.sort(key=lambda x: -x["accumulation_score"])
    return acc


def _step5_liquidity_leaders(all_metrics: list[dict], cfg: WhaleScanConfig) -> list[dict]:
    """Highest liquidity + volume = capital gathering (pre-pump signal)."""
    eligible = [p for p in all_metrics if p["liquidity_usd"] >= cfg.min_liquidity_usd]
    for p in eligible:
        p["liquidity_inflow_score"] = round(
            p["liquidity_usd"] * 0.0001 + p["volume_24h_usd"] * 0.0002 + p["buy_pressure_pct"] * 0.3,
            2,
        )
    eligible.sort(key=lambda x: -x["liquidity_inflow_score"])
    return eligible


def _linked_wallet_actions(pair: dict) -> list[dict]:
    """Actionable links for manual wallet trace (video step 3–4)."""
    actions = []
    if pair.get("dexscreener_url"):
        actions.append({
            "step": "2 · Big trades",
            "label": "DexScreener pair — filter largest trades",
            "url": pair["dexscreener_url"],
        })
    if pair.get("token_explorer_url"):
        actions.append({
            "step": "3–4 · Wallets",
            "label": f"{pair.get('chain_label')} token — holders & transfers",
            "url": pair["token_explorer_url"],
        })
    return actions


def run_big_whale_scan(cfg: WhaleScanConfig | None = None) -> dict[str, Any]:
    """Full 5-step whale pump/dump discovery pipeline."""
    cfg = cfg or WhaleScanConfig()
    boosts = fetch_token_boosts()
    time.sleep(cfg.request_pause_sec)

    all_metrics: list[dict] = []
    errors: list[str] = []
    scanned_tokens = 0

    boost_index = {(b["chain_id"], b["token_address"].lower()): b for b in boosts}

    for chain in cfg.chains:
        chain_boosts = [b for b in boosts if b["chain_id"] == chain][: cfg.max_tokens_per_chain]
        if not chain_boosts:
            chain_boosts = [{"chain_id": chain, "token_address": "", "source": "search"}]

        tokens_to_fetch: list[tuple[str, str]] = []
        for b in chain_boosts:
            addr = b.get("token_address")
            if addr:
                tokens_to_fetch.append((chain, addr))

        if len(tokens_to_fetch) < 5:
            search = _get_json("/latest/dex/search", params={"q": chain})
            time.sleep(cfg.request_pause_sec)
            if isinstance(search, dict):
                for p in (search.get("pairs") or []):
                    if str(p.get("chainId")) != chain:
                        continue
                    base = (p.get("baseToken") or {}).get("address")
                    if base:
                        tokens_to_fetch.append((chain, base))

        seen_addr: set[str] = set()
        for chain_id, token_addr in tokens_to_fetch:
            if token_addr.lower() in seen_addr:
                continue
            seen_addr.add(token_addr.lower())
            pairs = fetch_pairs_for_token(chain_id, token_addr)
            time.sleep(cfg.request_pause_sec)
            scanned_tokens += 1
            best = _best_pair(pairs)
            if not best:
                continue
            m = _pair_metrics(best)
            boost = boost_index.get((chain_id, token_addr.lower()))
            if boost:
                m["is_boosted"] = True
                m["boost_total"] = boost.get("boost_total")
            m["linked_actions"] = _linked_wallet_actions(m)
            all_metrics.append(m)

    if not all_metrics:
        return {
            "error": "No DEX pairs returned — check network or try again.",
            "scanned_tokens": scanned_tokens,
            "boosts_found": len(boosts),
        }

    pumped = _step1_pumped_pairs(all_metrics, cfg)
    big_trades = _step2_big_trades(pumped, cfg) if pumped else []
    accumulation = _step4_accumulation(all_metrics, cfg)
    liquidity_leaders = _step5_liquidity_leaders(all_metrics, cfg)

    watchlist = []
    for p in liquidity_leaders:
        if p in accumulation or any(p["symbol"] == x["symbol"] for x in pumped):
            entry = dict(p)
            entry["verdict"] = "HIGH_WATCH"
            entry["verdict_note"] = (
                "Liquidity + buy flow on a pumped/boosted name — "
                "whales may be positioning before the next leg."
            )
            watchlist.append(entry)

    min_conf = cfg.min_trade_confidence
    pumped = _attach_trades(pumped, "pumped_fade", min_conf)
    big_trades = _attach_trades(big_trades, "big_trade", min_conf)
    accumulation = _attach_trades(accumulation, "accumulation", min_conf)
    liquidity_leaders = _attach_trades(liquidity_leaders, "liquidity", min_conf)
    watchlist = _attach_trades(watchlist, "watchlist", min_conf)

    # Early momentum longs on moderate pumps not yet in fade zone
    for p in pumped:
        if 8 <= p.get("pump_24h_pct", 0) <= 32 and p.get("buy_pressure_pct", 0) >= 58:
            mom = suggest_whale_trade(p, role="momentum", min_confidence=min_conf)
            if mom.get("confidence_pct", 0) > (p.get("trade_setup") or {}).get("confidence_pct", 0):
                p["trade_setup"] = mom

    trade_recommendations = _build_trade_recommendations([
        ("watchlist", watchlist),
        ("accumulation", accumulation),
        ("big_trade", big_trades),
        ("pumped", pumped),
        ("liquidity", liquidity_leaders),
    ])

    return {
        "scanned_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "config": {
            "chains": cfg.chains,
            "min_pump_24h_pct": cfg.min_pump_24h_pct,
            "min_liquidity_usd": cfg.min_liquidity_usd,
        },
        "boosts_found": len(boosts),
        "scanned_tokens": scanned_tokens,
        "step1_pumped_24h": pumped,
        "step2_big_trades": big_trades,
        "step4_accumulation": accumulation,
        "step5_liquidity_inflows": liquidity_leaders,
        "pre_pump_watchlist": watchlist,
        "trade_recommendations": trade_recommendations,
        "summary": {
            "pumped_count": len(pumped),
            "big_trade_count": len(big_trades),
            "accumulation_count": len(accumulation),
            "trade_signals": len(trade_recommendations),
            "top_pump_symbol": pumped[0]["symbol"] if pumped else None,
            "top_pump_pct": pumped[0]["pump_24h_pct"] if pumped else None,
        },
    }
