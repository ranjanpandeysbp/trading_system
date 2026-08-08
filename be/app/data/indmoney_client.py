"""
INDstocks / IndMoney Trading API client
---------------------------------------
Auth: TOTP → POST /generate/token (x-api-key + mpin + totp)
Data: quotes, historical OHLCV, instruments master, option-chain (when available)

Docs: https://api-docs.indstocks.com/
Base: https://api.indstocks.com
"""

from __future__ import annotations

import io
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.indstocks.com"

# App TF → IndMoney interval path segment
_INTERVAL_MAP: dict[str, str] = {
    "1m": "1minute",
    "2m": "2minute",
    "3m": "3minute",
    "5m": "5minute",
    "10m": "10minute",
    "15m": "15minute",
    "30m": "30minute",
    "1h": "60minute",
    "60m": "60minute",
    "2h": "120minute",
    "3h": "180minute",
    "4h": "240minute",
    "1d": "1day",
    "1w": "1week",
    "1wk": "1week",
    "1M": "1month",
}

# Max fetch window per interval (docs)
_MAX_RANGE: dict[str, timedelta] = {
    "1minute": timedelta(days=7),
    "2minute": timedelta(days=7),
    "3minute": timedelta(days=7),
    "4minute": timedelta(days=7),
    "5minute": timedelta(days=7),
    "10minute": timedelta(days=7),
    "15minute": timedelta(days=7),
    "30minute": timedelta(days=7),
    "60minute": timedelta(days=14),
    "120minute": timedelta(days=14),
    "180minute": timedelta(days=14),
    "240minute": timedelta(days=14),
    "1day": timedelta(days=365),
    "1week": timedelta(days=365),
    "1month": timedelta(days=365),
}

# Common India index → IndMoney NIDX tokens (from docs / WS examples)
_INDEX_SCRIP: dict[str, str] = {
    "NIFTY": "NIDX_26000",
    "NIFTY 50": "NIDX_26000",
    "NIFTY50": "NIDX_26000",
    "^NSEI": "NIDX_26000",
    "BANKNIFTY": "NIDX_26009",
    "NIFTY BANK": "NIDX_26009",
    "FINNIFTY": "NIDX_26037",
    "MIDCPNIFTY": "NIDX_26074",
    "NIFTYNXT50": "NIDX_26013",
    "SENSEX": "BIDX_1",
}

_instrument_lock = threading.Lock()
_instrument_cache: dict[str, tuple[float, dict[str, str]]] = {}  # source -> (ts, SYMBOL->scrip)
_INSTRUMENT_TTL = 6 * 3600  # 6h


def _auth_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": (access_token or "").strip(),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def generate_totp_code(totp_secret: str) -> str:
    """Generate current 6-digit TOTP from base32 secret (requires pyotp)."""
    import pyotp

    secret = (totp_secret or "").strip().replace(" ", "")
    if not secret:
        raise ValueError("TOTP secret is empty")
    return pyotp.TOTP(secret).now()


