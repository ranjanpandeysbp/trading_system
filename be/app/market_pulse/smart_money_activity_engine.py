"""
smart_money_activity_engine.py
------------------------------
Check Smart Money Activity — for one or more tickers + date range, scan
preferred India fund houses (SBI / HDFC / ICICI Prudential / Nippon) mutual
funds and/or ETFs (and major US/crypto ETFs) to see whether institutional
stake is rising or falling, then emit a trade signal.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

import pandas as pd

from app.market_pulse.etf_holdings_engine import (
    CRYPTO_ETF_ISSUERS,
    US_ETF_ISSUERS,
    analyze_india_etf_holdings_change,
    analyze_us_etf_holdings_change,
    fetch_amc_list as fetch_etf_amc_list,
    fetch_etf_schemes_for_amc,
)
from app.market_pulse.mutual_fund_holdings_engine import (
    HoldingsChangeConfig,
    analyze_holdings_change,
    fetch_amc_list,
    fetch_schemes_for_amc,
)

logger = logging.getLogger(__name__)


def _as_records(obj: Any) -> list[dict[str, Any]]:
    if obj is None:
        return []
    if isinstance(obj, pd.DataFrame):
        if obj.empty:
            return []
        return obj.to_dict(orient="records")
    if isinstance(obj, list):
        return [r for r in obj if isinstance(r, dict)]
    return []

# Restricted fund houses (India StockEdge AMC name match).
PREFERRED_AMC_KEYWORDS: tuple[str, ...] = (
    "SBI",
    "HDFC",
    "ICICI",
    "NIPPON",
)

_MAX_SCHEMES_PER_AMC = 18
_MAX_US_CRYPTO_ETFS = 14
_MAX_SNAPSHOT_POINTS = 8

_SUFFIX_RE = re.compile(
    r"\b(limited|ltd\.?|inc\.?|corp\.?|corporation|plc|co\.?|the)\b",
    re.I,
)


def _norm(s: str) -> str:
    t = (s or "").strip().upper()
    t = _SUFFIX_RE.sub(" ", t)
    t = re.sub(r"[^A-Z0-9]+", " ", t)
    return " ".join(t.split())


def _ticker_aliases(ticker: str) -> set[str]:
    raw = (ticker or "").strip().upper()
    out = {raw, _norm(raw)}
    # NSE/Yahoo style suffixes
    for suf in (".NS", ".BO", "-EQ", ".NSE"):
        if raw.endswith(suf):
            out.add(raw[: -len(suf)])
            out.add(_norm(raw[: -len(suf)]))
    # CoinDCX futures often look like BTCUSDT / BTC-INR
    for sep in ("USDT", "USD", "INR", "PERP"):
        if raw.endswith(sep) and len(raw) > len(sep) + 1:
            out.add(raw[: -len(sep)])
    return {x for x in out if x}


def stock_matches_ticker(stock: str, ticker: str, *, slug: str = "") -> bool:
    """Loose match between holding name/slug and a user ticker symbol."""
    aliases = _ticker_aliases(ticker)
    sn = _norm(stock)
    slug_n = _norm(slug.replace("-", " "))
    for a in aliases:
        if not a:
            continue
        if sn == a or slug_n == a:
            return True
        if len(a) >= 3 and (a in sn or a in slug_n or sn.startswith(a) or slug_n.startswith(a)):
            return True
        # compact compare: RELIANCEINDUSTRIES vs RELIANCE
        compact_s = sn.replace(" ", "")
        compact_a = a.replace(" ", "")
        if compact_a and (compact_s.startswith(compact_a) or compact_a in compact_s):
            return True
    return False


def _amc_id(row: dict) -> int | None:
    try:
        return int(row.get("ID") or row.get("Id") or 0) or None
    except (TypeError, ValueError):
        return None


def _amc_matches_preferred(name: str) -> bool:
    n = (name or "").upper()
    return any(k in n for k in PREFERRED_AMC_KEYWORDS)


def resolve_preferred_amcs(amcs: list[dict] | None = None) -> list[dict[str, Any]]:
    """Return preferred India AMCs from StockEdge list."""
    amcs = amcs if amcs is not None else fetch_amc_list()
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in amcs:
        aid = _amc_id(row)
        name = str(row.get("Name") or "")
        if aid is None or aid in seen:
            continue
        if not _amc_matches_preferred(name):
            continue
        seen.add(aid)
        out.append({"id": aid, "name": name, "aum": row.get("AUM"), "scheme_count": row.get("SchemeCount")})
    return out


def _scheme_sort_key(s: dict) -> float:
    try:
        return float(s.get("AUM") or 0)
    except (TypeError, ValueError):
        return 0.0


def _collect_india_schemes(
    *,
    etf_only: bool,
    max_per_amc: int = _MAX_SCHEMES_PER_AMC,
) -> tuple[list[int], dict[int, str], list[dict[str, Any]]]:
    amcs = resolve_preferred_amcs(fetch_etf_amc_list() if etf_only else fetch_amc_list())
    scheme_ids: list[int] = []
    names: dict[int, str] = {}
    meta: list[dict[str, Any]] = []
    for amc in amcs:
        aid = int(amc["id"])
        schemes = (
            fetch_etf_schemes_for_amc(aid) if etf_only else fetch_schemes_for_amc(aid)
        )
        schemes = sorted(schemes, key=_scheme_sort_key, reverse=True)[:max_per_amc]
        for s in schemes:
            try:
                sid = int(s.get("ID") or s.get("Id") or 0)
            except (TypeError, ValueError):
                continue
            if not sid or sid in names:
                continue
            sname = str(s.get("Name") or sid)
            label = f"{amc['name']} — {sname}"
            scheme_ids.append(sid)
            names[sid] = label
            meta.append({"amc_id": aid, "amc_name": amc["name"], "scheme_id": sid, "scheme_name": sname})
    return scheme_ids, names, meta


def _collect_us_crypto_etfs(market: str, *, limit: int = _MAX_US_CRYPTO_ETFS) -> tuple[list[str], dict[str, str]]:
    catalog = CRYPTO_ETF_ISSUERS if market == "crypto" else US_ETF_ISSUERS
    symbols: list[str] = []
    names: dict[str, str] = {}
    for issuer, items in catalog.items():
        for item in items:
            sym = str(item.get("symbol") or "").upper()
            if not sym or sym in names:
                continue
            symbols.append(sym)
            names[sym] = f"{issuer} — {item.get('name') or sym}"
            if len(symbols) >= limit:
                return symbols, names
    return symbols, names


def _rows_from_overall(payload: dict[str, Any]) -> list[dict[str, Any]]:
    overall = payload.get("overall")
    if overall is None:
        return []
    if isinstance(overall, pd.DataFrame):
        return _as_records(overall)
    if isinstance(overall, list):
        return [r for r in overall if isinstance(r, dict)]
    return []


def _per_scheme_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    ps = payload.get("per_scheme")
    if ps is None:
        return []
    if isinstance(ps, pd.DataFrame):
        return _as_records(ps)
    if isinstance(ps, list):
        return [r for r in ps if isinstance(r, dict)]
    return []


def _signal_for_row(row: dict[str, Any]) -> dict[str, Any]:
    """Map holdings trend → BULLISH / ADD_LONG / WAIT / BEARISH / SELL_AVOID."""
    trend = str(row.get("overall_trend") or "STABLE").upper()
    up = int(row.get("schemes_increasing") or 0)
    down = int(row.get("schemes_decreasing") or 0)
    n = int(row.get("n_schemes") or (up + down + int(row.get("schemes_stable") or 0)) or 0)
    try:
        avg = float(row.get("avg_change_pct") or 0)
    except (TypeError, ValueError):
        avg = 0.0
    net = up - down

    strong_up = trend == "INCREASING" and avg > 0.05 and up >= down and up > 0
    mild_up = avg > 0.02 and net >= 1 and trend != "DECREASING"
    strong_down = trend == "DECREASING" and avg < -0.05 and down >= up and down > 0
    mild_down = avg < -0.02 and net <= -1 and trend != "INCREASING"

    if strong_up:
        signal = "ADD_LONG"
        bias = "BULLISH"
        summary = (
            f"Smart money accumulating: {up}/{n or '—'} funds raised stake "
            f"(avg Δ {avg:+.3f}%). Bias bullish — consider adding / holding long."
        )
    elif mild_up:
        signal = "BULLISH"
        bias = "BULLISH"
        summary = (
            f"Mild accumulation ({up} ↑ / {down} ↓, avg Δ {avg:+.3f}%). "
            f"Bullish lean — wait for confirmation or scale in carefully."
        )
    elif strong_down:
        signal = "SELL_AVOID"
        bias = "BEARISH"
        summary = (
            f"Smart money distributing: {down}/{n or '—'} funds cut stake "
            f"(avg Δ {avg:+.3f}%). Bias bearish — sell / avoid fresh longs."
        )
    elif mild_down:
        signal = "BEARISH"
        bias = "BEARISH"
        summary = (
            f"Mild distribution ({up} ↑ / {down} ↓, avg Δ {avg:+.3f}%). "
            f"Bearish lean — reduce risk or wait."
        )
    else:
        signal = "WAIT"
        bias = "WAIT"
        summary = (
            f"No clear institutional consensus (trend {trend.lower()}, "
            f"{up} ↑ / {down} ↓, avg Δ {avg:+.3f}%). Wait."
        )

    return {
        "signal": signal,
        "bias": bias,
        "summary": summary,
        "overall_trend": trend,
        "avg_change_pct": round(avg, 3),
        "schemes_increasing": up,
        "schemes_decreasing": down,
        "schemes_stable": int(row.get("schemes_stable") or 0),
        "n_schemes": n,
        "sector": row.get("sector"),
        "stock": row.get("stock"),
    }


def _filter_for_tickers(
    payload: dict[str, Any],
    tickers: list[str],
    *,
    source: str,
) -> list[dict[str, Any]]:
    overall = _rows_from_overall(payload)
    per_scheme = _per_scheme_rows(payload)
    results: list[dict[str, Any]] = []

    for ticker in tickers:
        matches = [
            r for r in overall
            if stock_matches_ticker(str(r.get("stock") or ""), ticker, slug=str(r.get("security_slug") or ""))
        ]
        if not matches:
            results.append({
                "ticker": ticker,
                "found": False,
                "signal": "WAIT",
                "bias": "WAIT",
                "summary": (
                    f"No holdings for {ticker} in the scanned {source} universe "
                    f"over this date range (or name did not match)."
                ),
                "matched_stocks": [],
                "fund_details": [],
                "source": source,
            })
            continue

        # Prefer the match with largest |avg_change| / most schemes
        matches.sort(
            key=lambda r: (abs(float(r.get("avg_change_pct") or 0)), int(r.get("n_schemes") or 0)),
            reverse=True,
        )
        best = matches[0]
        sig = _signal_for_row(best)
        matched_names = [str(m.get("stock")) for m in matches]
        details = [
            r for r in per_scheme
            if str(r.get("stock")) in matched_names
        ]
        results.append({
            "ticker": ticker,
            "found": True,
            "matched_stocks": matched_names,
            "fund_details": details[:40],
            "source": source,
            **sig,
            "stock": best.get("stock"),
        })
    return results


def _collect_india_schemes_for_amcs(
    amc_ids: list[int],
    *,
    etf_only: bool,
    max_per_amc: int | None = None,
) -> tuple[list[int], dict[int, str], list[dict[str, Any]]]:
    """Collect schemes for explicit AMC ids (no preferred-keyword filter)."""
    amc_list = fetch_etf_amc_list() if etf_only else fetch_amc_list()
    by_id = {_amc_id(a): a for a in amc_list if _amc_id(a) is not None}
    scheme_ids: list[int] = []
    names: dict[int, str] = {}
    meta: list[dict[str, Any]] = []
    for aid in amc_ids:
        row = by_id.get(aid)
        amc_name = str((row or {}).get("Name") or aid)
        schemes = fetch_etf_schemes_for_amc(aid) if etf_only else fetch_schemes_for_amc(aid)
        schemes = sorted(schemes, key=_scheme_sort_key, reverse=True)
        if max_per_amc is not None:
            schemes = schemes[:max_per_amc]
        for s in schemes:
            try:
                sid = int(s.get("ID") or s.get("Id") or 0)
            except (TypeError, ValueError):
                continue
            if not sid or sid in names:
                continue
            sname = str(s.get("Name") or sid)
            label = f"{amc_name} — {sname}"
            scheme_ids.append(sid)
            names[sid] = label
            meta.append({"amc_id": aid, "amc_name": amc_name, "scheme_id": sid, "scheme_name": sname})
    return scheme_ids, names, meta


def check_smart_money_activity(
    tickers: list[str],
    *,
    market: str = "india",
    source: str = "both",  # mutual_fund | etf | both
    from_date: date,
    to_date: date,
    max_schemes_per_amc: int = _MAX_SCHEMES_PER_AMC,
    amc_ids: list[int] | None = None,
    mf_scheme_ids: list[int] | None = None,
    mf_scheme_names: dict[int, str] | list[str] | None = None,
    etf_scheme_ids: list[int] | None = None,
    etf_scheme_names: dict[int, str] | list[str] | None = None,
    etf_symbols: list[str] | None = None,
    etf_symbol_names: dict[str, str] | list[str] | None = None,
) -> dict[str, Any]:
    """Main entry — returns per-ticker signals + underlying analysis meta.

    When scheme/ETF lists are provided, those are used. Otherwise India falls
    back to preferred AMCs (SBI/HDFC/ICICI/Nippon) and US/crypto to catalog ETFs.
    """
    tickers = [str(t).strip().upper() for t in tickers if str(t).strip()]
    if not tickers:
        return {"error": "Select at least one ticker."}
    if from_date > to_date:
        from_date, to_date = to_date, from_date

    market = (market or "india").lower()
    source = (source or "both").lower()
    if source not in ("mutual_fund", "etf", "both"):
        source = "both"

    def _name_map(ids: list[int] | list[str], names: dict | list | None, *, as_int: bool) -> dict:
        if isinstance(names, dict):
            out = {}
            for k, v in names.items():
                try:
                    key = int(k) if as_int else str(k).upper()
                except (TypeError, ValueError):
                    continue
                out[key] = str(v)
            return out
        if isinstance(names, list):
            out = {}
            for i, id_ in enumerate(ids):
                key = int(id_) if as_int else str(id_).upper()
                out[key] = str(names[i]) if i < len(names) else str(id_)
            return out
        return { (int(i) if as_int else str(i).upper()): str(i) for i in ids }

    cfg = HoldingsChangeConfig(max_snapshot_points=_MAX_SNAPSHOT_POINTS)
    analyses: list[dict[str, Any]] = []
    ticker_rows: list[dict[str, Any]] = []
    amcs_used: list[dict[str, Any]] = []
    notes: list[str] = []
    mf_ids_in = [int(x) for x in (mf_scheme_ids or []) if x]
    etf_ids_in = [int(x) for x in (etf_scheme_ids or []) if x]
    etf_syms_in = [str(s).strip().upper() for s in (etf_symbols or []) if str(s).strip()]
    selected_amc_ids = [int(x) for x in (amc_ids or []) if x is not None]
    # Explicit product picks from UI — do not auto-fill the other channel
    has_explicit_products = bool(mf_ids_in or etf_ids_in or etf_syms_in)
    manual = has_explicit_products or bool(selected_amc_ids)

    if market == "india":
        run_mf = source in ("mutual_fund", "both")
        run_etf = source in ("etf", "both")

        if run_mf:
            ids: list[int] = []
            names: dict[int, str] = {}
            if mf_ids_in:
                ids = mf_ids_in
                names = _name_map(ids, mf_scheme_names, as_int=True)
            elif has_explicit_products:
                notes.append("No mutual-fund schemes selected")
            elif selected_amc_ids:
                ids, names, _meta = _collect_india_schemes_for_amcs(
                    selected_amc_ids, etf_only=False, max_per_amc=None,
                )
            else:
                amcs_used = resolve_preferred_amcs()
                if not amcs_used:
                    return {
                        "error": "Could not resolve preferred AMCs (SBI / HDFC / ICICI / Nippon). Try again later.",
                    }
                ids, names, _meta = _collect_india_schemes(etf_only=False, max_per_amc=max_schemes_per_amc)

            if ids:
                notes.append(f"MF schemes scanned: {len(ids)}")
                mf = analyze_holdings_change(ids, names, from_date, to_date, cfg=cfg)
                mf["channel"] = "mutual_fund"
                analyses.append(mf)
                if not mf.get("error"):
                    ticker_rows.extend(_filter_for_tickers(mf, tickers, source="mutual_fund"))
                else:
                    notes.append(f"MF: {mf.get('error')}")
            elif not has_explicit_products:
                notes.append("No mutual-fund schemes selected / found")

        if run_etf:
            ids = []
            names = {}
            if etf_ids_in:
                ids = etf_ids_in
                names = _name_map(ids, etf_scheme_names, as_int=True)
            elif has_explicit_products:
                notes.append("No India ETF schemes selected")
            elif selected_amc_ids:
                ids, names, _meta = _collect_india_schemes_for_amcs(
                    selected_amc_ids, etf_only=True, max_per_amc=None,
                )
            else:
                if not amcs_used:
                    amcs_used = resolve_preferred_amcs(fetch_etf_amc_list())
                ids, names, _meta = _collect_india_schemes(
                    etf_only=True, max_per_amc=max(8, max_schemes_per_amc // 2),
                )

            if ids:
                notes.append(f"India ETF schemes scanned: {len(ids)}")
                etf = analyze_india_etf_holdings_change(ids, names, from_date, to_date, cfg=cfg)
                etf["channel"] = "etf"
                analyses.append(etf)
                if not etf.get("error"):
                    ticker_rows.extend(_filter_for_tickers(etf, tickers, source="etf"))
                else:
                    notes.append(f"ETF: {etf.get('error')}")
            elif not has_explicit_products:
                notes.append("No India ETF schemes selected / found")

        if selected_amc_ids and not amcs_used:
            amc_list = fetch_amc_list()
            by_id = {_amc_id(a): a for a in amc_list if _amc_id(a) is not None}
            for aid in selected_amc_ids:
                row = by_id.get(aid)
                amcs_used.append({
                    "id": aid,
                    "name": str((row or {}).get("Name") or aid),
                    "aum": (row or {}).get("AUM"),
                    "scheme_count": (row or {}).get("SchemeCount"),
                })

        if not analyses and not ticker_rows:
            return {
                "error": "Select at least one fund house and one or more funds/ETFs to scan.",
                "market": market,
                "manual_selection": manual,
            }

    else:
        # US / crypto — ETF path only
        if source == "mutual_fund":
            return {
                "error": "Mutual fund holdings are India-only. Use ETF (or Both) for US / Crypto.",
                "market": market,
            }
        if etf_syms_in:
            symbols = etf_syms_in
            names = _name_map(symbols, etf_symbol_names, as_int=False)
        else:
            symbols, names = _collect_us_crypto_etfs(market)
        if not symbols:
            return {"error": f"No {market.upper()} ETF catalog entries available. Select one or more ETFs."}
        notes.append(f"{market.upper()} ETFs scanned: {len(symbols)}")
        us = analyze_us_etf_holdings_change(market, symbols, names, from_date, to_date)
        us["channel"] = "etf"
        analyses.append(us)
        if us.get("error"):
            return {"error": us["error"], "market": market, "notes": notes, "manual_selection": manual}
        ticker_rows.extend(_filter_for_tickers(us, tickers, source="etf"))

    # Merge MF + ETF rows for same ticker when both ran
    merged = _merge_ticker_signals(tickers, ticker_rows)

    bullish = sum(1 for r in merged if r.get("bias") == "BULLISH")
    bearish = sum(1 for r in merged if r.get("bias") == "BEARISH")
    wait = sum(1 for r in merged if r.get("bias") == "WAIT")

    return {
        "market": market,
        "source": source,
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "tickers": tickers,
        "preferred_amcs": amcs_used,
        "preferred_amc_keywords": list(PREFERRED_AMC_KEYWORDS),
        "manual_selection": manual,
        "notes": notes,
        "summary": {
            "tickers": len(merged),
            "found": sum(1 for r in merged if r.get("found")),
            "bullish": bullish,
            "bearish": bearish,
            "wait": wait,
        },
        "results": merged,
        "analyses_meta": [
            {
                "channel": a.get("channel"),
                "error": a.get("error"),
                "n_dates": len(a.get("dates") or []) if not isinstance(a.get("dates"), pd.DataFrame) else len(a["dates"]),
                "n_schemes": len(a.get("scheme_ids") or []),
                "snapshot_note": a.get("snapshot_note"),
            }
            for a in analyses
        ],
    }


def _merge_ticker_signals(tickers: list[str], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combine MF + ETF findings per ticker into one signal."""
    by_ticker: dict[str, list[dict[str, Any]]] = {t: [] for t in tickers}
    for r in rows:
        t = str(r.get("ticker") or "").upper()
        if t in by_ticker:
            by_ticker[t].append(r)

    rank = {"ADD_LONG": 2, "BULLISH": 1, "WAIT": 0, "BEARISH": -1, "SELL_AVOID": -2}
    out: list[dict[str, Any]] = []
    for t in tickers:
        group = by_ticker.get(t) or []
        found = [g for g in group if g.get("found")]
        if not found:
            out.append(group[0] if group else {
                "ticker": t,
                "found": False,
                "signal": "WAIT",
                "bias": "WAIT",
                "summary": f"No smart-money holdings data for {t}.",
                "sources": [],
            })
            continue
        if len(found) == 1:
            one = dict(found[0])
            one["sources"] = [one.get("source")]
            out.append(one)
            continue

        # Average change across channels; pick stronger signal
        avg = sum(float(g.get("avg_change_pct") or 0) for g in found) / len(found)
        best = max(found, key=lambda g: abs(rank.get(str(g.get("signal")), 0)))
        # If channels conflict (one bullish one bearish) → WAIT
        biases = {g.get("bias") for g in found}
        if "BULLISH" in biases and "BEARISH" in biases:
            signal, bias = "WAIT", "WAIT"
            summary = (
                f"Mixed MF vs ETF flow for {t} (avg Δ {avg:+.3f}%). Wait for alignment. "
                + " | ".join(f"{g.get('source')}: {g.get('signal')}" for g in found)
            )
        else:
            signal = str(best.get("signal") or "WAIT")
            bias = str(best.get("bias") or "WAIT")
            summary = (
                f"Combined smart-money view ({', '.join(str(g.get('source')) for g in found)}): "
                f"{signal.replace('_', ' ').title()} — avg Δ {avg:+.3f}%. "
                + best.get("summary", "")
            )
        out.append({
            "ticker": t,
            "found": True,
            "signal": signal,
            "bias": bias,
            "summary": summary,
            "avg_change_pct": round(avg, 3),
            "overall_trend": best.get("overall_trend"),
            "matched_stocks": list({m for g in found for m in (g.get("matched_stocks") or [])}),
            "sources": [g.get("source") for g in found],
            "channels": found,
            "n_schemes": sum(int(g.get("n_schemes") or 0) for g in found),
            "schemes_increasing": sum(int(g.get("schemes_increasing") or 0) for g in found),
            "schemes_decreasing": sum(int(g.get("schemes_decreasing") or 0) for g in found),
            "sector": best.get("sector"),
            "stock": best.get("stock"),
        })
    return out