def generate_access_token(*, client_id: str, mpin: str, totp: str, timeout: float = 20.0) -> dict[str, Any]:
    """
    POST /generate/token — returns {token, raw, error?}.
    Headers use x-api-key (Client ID), not Authorization.
    """
    client_id = (client_id or "").strip()
    mpin = (mpin or "").strip()
    totp = (totp or "").strip()
    if not client_id or not mpin or not totp:
        return {"token": None, "error": "client_id, mpin, and totp are required"}

    try:
        resp = requests.post(
            f"{BASE_URL}/generate/token",
            headers={
                "x-api-key": client_id,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={"mpin": mpin, "totp": totp},
            timeout=timeout,
        )
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            msg = data.get("message") or data.get("error") or data.get("detail") or resp.text[:200]
            return {"token": None, "error": f"HTTP {resp.status_code}: {msg}", "raw": data}

        token = None
        if isinstance(data, dict):
            token = data.get("token")
            inner = data.get("data")
            if not token and isinstance(inner, dict):
                token = inner.get("token") or inner.get("access_token")
            if not token and isinstance(inner, str):
                token = inner
            if not token:
                token = data.get("access_token")
        token = (token or "").strip() or None
        if not token:
            return {"token": None, "error": "No token in response", "raw": data}
        return {"token": token, "raw": data, "expires_in_hours": 24}
    except Exception as exc:
        logger.exception("IndMoney token generation failed")
        return {"token": None, "error": str(exc)}


def _normalize_symbol(symbol: str) -> str:
    return (symbol or "").strip().upper().replace(".NS", "").replace(".BO", "")


def _load_instruments(source: str, access_token: str) -> dict[str, str]:
    """Return SYMBOL_NAME / TRADING_SYMBOL → EXCH_SECURITY_ID map."""
    source = (source or "equity").strip().lower()
    now = time.time()
    with _instrument_lock:
        hit = _instrument_cache.get(source)
        if hit and now - hit[0] < _INSTRUMENT_TTL:
            return hit[1]

    try:
        resp = requests.get(
            f"{BASE_URL}/market/instruments",
            headers=_auth_headers(access_token),
            params={"source": source},
            timeout=60,
        )
        if resp.status_code >= 400 or not resp.text:
            logger.warning("IndMoney instruments %s failed: HTTP %s", source, resp.status_code)
            return hit[1] if hit else {}

        df = pd.read_csv(io.StringIO(resp.text))
        mapping: dict[str, str] = {}
        cols = {c.upper(): c for c in df.columns}
        exch_c = cols.get("EXCH")
        sec_c = cols.get("SECURITY_ID")
        sym_c = cols.get("SYMBOL_NAME")
        trade_c = cols.get("TRADING_SYMBOL")
        if not exch_c or not sec_c:
            logger.warning("IndMoney instruments CSV missing EXCH/SECURITY_ID")
            return hit[1] if hit else {}

        for _, row in df.iterrows():
            exch = str(row[exch_c] or "").strip().upper()
            sec = str(row[sec_c] or "").strip()
            if not exch or not sec or sec.lower() == "nan":
                continue
            # Quotes/historical use NSE_2885 style
            scrip = f"{exch}_{sec}"
            if sym_c:
                name = str(row[sym_c] or "").strip().upper()
                if name and name != "NAN":
                    mapping.setdefault(name, scrip)
            if trade_c:
                tsym = str(row[trade_c] or "").strip().upper()
                if tsym and tsym != "NAN":
                    mapping.setdefault(tsym, scrip)
                    # Strip -EQ suffix variants
                    base = tsym.split("-")[0]
                    if base:
                        mapping.setdefault(base, scrip)

        with _instrument_lock:
            _instrument_cache[source] = (now, mapping)
        logger.info("IndMoney instruments cached for %s (%d symbols)", source, len(mapping))
        return mapping
    except Exception as exc:
        logger.warning("IndMoney instruments load failed (%s): %s", source, exc)
        return hit[1] if hit else {}


def resolve_scrip_code(
    symbol: str,
    access_token: str,
    *,
    exchange: str = "NSE",
    prefer_index: bool = False,
) -> str | None:
    """Map ticker / index name → IndMoney scrip-code (e.g. NSE_2885, NIDX_26000)."""
    sym = _normalize_symbol(symbol)
    if not sym or not access_token:
        return None

    # Already a scrip code?
    if "_" in sym and sym.split("_", 1)[0] in ("NSE", "BSE", "NFO", "BFO", "NIDX", "BIDX"):
        return sym

    if prefer_index or sym in _INDEX_SCRIP or any(k in sym for k in ("NIFTY", "SENSEX", "BANKNIFTY")):
        if sym in _INDEX_SCRIP:
            return _INDEX_SCRIP[sym]
        for k, v in _INDEX_SCRIP.items():
            if k in sym or sym in k:
                return v
        idx_map = _load_instruments("index", access_token)
        if sym in idx_map:
            return idx_map[sym]

    exch = (exchange or "NSE").upper()
    eq_map = _load_instruments("equity", access_token)
    if sym in eq_map:
        scrip = eq_map[sym]
        # Prefer requested exchange when multiple exist — master is unique per SYMBOL usually
        if scrip.startswith(f"{exch}_") or exch == "NSE":
            return scrip
        # Try alternate key
        alt = eq_map.get(f"{sym}-{exch}") or scrip
        return alt

    # US: IndMoney Trading API is India-focused; no US equity master in docs.
    return None


def _window_for_interval(interval: str, limit: int) -> tuple[int, int]:
    """Return (start_ms, end_ms) IST-ish unix ms within max allowed range."""
    now = datetime.now(timezone.utc)
    # Docs: timestamps are IST epoch ms — approximate with UTC+5:30 offset for window sizing
    max_td = _MAX_RANGE.get(interval, timedelta(days=7))
    # Estimate bars → duration
    bar_td = {
        "1minute": timedelta(minutes=1),
        "2minute": timedelta(minutes=2),
        "3minute": timedelta(minutes=3),
        "5minute": timedelta(minutes=5),
        "10minute": timedelta(minutes=10),
        "15minute": timedelta(minutes=15),
        "30minute": timedelta(minutes=30),
        "60minute": timedelta(hours=1),
        "120minute": timedelta(hours=2),
        "240minute": timedelta(hours=4),
        "1day": timedelta(days=1),
        "1week": timedelta(weeks=1),
        "1month": timedelta(days=30),
    }.get(interval, timedelta(days=1))
    need = bar_td * max(limit + 5, 30)
    span = min(need, max_td - timedelta(minutes=1))
    end = now
    start = end - span
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def fetch_indmoney_ohlcv(
    symbol: str,
    timeframe: str,
    access_token: str,
    *,
    exchange: str = "NSE",
    limit: int = 300,
    prefer_index: bool = False,
) -> pd.DataFrame:
    """Fetch OHLCV via GET /market/historical/{interval}. Returns empty DF on failure."""
    token = (access_token or "").strip()
    if not token:
        return pd.DataFrame()

    interval = _INTERVAL_MAP.get((timeframe or "1d").strip(), None)
    if not interval:
        # Unsupported TF for IndMoney — caller should fallback
        return pd.DataFrame()

    scrip = resolve_scrip_code(symbol, token, exchange=exchange, prefer_index=prefer_index)
    if not scrip:
        logger.debug("IndMoney: no scrip for %s", symbol)
        return pd.DataFrame()

    start_ms, end_ms = _window_for_interval(interval, limit)
    try:
        resp = requests.get(
            f"{BASE_URL}/market/historical/{interval}",
            headers=_auth_headers(token),
            params={
                "scrip-codes": scrip,
                "start_time": start_ms,
                "end_time": end_ms,
            },
            timeout=45,
        )
        if resp.status_code >= 400:
            logger.debug("IndMoney historical HTTP %s for %s: %s", resp.status_code, scrip, resp.text[:160])
            return pd.DataFrame()
        payload = resp.json() if resp.content else {}
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return pd.DataFrame()
        block = data.get(scrip) or next(iter(data.values()), None)
        if not isinstance(block, dict):
            return pd.DataFrame()
        candles = block.get("candles") or []
        if not candles:
            return pd.DataFrame()

        rows = []
        for c in candles:
            if not isinstance(c, dict):
                continue
            ts = c.get("ts")
            if ts is None:
                continue
            # ts is unix seconds (IST per docs)
            rows.append({
                "date": pd.to_datetime(int(ts), unit="s"),
                "open": float(c.get("o") or 0),
                "high": float(c.get("h") or 0),
                "low": float(c.get("l") or 0),
                "close": float(c.get("c") or 0),
                "volume": float(c.get("v") or 0),
            })
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows).set_index("date").sort_index()
        df = df[~df.index.duplicated(keep="last")]
        return df.tail(limit)
    except Exception as exc:
        logger.debug("IndMoney OHLCV failed for %s: %s", symbol, exc)
        return pd.DataFrame()


def fetch_indmoney_quote(
    symbol: str,
    access_token: str,
    *,
    exchange: str = "NSE",
    prefer_index: bool = False,
) -> dict[str, Any] | None:
    """GET /market/quotes/ltp (or full). Returns {ltp, ...} or None."""
    token = (access_token or "").strip()
    if not token:
        return None
    scrip = resolve_scrip_code(symbol, token, exchange=exchange, prefer_index=prefer_index)
    if not scrip:
        return None
    try:
        resp = requests.get(
            f"{BASE_URL}/market/quotes/ltp",
            headers=_auth_headers(token),
            params={"scrip-codes": scrip},
            timeout=20,
        )
        if resp.status_code >= 400:
            # try full quotes
            resp = requests.get(
                f"{BASE_URL}/market/quotes/full",
                headers=_auth_headers(token),
                params={"scrip-codes": scrip},
                timeout=20,
            )
        if resp.status_code >= 400:
            return None
        payload = resp.json() if resp.content else {}
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return None
        block = data.get(scrip) or next(iter(data.values()), None)
        if not isinstance(block, dict):
            return None
        ltp = block.get("live_price") or block.get("ltp") or block.get("last_price")
        if ltp is None:
            return None
        return {
            "ltp": float(ltp),
            "scrip": scrip,
            "day_high": _f(block.get("day_high") or block.get("high")),
            "day_low": _f(block.get("day_low") or block.get("low")),
            "volume": _f(block.get("volume")),
            "change_pct": _f(block.get("day_change_percentage") or block.get("change_pct")),
            "raw": block,
        }
    except Exception as exc:
        logger.debug("IndMoney quote failed for %s: %s", symbol, exc)
        return None


def _f(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_indmoney_option_chain(
    symbol: str,
    access_token: str,
    *,
    expiry: str | None = None,
    count: int = 10,
) -> dict[str, Any] | None:
    """
    Try GET /option-chain (documented as Coming Soon).
    Returns normalized-ish dict or None so callers can fall back to NSE/Groww.
    """
    token = (access_token or "").strip()
    if not token:
        return None
    # Map common indices to NIDX tokens used in option-chain docs
    sym = _normalize_symbol(symbol)
    idx_token = _INDEX_SCRIP.get(sym) or _INDEX_SCRIP.get(sym.replace(" ", ""))
    if not idx_token and sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"):
        idx_token = _INDEX_SCRIP.get(sym)
    if not idx_token:
        # equity FNO — resolve from fno master if possible
        fno = _load_instruments("fno", token)
        # Without a stable underlying token for equity OC, skip
        if not fno:
            return None
        idx_token = None

    if not idx_token:
        # Docs example: NIDX_40000001 for NIFTY — try known map first; else fail soft
        return None

    try:
        # Expiries
        exp_resp = requests.get(
            f"{BASE_URL}/option-chain-symbols",
            headers=_auth_headers(token),
            json={"token": idx_token},
            timeout=20,
        )
        # Some gateways ignore body on GET — also try query
        if exp_resp.status_code >= 400:
            exp_resp = requests.get(
                f"{BASE_URL}/option-chain-symbols",
                headers=_auth_headers(token),
                params={"token": idx_token},
                timeout=20,
            )
        expiries: list[str] = []
        if exp_resp.status_code < 400 and exp_resp.content:
            ed = exp_resp.json()
            raw = (ed.get("data") or {}) if isinstance(ed, dict) else {}
            if isinstance(raw, dict):
                expiries = list(raw.get("expiries") or [])
            elif isinstance(raw, list):
                expiries = [str(x) for x in raw]

        use_expiry = expiry or (expiries[0] if expiries else None)
        if not use_expiry:
            return None

        oc_resp = requests.get(
            f"{BASE_URL}/option-chain",
            headers=_auth_headers(token),
            json={"token": idx_token, "count": str(count), "expiry": use_expiry},
            timeout=30,
        )
        if oc_resp.status_code >= 400:
            oc_resp = requests.get(
                f"{BASE_URL}/option-chain",
                headers=_auth_headers(token),
                params={"token": idx_token, "count": str(count), "expiry": use_expiry},
                timeout=30,
            )
        if oc_resp.status_code >= 400:
            logger.debug("IndMoney option-chain unavailable: HTTP %s", oc_resp.status_code)
            return None
        payload = oc_resp.json() if oc_resp.content else {}
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows:
            return None
        return {
            "source": "indmoney",
            "symbol": sym,
            "underlying_token": idx_token,
            "expiry_dates": expiries,
            "current_expiry": use_expiry,
            "strikes_raw": rows,
            "plain_english": f"IndMoney option chain for {sym} expiry {use_expiry} ({len(rows)} rows).",
        }
    except Exception as exc:
        logger.debug("IndMoney option-chain failed: %s", exc)
        return None


def health_check(access_token: str) -> dict[str, Any]:
    token = (access_token or "").strip()
    if not token:
        return {"ok": False, "provider": "indmoney", "error": "No access token"}
    try:
        resp = requests.get(
            f"{BASE_URL}/user/profile",
            headers=_auth_headers(token),
            timeout=15,
        )
        if resp.status_code >= 400:
            return {"ok": False, "provider": "indmoney", "error": f"HTTP {resp.status_code}: {resp.text[:160]}"}
        data = resp.json() if resp.content else {}
        # Also poke a quote
        q = fetch_indmoney_quote("RELIANCE", token, exchange="NSE")
        return {
            "ok": True,
            "provider": "indmoney",
            "profile": (data.get("data") if isinstance(data, dict) else None),
            "sample_ltp": (q or {}).get("ltp"),
        }
    except Exception as exc:
        return {"ok": False, "provider": "indmoney", "error": str(exc)}
