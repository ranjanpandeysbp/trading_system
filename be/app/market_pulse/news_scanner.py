from contextlib import nullcontext
"""
news_scanner.py
---------------
Market Intelligence Command Center for TrueBacktester.
Provides live global market data, news feeds, NSE Nifty Options Chain analysis,
and AI-powered market intelligence summaries.

Sections:
  1. Indian Markets (Nifty 50, Sensex, Bank Nifty, India VIX, Nifty IT, Midcap)
  2. Gift Nifty (live scrape from 5paisa.com)
  3. US Markets (Dow, S&P 500, Nasdaq, Russell 2000)
  4. Asia Markets (Nikkei, Hang Seng, Shanghai, KOSPI, STI, ASX, Taiwan)
  5. Europe Markets (FTSE, DAX, CAC 40)
  6. Global Futures (Dow/S&P/Nasdaq futures)
  7. Forex & Dollar
  8. Commodities, Crypto & Bond Yields
  9. Nifty Options Chain Analysis (PCR, Max Pain, OI, Directional Verdict)
 10. Price Charts
 11. News Feed (96h freshness, Moneycontrol-heavy RSS)
 11b. Analyst Calls & Brokerage Recommendations
 12. Upcoming Events (future-only macro calendar)
 13. AI Market Intelligence Summary
"""

import yfinance as yf
import feedparser
import requests
from bs4 import BeautifulSoup
import json
import time
import logging
from datetime import date, datetime, timedelta
from urllib.parse import quote
import plotly.graph_objects as go
import plotly.express as px
from groq import Groq
from app.market_pulse.ai_view import render_ai_provider_compact
from app.market_pulse.env_config import api_key_env_hint, get_api_key_for_provider
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.index_ohlcv import (
    clear_index_ohlcv_cache,
    download_yf_ticker_ohlcv,
    fetch_index_close_series,
    fetch_index_daily_ohlcv,
    fetch_index_interval_close_series,
    yf_ohlcv_from_download,
)
from app.market_pulse.nse_index_yfinance import (
    INDIA_MARKET_DISPLAY_YF,
    MARKET_DISPLAY_YF,
    NIFTY50_YF,
    SECTOR_INDEX_YF_TICKERS,
    index_name_to_yf as _index_name_to_yf,
    sector_fallback_index_names,
    stock_symbol_to_yf,
)
from app.market_pulse.nifty_index_constituents import get_index_constituent_symbols
try:
    from google import genai as genai_new
    GENAI_NEW = True
except ImportError:
    try:
        import google.generativeai as genai
        GENAI_NEW = False
    except ImportError:
        pass
import pandas as pd
import numpy as np
import pytz

logger = logging.getLogger(__name__)

# ─── Helper Functions ───────────────────────────────────────────────────────

def fmt_price(val, decimals=2):
    if val is None: return "N/A"
    return f"{val:,.{decimals}f}"

def fmt_change(pct):
    if pct is None: return ("N/A", "neu")
    sign = "▲" if pct >= 0 else "▼"
    cls = "pos" if pct >= 0 else "neg"
    return (f"{sign} {abs(pct):.2f}%", cls)


def fmt_last_pct(
    last,
    pct,
    *,
    prefix: str = "",
    suffix: str = "",
    decimals: int = 2,
    sep: str = " · ",
) -> str:
    """Last price and % change on one line, e.g. 23,217.00 · +0.23%."""
    parts = []
    if last is not None:
        try:
            if not (isinstance(last, float) and np.isnan(last)):
                parts.append(f"{prefix}{fmt_price(float(last), decimals)}{suffix}")
        except (TypeError, ValueError):
            pass
    if pct is not None:
        try:
            p = float(pct)
            parts.append(f"{p:+.2f}%")
        except (TypeError, ValueError):
            pass
    return sep.join(parts) if parts else "N/A"


def _market_quote_line(market_data: dict, name: str, pct=None, *, prefix="", decimals=2) -> str:
    """Price + % for outlook/sentiment chips."""
    d = (market_data or {}).get(name) or {}
    price = d.get("price")
    p = pct if pct is not None else d.get("pct")
    return fmt_last_pct(price, p, prefix=prefix, decimals=decimals)

def _parse_number_text(text):
    """Parse numeric strings like '23,091.00', '-436.5', or '(-1.86%)'."""
    if text is None:
        return None
    cleaned = str(text).replace("₹", "").replace(",", "").strip()
    cleaned = cleaned.replace("(", "").replace(")", "").replace("%", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def get_yf_data(ticker, period="3mo", interval="1d"):
    """Fetch the latest price, daily % change, and recent history for a ticker."""
    try:
        t = yf.Ticker(ticker)
        latest = None
        prev_close = None

        try:
            fi = t.fast_info
            latest = fi.get("last_price") or fi.get("regular_market_price")
            prev_close = fi.get("previous_close") or fi.get("regular_market_previous_close")
        except Exception:
            pass

        if latest is None:
            try:
                info = t.info
                latest = info.get("regularMarketPrice") or info.get("currentPrice")
                prev_close = prev_close or info.get("regularMarketPreviousClose") or info.get("previousClose")
            except Exception:
                pass

        hist = t.history(period=period, interval=interval, prepost=True)
        if hist.empty or len(hist) < 1:
            if latest is not None:
                pct = ((latest - prev_close) / prev_close * 100) if prev_close else 0.0
                return latest, pct, None
            return None, None, None

        if hist.index.tz is not None:
            hist.index = hist.index.tz_convert("Asia/Kolkata")

        if latest is None:
            latest = float(hist["Close"].iloc[-1])

        if prev_close and prev_close > 0:
            pct = ((latest - prev_close) / prev_close) * 100
        else:
            daily_closes = hist["Close"].resample("D").last().dropna()
            if len(daily_closes) >= 2:
                prev = daily_closes.iloc[-2]
                pct = ((latest - prev) / prev) * 100
            elif len(hist) >= 2:
                prev = float(hist["Close"].iloc[0])
                pct = ((latest - prev) / prev) * 100 if prev else 0.0
            else:
                pct = 0.0

        return latest, pct, hist
    except Exception as e:
        logger.debug(f"yfinance error for {ticker}: {e}")
        return None, None, None


def _fivepaisa_headers():
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


def fetch_gift_nifty_5paisa():
    """Scrape live Gift Nifty quote from 5paisa.com."""
    url = "https://www.5paisa.com/share-market-today/gift-nifty"
    try:
        resp = requests.get(url, headers=_fivepaisa_headers(), timeout=15)
        if resp.status_code != 200:
            logger.warning(f"5paisa Gift Nifty page returned status {resp.status_code}")
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        prc_block = soup.select_one(".market--prc")
        if not prc_block:
            logger.warning("5paisa Gift Nifty price block not found")
            return None

        big = prc_block.select_one(".prc-bigtext")
        small = prc_block.select_one(".prc-smalltext")
        price = None
        if big:
            price_text = big.get_text(strip=True)
            if small:
                price_text += small.get_text(strip=True)
            price = _parse_number_text(price_text)

        pct = None
        change_pts = None
        pct_label = prc_block.select_one('[class*="prc--percentage"]')
        if pct_label:
            for span in pct_label.find_all("span"):
                txt = span.get_text(strip=True)
                if not txt:
                    continue
                if "%" in txt:
                    pct = _parse_number_text(txt)
                elif txt[0] in "+-":
                    change_pts = _parse_number_text(txt)

        as_of = ""
        date_el = prc_block.select_one(".market--prc--date")
        if date_el:
            as_of = date_el.get_text(" ", strip=True).replace("As on", "").strip()

        day_low = day_high = open_price = prev_close = None
        for range_block in soup.select(".stock-page__range"):
            text = range_block.get_text(" ", strip=True)
            if "Day Low" in text and day_low is None:
                parts = text.split("Day High")
                day_low = _parse_number_text(parts[0].replace("Day Low", "").strip())
                if len(parts) > 1:
                    day_high = _parse_number_text(parts[1].strip())
            elif "52-week Low" in text:
                continue

        volume_block = soup.select_one(".stock-page__valume")
        if volume_block:
            vol_text = volume_block.get_text(" ", strip=True)
            if "Open Price" in vol_text:
                open_price = _parse_number_text(vol_text.split("Open Price", 1)[1].split("Previous Close", 1)[0])
            if "Previous Close" in vol_text:
                prev_part = vol_text.split("Previous Close", 1)[1]
                prev_close = _parse_number_text(prev_part.split("1W Returns", 1)[0])

        if price is None:
            return None

        if pct is None and prev_close and prev_close > 0:
            pct = ((price - prev_close) / prev_close) * 100
        if change_pts is None and prev_close is not None:
            change_pts = price - prev_close

        return {
            "price": price,
            "pct": pct,
            "change_pts": change_pts,
            "open": open_price,
            "prev_close": prev_close,
            "day_low": day_low,
            "day_high": day_high,
            "as_of": as_of,
            "source": "5paisa.com",
        }
    except Exception as e:
        logger.error(f"Error scraping Gift Nifty from 5paisa: {e}")
        return None


def fetch_5paisa_global_indices():
    """Scrape global index quotes from the Gift Nifty page's indices table."""
    url = "https://www.5paisa.com/share-market-today/gift-nifty"
    name_map = {
        "S&P ASX 200": "ASX 200 (Australia)",
        "Shanghai Composite": "Shanghai (China)",
        "DAX": "DAX 40 (Germany)",
        "CAC 40": "CAC 40 (France)",
        "FTSE 100": "FTSE 100 (UK)",
        "Hang Seng": "Hang Seng (HK)",
        "Nikkei 225": "Nikkei 225 (Japan)",
        "Taiwan Index": "Taiwan Weighted",
        "Dow Jones": "Dow Jones",
        "Nasdaq Composite": "Nasdaq Composite",
        "S&P": "S&P 500",
    }
    try:
        resp = requests.get(url, headers=_fivepaisa_headers(), timeout=15)
        if resp.status_code != 200:
            return {}

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table")
        if not table:
            return {}

        results = {}
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            raw_name = cells[0].get_text(strip=True)
            mapped = name_map.get(raw_name)
            if not mapped:
                continue
            price = _parse_number_text(cells[1].get_text(strip=True))
            change_text = cells[2].get_text(" ", strip=True)
            pct = None
            if "(" in change_text and ")" in change_text:
                pct = _parse_number_text(change_text.split("(", 1)[1].split(")", 1)[0])
            if price is not None:
                results[mapped] = {"price": price, "pct": pct, "hist": None, "symbol": raw_name, "source": "5paisa.com"}
        return results
    except Exception as e:
        logger.error(f"Error scraping 5paisa global indices: {e}")
        return {}


_OILPRICE_CHARTS_URL = "https://oilprice.com/oil-price-charts/"
_OILPRICE_ENERGY_SYMBOLS = ("WTI Crude", "Brent Crude", "Natural Gas")


def _parse_oilprice_pct_cell(text: str) -> float | None:
    """Parse '-0.82% (11-Minute Delay)' -> -0.82."""
    if not text:
        return None
    return _parse_number_text(str(text).split("%", 1)[0])


def fetch_oilprice_energy_quotes() -> dict[str, dict]:
    """WTI, Brent, and Natural Gas — last / change / % from oilprice.com charts."""
    out: dict[str, dict] = {}
    targets = set(_OILPRICE_ENERGY_SYMBOLS)
    try:
        resp = requests.get(
            _OILPRICE_CHARTS_URL,
            headers={"User-Agent": _NSE_UA, "Accept": "text/html"},
            timeout=20,
        )
        if resp.status_code != 200:
            return out
        soup = BeautifulSoup(resp.text, "html.parser")
        for tr in soup.select("table tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(cells) < 4:
                continue
            if cells[0] in targets:
                name, last_i, chg_i, pct_i = cells[0], 1, 2, 3
            elif len(cells) > 1 and cells[1] in targets:
                name, last_i, chg_i, pct_i = cells[1], 2, 3, 4
            else:
                continue
            if name in out:
                continue
            last = _parse_number_text(cells[last_i])
            change = _parse_number_text(cells[chg_i])
            pct = _parse_oilprice_pct_cell(cells[pct_i] if len(cells) > pct_i else "")
            if last is None:
                continue
            out[name] = {
                "price": last,
                "change": change,
                "pct": pct,
                "symbol": name,
                "source": "oilprice.com",
            }
    except Exception as e:
        logger.error(f"Oilprice.com energy scrape error: {e}")
    return out


# ─── Market Data Fetcher ────────────────────────────────────────────────────

def fetch_all_market_data():
    """Fetch live market data for all global instruments."""
    data = {}
    tickers = dict(MARKET_DISPLAY_YF)
    for name, sym in tickers.items():
        price, pct, hist = get_yf_data(sym)
        data[name] = {"price": price, "pct": pct, "hist": hist, "symbol": sym, "source": "yahoo"}
        time.sleep(0.03)

    gift_data = fetch_gift_nifty_5paisa()
    if gift_data and gift_data.get("price") is not None:
        data["Gift Nifty"] = {
            "price": gift_data["price"],
            "pct": gift_data.get("pct"),
            "hist": None,
            "symbol": "GIFTNIFTY",
            "source": "5paisa.com",
            "change_pts": gift_data.get("change_pts"),
            "open": gift_data.get("open"),
            "prev_close": gift_data.get("prev_close"),
            "day_low": gift_data.get("day_low"),
            "day_high": gift_data.get("day_high"),
            "as_of": gift_data.get("as_of"),
        }

    fivepaisa_indices = fetch_5paisa_global_indices()
    for name, idx_data in fivepaisa_indices.items():
        if idx_data.get("price") is not None:
            existing = data.get(name, {})
            merged = {**existing, **idx_data}
            # 5paisa only supplies live quotes — keep Yahoo intraday history for mini charts
            if idx_data.get("hist") is None and existing.get("hist") is not None:
                merged["hist"] = existing["hist"]
            data[name] = merged

    for name, quote in fetch_oilprice_energy_quotes().items():
        data[name] = {
            "price": quote.get("price"),
            "pct": quote.get("pct"),
            "change_pts": quote.get("change"),
            "hist": None,
            "symbol": quote.get("symbol", name),
            "source": "oilprice.com",
        }

    return data


# ─── NSE / Groww Market Data (Options, FII/DII, Turnover, Delivery) ─────────

GROWW_BASE = "https://api.groww.in"
_NSE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_NSE_WARM_PATHS = ("/option-chain", "/market-data/live-equity-market")
_NSE_API_TIMEOUT = 25


class NseBreadthUnavailable(Exception):
    """NSE allIndices fetch failed — raised so Streamlit does not cache a miss."""


def _warm_nse_session(session: requests.Session, referer_path: str = "/option-chain") -> bool:
    """Establish NSE cookies; try fallback paths if the primary page is slow or blocked."""
    paths: list[str] = []
    for path in (referer_path, *_NSE_WARM_PATHS):
        if path and path not in paths:
            paths.append(path)
    session.headers.update({
        "User-Agent": _NSE_UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    for path in paths:
        session.headers["Referer"] = f"https://www.nseindia.com{path}"
        try:
            resp = session.get(f"https://www.nseindia.com{path}", timeout=12)
            if resp.status_code == 200:
                time.sleep(0.5)
                return True
        except requests.RequestException as e:
            logger.warning(f"NSE warm failed ({path}): {e}")
    logger.error("NSE session warm failed on all paths")
    return False


def _parse_option_chain_payload(raw: dict, source: str = "NSE") -> dict | None:
    """Normalize NSE option-chain JSON (v3 or legacy) into a standard dict."""
    records = raw.get("records", {})
    filtered = raw.get("filtered", {})
    if not records or not filtered:
        return None

    underlying_value = records.get("underlyingValue", 0)
    timestamp = records.get("timestamp", "")
    expiry_dates = records.get("expiryDates", [])
    ce_data = filtered.get("CE", {})
    pe_data = filtered.get("PE", {})
    all_data = filtered.get("data", [])

    total_call_oi = ce_data.get("totOI", 0)
    total_put_oi = pe_data.get("totOI", 0)
    total_call_vol = ce_data.get("totVol", 0)
    total_put_vol = pe_data.get("totVol", 0)

    strikes = []
    for item in all_data:
        strike = item.get("strikePrice", 0)
        ce = item.get("CE") or {}
        pe = item.get("PE") or {}
        strikes.append({
            "strike": strike,
            "ce_oi": ce.get("openInterest", 0),
            "ce_chg_oi": ce.get("changeinOpenInterest", 0),
            "ce_vol": ce.get("totalTradedVolume", 0),
            "ce_iv": ce.get("impliedVolatility", 0),
            "ce_ltp": ce.get("lastPrice", 0),
            "pe_oi": pe.get("openInterest", 0),
            "pe_chg_oi": pe.get("changeinOpenInterest", 0),
            "pe_vol": pe.get("totalTradedVolume", 0),
            "pe_iv": pe.get("impliedVolatility", 0),
            "pe_ltp": pe.get("lastPrice", 0),
        })

    pcr_oi = round(total_put_oi / total_call_oi, 4) if total_call_oi > 0 else 0
    pcr_vol = round(total_put_vol / total_call_vol, 4) if total_call_vol > 0 else 0
    max_pain = _calculate_max_pain(strikes, underlying_value)

    return {
        "underlying": underlying_value,
        "timestamp": timestamp,
        "expiry_dates": expiry_dates,
        "current_expiry": expiry_dates[0] if expiry_dates else "",
        "total_call_oi": total_call_oi,
        "total_put_oi": total_put_oi,
        "total_call_vol": total_call_vol,
        "total_put_vol": total_put_vol,
        "pcr_oi": pcr_oi,
        "pcr_vol": pcr_vol,
        "max_pain": max_pain,
        "strikes": strikes,
        "top_call_oi": sorted(strikes, key=lambda x: x["ce_oi"], reverse=True)[:5],
        "top_put_oi": sorted(strikes, key=lambda x: x["pe_oi"], reverse=True)[:5],
        "top_call_chg_oi": sorted(strikes, key=lambda x: x["ce_chg_oi"], reverse=True)[:5],
        "top_put_chg_oi": sorted(strikes, key=lambda x: x["pe_chg_oi"], reverse=True)[:5],
        "source": source,
    }


def _fetch_nse_option_chain_v3(symbol: str = "NIFTY") -> dict | None:
    """Fetch options via NSE option-chain-v3 API (replaces deprecated option-chain-indices)."""
    try:
        session = requests.Session()
        _warm_nse_session(session, "/option-chain")

        info_url = (
            "https://www.nseindia.com/api/option-chain-contract-info"
            f"?symbol={symbol}&instrument=Indices"
        )
        info_resp = session.get(info_url, timeout=15)
        if info_resp.status_code != 200:
            logger.warning(f"NSE contract-info status {info_resp.status_code}")
            return None

        info = info_resp.json()
        expiry_dates = info.get("expiryDates") or []
        if not expiry_dates:
            return None

        nearest_expiry = expiry_dates[0]
        oc_url = (
            "https://www.nseindia.com/api/option-chain-v3"
            f"?type=Indices&symbol={symbol}&expiry={nearest_expiry}"
        )
        resp = session.get(oc_url, timeout=20)
        if resp.status_code != 200 or len(resp.text) < 50:
            logger.warning(f"NSE option-chain-v3 status {resp.status_code}, len={len(resp.text)}")
            return None

        parsed = _parse_option_chain_payload(resp.json(), source="NSE")
        if parsed and not parsed.get("current_expiry"):
            parsed["current_expiry"] = nearest_expiry
        return parsed
    except Exception as e:
        logger.error(f"NSE option-chain-v3 error: {e}")
        return None


def _fetch_groww_option_chain(symbol: str, api_token: str, exchange: str = "NSE") -> dict | None:
    """Fallback: fetch full option chain from Groww API when NSE is blocked/unavailable."""
    if not api_token or not api_token.strip():
        return None
    try:
        headers = {"Authorization": f"Bearer {api_token.strip()}", "Accept": "application/json"}
        symbol = symbol.upper().strip()
        exchange = exchange.upper().strip()

        exp_resp = requests.get(
            f"{GROWW_BASE}/v1/historical/expiries",
            headers=headers,
            params={"exchange": exchange, "underlying_symbol": symbol},
            timeout=12,
        )
        if exp_resp.status_code != 200:
            return None
        expiry_dates = exp_resp.json().get("expiryDates") or []
        if not expiry_dates:
            return None
        nearest_expiry = min(expiry_dates)

        oc_resp = requests.get(
            f"{GROWW_BASE}/v1/option-chain/exchange/{exchange}/underlying/{symbol}",
            headers=headers,
            params={"expiry_date": nearest_expiry},
            timeout=15,
        )
        if oc_resp.status_code != 200:
            return None
        oc_data = oc_resp.json()
        strikes_raw = oc_data.get("strikes") or {}

        strikes = []
        total_call_oi = total_put_oi = total_call_vol = total_put_vol = 0
        for strike_key, legs in strikes_raw.items():
            try:
                strike = float(strike_key)
            except (TypeError, ValueError):
                continue
            ce = legs.get("CE") or {}
            pe = legs.get("PE") or {}
            ce_oi = ce.get("open_interest", 0) or 0
            pe_oi = pe.get("open_interest", 0) or 0
            ce_vol = ce.get("volume", 0) or ce.get("total_traded_volume", 0) or 0
            pe_vol = pe.get("volume", 0) or pe.get("total_traded_volume", 0) or 0
            total_call_oi += ce_oi
            total_put_oi += pe_oi
            total_call_vol += ce_vol
            total_put_vol += pe_vol
            strikes.append({
                "strike": strike,
                "ce_oi": ce_oi,
                "ce_chg_oi": ce.get("change_in_oi", ce.get("change_in_open_interest", 0)) or 0,
                "ce_vol": ce_vol,
                "ce_iv": ce.get("implied_volatility", ce.get("iv", 0)) or 0,
                "ce_ltp": ce.get("ltp", ce.get("last_price", 0)) or 0,
                "pe_oi": pe_oi,
                "pe_chg_oi": pe.get("change_in_oi", pe.get("change_in_open_interest", 0)) or 0,
                "pe_vol": pe_vol,
                "pe_iv": pe.get("implied_volatility", pe.get("iv", 0)) or 0,
                "pe_ltp": pe.get("ltp", pe.get("last_price", 0)) or 0,
            })

        if not strikes:
            return None

        underlying = oc_data.get("underlying_value") or oc_data.get("underlying_ltp") or 0
        pcr_oi = round(total_put_oi / total_call_oi, 4) if total_call_oi > 0 else 0
        pcr_vol = round(total_put_vol / total_call_vol, 4) if total_call_vol > 0 else 0
        max_pain = _calculate_max_pain(strikes, underlying or strikes[0]["strike"])

        return {
            "underlying": underlying,
            "timestamp": nearest_expiry,
            "expiry_dates": expiry_dates,
            "current_expiry": nearest_expiry,
            "total_call_oi": total_call_oi,
            "total_put_oi": total_put_oi,
            "total_call_vol": total_call_vol,
            "total_put_vol": total_put_vol,
            "pcr_oi": pcr_oi,
            "pcr_vol": pcr_vol,
            "max_pain": max_pain,
            "strikes": strikes,
            "top_call_oi": sorted(strikes, key=lambda x: x["ce_oi"], reverse=True)[:5],
            "top_put_oi": sorted(strikes, key=lambda x: x["pe_oi"], reverse=True)[:5],
            "top_call_chg_oi": sorted(strikes, key=lambda x: x["ce_chg_oi"], reverse=True)[:5],
            "top_put_chg_oi": sorted(strikes, key=lambda x: x["pe_chg_oi"], reverse=True)[:5],
            "source": "Groww",
        }
    except Exception as e:
        logger.error(f"Groww option chain error: {e}")
        return None


def fetch_nse_option_chain(symbol="NIFTY", groww_token: str = ""):
    """
    Fetch NIFTY/BANKNIFTY options chain — NSE v3 API first, Groww API fallback.
    Returns parsed option chain data dict or None on failure.
    """
    data = _fetch_nse_option_chain_v3(symbol)
    if data:
        return data
    groww_data = _fetch_groww_option_chain(symbol, groww_token)
    if groww_data:
        return groww_data
    # Legacy endpoint last resort (may still work in some environments)
    try:
        session = requests.Session()
        _warm_nse_session(session, "/option-chain")
        legacy_url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
        resp = session.get(legacy_url, timeout=15)
        if resp.status_code == 200 and len(resp.text) > 50:
            return _parse_option_chain_payload(resp.json(), source="NSE-legacy")
    except Exception as e:
        logger.error(f"Legacy NSE option chain error: {e}")
    return None


_STOCKEDGE_FII_API = (
    "https://api.stockedge.com/Api/FIIDashboardApi/GetFIIDIIProvisional"
)


def _parse_stockedge_daily_dates(rows: list[dict]) -> list[dict]:
    """Attach calendar dates to StockEdge daily rows (input is newest-first)."""
    parsed = []
    year = datetime.now().year
    prev_month = None
    for row in rows:
        date_text = (row.get("DateText") or "").strip()
        if not date_text:
            continue
        try:
            dt = datetime.strptime(f"{date_text} {year}", "%b %d %Y")
        except ValueError:
            continue
        if prev_month is not None and dt.month > prev_month:
            year -= 1
            dt = datetime.strptime(f"{date_text} {year}", "%b %d %Y")
        prev_month = dt.month
        parsed.append({
            "date": dt.strftime("%d-%b-%Y"),
            "net_cr": float(row.get("NetValue", 0) or 0),
            "_sort": dt,
        })
    return parsed


def _fetch_stockedge_cash_history(trading_days: int = 30) -> list[dict]:
    """Fetch CM provisional FII/DII daily net flows from StockEdge."""
    headers = {"User-Agent": _NSE_UA, "Accept": "application/json"}
    params = {"TimeSpan": "D", "lang": "en"}
    fii_resp = requests.get(
        _STOCKEDGE_FII_API, params={**params, "FiiDiiType": "fii"},
        headers=headers, timeout=20,
    )
    dii_resp = requests.get(
        _STOCKEDGE_FII_API, params={**params, "FiiDiiType": "dii"},
        headers=headers, timeout=20,
    )
    if fii_resp.status_code != 200 or dii_resp.status_code != 200:
        return []
    fii_rows = fii_resp.json() if fii_resp.text else []
    dii_rows = dii_resp.json() if dii_resp.text else []
    if not isinstance(fii_rows, list) or not isinstance(dii_rows, list):
        return []

    fii_by_date = {r["date"]: r for r in _parse_stockedge_daily_dates(fii_rows)}
    dii_by_date = {r["date"]: r for r in _parse_stockedge_daily_dates(dii_rows)}
    common_dates = sorted(
        set(fii_by_date) & set(dii_by_date),
        key=lambda d: fii_by_date[d]["_sort"],
        reverse=True,
    )[:trading_days]
    history = []
    for date in reversed(common_dates):
        fii = fii_by_date[date]
        dii = dii_by_date[date]
        history.append({
            "date": date,
            "fii_net": fii["net_cr"],
            "dii_net": dii["net_cr"],
        })
    return history


def _fetch_nse_fii_dii_latest() -> dict | None:
    """Fetch latest-day FII / DII cash buy-sell from NSE."""
    session = requests.Session()
    _warm_nse_session(session, "/market-data/live-equity-market")
    resp = session.get("https://www.nseindia.com/api/fiidiiTradeReact", timeout=15)
    if resp.status_code != 200:
        return None
    rows = resp.json()
    if not isinstance(rows, list) or not rows:
        return None
    result = {"date": None, "fii": None, "dii": None}
    for row in rows:
        cat = row.get("category", "").upper()
        entry = {
            "buy_cr": float(row.get("buyValue", 0) or 0),
            "sell_cr": float(row.get("sellValue", 0) or 0),
            "net_cr": float(row.get("netValue", 0) or 0),
            "date": row.get("date", ""),
        }
        result["date"] = entry["date"] or result["date"]
        if cat in ("FII/FPI", "FII"):
            result["fii"] = entry
        elif cat == "DII":
            result["dii"] = entry
    return result if result["fii"] or result["dii"] else None


def fetch_nse_fii_dii() -> dict | None:
    """
    Fetch FII / DII cash-market flows.
    Latest buy/sell from NSE; 30-day CM provisional net history from StockEdge.
    """
    try:
        result = {
            "date": None,
            "fii": None,
            "dii": None,
            "history": [],
            "source": "stockedge.com",
        }
        nse = _fetch_nse_fii_dii_latest()
        if nse:
            result["date"] = nse.get("date")
            result["fii"] = nse.get("fii")
            result["dii"] = nse.get("dii")
            result["source"] = "NSE + stockedge.com"

        history = _fetch_stockedge_cash_history(30)
        if history:
            result["history"] = history
            if not result["date"]:
                result["date"] = history[-1]["date"]
            if not result["fii"] and history:
                latest = history[-1]
                result["fii"] = {"buy_cr": 0, "sell_cr": 0, "net_cr": latest["fii_net"], "date": latest["date"]}
            if not result["dii"] and history:
                latest = history[-1]
                result["dii"] = {"buy_cr": 0, "sell_cr": 0, "net_cr": latest["dii_net"], "date": latest["date"]}

        if result["fii"] or result["dii"] or result["history"]:
            return result
        return None
    except Exception as e:
        logger.error(f"FII/DII fetch error: {e}")
        return None


def _parse_bulk_block_rows(payload: object) -> list[dict]:
    """Normalize NSE bulk/block/large-deal JSON into flat rows."""
    rows: list[dict] = []
    if not payload:
        return rows
    if isinstance(payload, list):
        data = payload
    elif isinstance(payload, dict):
        data = (
            payload.get("data")
            or payload.get("bulkBlockDeals")
            or payload.get("BULK_DEALS")
            or payload.get("BLOCK_DEALS")
            or []
        )
        if isinstance(data, dict):
            data = list(data.values())
    else:
        return rows
    for item in data:
        if not isinstance(item, dict):
            continue
        sym = (
            item.get("symbol")
            or item.get("SYMBOL")
            or item.get("secName")
            or item.get("securityName")
            or ""
        ).upper().strip()
        if not sym:
            continue
        try:
            price = float(
                item.get("tradePrice")
                or item.get("ltp")
                or item.get("price")
                or item.get("TRADE_PRICE")
                or item.get("AVG_PRICE")
                or 0
            )
        except (TypeError, ValueError):
            price = 0.0
        side = item.get("buySell") or item.get("dealType") or ""
        if not side and item.get("BUY_QTY"):
            side = "BUY"
        elif not side and item.get("SELL_QTY"):
            side = "SELL"
        if isinstance(side, str):
            sl = side.lower()
            if "buy" in sl:
                side = "BUY"
            elif "sell" in sl:
                side = "SELL"
        rows.append({
            "symbol": sym.replace(".NS", ""),
            "price": price,
            "qty": item.get("quantity") or item.get("qty") or item.get("QTY_TRADED") or 0,
            "side": str(side).upper() if side else "",
            "deal_type": item.get("dealType") or item.get("type") or "deal",
            "client": item.get("clientName") or item.get("CLIENT_NAME") or "",
        })
    return rows


def fetch_nse_bulk_block_deals() -> list[dict]:
    """Bulk / block / large deals from NSE (same-day institutional footprints)."""
    session = requests.Session()
    if not _warm_nse_session(session, "/market-data/bulk-block-deals"):
        return []
    urls = (
        "https://www.nseindia.com/api/snapshot-capital-market-largedeal?index=volume",
        "https://www.nseindia.com/api/block-deal-watch?index=volume",
    )
    seen: set[tuple] = set()
    out: list[dict] = []
    for url in urls:
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                continue
            for row in _parse_bulk_block_rows(resp.json()):
                key = (row["symbol"], row.get("price"), row.get("side"))
                if key in seen:
                    continue
                seen.add(key)
                out.append(row)
        except Exception as e:
            logger.warning(f"Bulk/block deals fetch failed ({url}): {e}")
    return out


_NIFTY_BREADTH_GROUP_ORDER = (
    "INDICES ELIGIBLE IN DERIVATIVES",
    "BROAD MARKET INDICES",
    "SECTORAL INDICES",
    "THEMATIC INDICES",
    "STRATEGY INDICES",
)
_NIFTY_BREADTH_GROUP_LABELS = {
    "INDICES ELIGIBLE IN DERIVATIVES": "F&O / Derivatives",
    "BROAD MARKET INDICES": "Broad Market",
    "SECTORAL INDICES": "Sectoral",
    "THEMATIC INDICES": "Thematic",
    "STRATEGY INDICES": "Strategy",
}
_AI_BREADTH_GROUPS = frozenset({
    "INDICES ELIGIBLE IN DERIVATIVES",
    "BROAD MARKET INDICES",
})
_FO_INDICES_FOR_STOCK_MOVERS = (
    "NIFTY 50",
    "NIFTY NEXT 50",
    "NIFTY BANK",
    "NIFTY FINANCIAL SERVICES",
    "NIFTY MIDCAP SELECT",
)
_MONTHLY_STOCK_MAX_CONSTITUENTS: int | None = None  # no constituent cap
_MONTHLY_MOVERS_TOP_N: int | None = None  # return full ranked lists


def _fetch_nse_index_constituent_symbols(index_name: str) -> list[str]:
    """Return EQ constituent symbols: niftyindices CSV / static lists, then NSE API."""
    symbols = get_index_constituent_symbols(index_name)
    if symbols:
        return symbols
    try:
        session = requests.Session()
        _warm_nse_session(session, "/market-data/live-equity-market")
        url = f"https://www.nseindia.com/api/equity-stockIndices?index={quote(index_name)}"
        resp = session.get(url, timeout=20)
        if resp.status_code != 200:
            return []
        symbols = []
        for item in resp.json().get("data", []):
            symbol = (item.get("symbol") or "").strip()
            if not symbol or symbol.upper() == index_name.upper():
                continue
            if item.get("priority") == 0:
                continue
            symbols.append(symbol)
        return symbols
    except Exception as e:
        logger.error(f"Index constituents fetch error ({index_name}): {e}")
        return []


def _monthly_return_from_close(close_series) -> float | None:
    if close_series is None:
        return None
    closes = close_series.dropna()
    if len(closes) < 2:
        return None
    return float((closes.iloc[-1] / closes.iloc[0] - 1) * 100)


def _fetch_monthly_returns_for_symbols(symbols: list[str]) -> list[dict]:
    """Compute ~1-month % return for NSE symbols via yfinance."""
    symbols = [s for s in symbols if s]
    if _MONTHLY_STOCK_MAX_CONSTITUENTS is not None and _MONTHLY_STOCK_MAX_CONSTITUENTS > 0:
        symbols = symbols[:_MONTHLY_STOCK_MAX_CONSTITUENTS]
    if not symbols:
        return []
    tickers = [stock_symbol_to_yf(s) for s in symbols]
    results = []
    try:
        if len(tickers) == 1:
            df = yf.download(
                tickers[0], period="1mo", interval="1d",
                progress=False, auto_adjust=True,
            )
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0] for c in df.columns]
                closes = df.get("Close")
                pct = _monthly_return_from_close(closes)
                if pct is not None:
                    clean = closes.dropna()
                    last = float(clean.iloc[-1]) if len(clean) else None
                    results.append({"symbol": symbols[0], "pct": pct, "last": last})
            return results

        raw = yf.download(
            tickers, period="1mo", interval="1d",
            progress=False, auto_adjust=True, threads=True,
        )
        if raw.empty:
            return results
        if isinstance(raw.columns, pd.MultiIndex):
            for sym in symbols:
                tkr = stock_symbol_to_yf(sym)
                if tkr in raw.columns.get_level_values(0):
                    closes = raw[tkr]["Close"]
                    pct = _monthly_return_from_close(closes)
                    if pct is not None:
                        clean = closes.dropna()
                        last = float(clean.iloc[-1]) if len(clean) else None
                        results.append({"symbol": sym, "pct": pct, "last": last})
        else:
            closes = raw.get("Close")
            pct = _monthly_return_from_close(closes)
            if pct is not None:
                clean = closes.dropna()
                last = float(clean.iloc[-1]) if len(clean) else None
                results.append({"symbol": symbols[0], "pct": pct, "last": last})
    except Exception as e:
        logger.error(f"Monthly stock returns error: {e}")
    return results


def fetch_index_monthly_stock_movers(index_name: str, top_n: int | None = _MONTHLY_MOVERS_TOP_N) -> dict | None:
    """Stock gainers/losers over ~1 month for an index's constituents (full list by default)."""
    symbols = _fetch_nse_index_constituent_symbols(index_name)
    if not symbols:
        return None
    if (
        _MONTHLY_STOCK_MAX_CONSTITUENTS is not None
        and _MONTHLY_STOCK_MAX_CONSTITUENTS > 0
        and len(symbols) > _MONTHLY_STOCK_MAX_CONSTITUENTS
    ):
        return {
            "skipped": True,
            "constituent_count": len(symbols),
            "gainers": [],
            "losers": [],
        }
    stocks = _fetch_monthly_returns_for_symbols(symbols)
    if not stocks:
        return None
    gainers = sorted(stocks, key=lambda x: x["pct"], reverse=True)
    losers = sorted(stocks, key=lambda x: x["pct"])
    if top_n is not None and top_n > 0:
        gainers = gainers[:top_n]
        losers = losers[:top_n]
    return {"gainers": gainers, "losers": losers, "skipped": False}


def fetch_nse_index_stock_movers(index_name: str, top_n: int | None = None) -> dict | None:
    """Fetch stock gainers/losers for an NSE index from equity-stockIndices (full list by default)."""
    try:
        session = requests.Session()
        _warm_nse_session(session, "/market-data/live-equity-market")
        url = f"https://www.nseindia.com/api/equity-stockIndices?index={quote(index_name)}"
        resp = session.get(url, timeout=20)
        if resp.status_code != 200:
            return None
        stocks = []
        for item in resp.json().get("data", []):
            symbol = (item.get("symbol") or "").strip()
            if not symbol or symbol.upper() == index_name.upper():
                continue
            if item.get("priority") == 0:
                continue
            pct = item.get("pChange", item.get("percentChange"))
            if pct is None:
                continue
            stocks.append({
                "symbol": symbol,
                "pct": float(pct),
                "last": float(item.get("lastPrice", item.get("ltp", 0)) or 0),
            })
        if not stocks:
            return None
        gainers = sorted(stocks, key=lambda x: x["pct"], reverse=True)
        losers = sorted(stocks, key=lambda x: x["pct"])
        if top_n is not None and top_n > 0:
            gainers = gainers[:top_n]
            losers = losers[:top_n]
        return {"gainers": gainers, "losers": losers}
    except Exception as e:
        logger.error(f"Index stock movers fetch error ({index_name}): {e}")
        return None


def _parse_nse_all_indices_payload(raw: dict) -> dict | None:
    """Parse NSE allIndices JSON into breadth + monthly structures."""
    indices = {}
    monthly: dict[str, dict] = {}
    groups: dict[str, list[str]] = {g: [] for g in _NIFTY_BREADTH_GROUP_ORDER}
    monthly_groups: dict[str, list[str]] = {g: [] for g in _NIFTY_BREADTH_GROUP_ORDER}
    for item in raw.get("data", []):
        name = (item.get("index") or "").strip()
        if not name.upper().startswith("NIFTY"):
            continue
        group = item.get("key") or "OTHER"
        pct_30d = item.get("perChange30d")
        if pct_30d is not None:
            monthly[name] = {
                "pct_30d": float(pct_30d),
                "last": float(item.get("last", 0) or 0),
                "group": group,
                "date_30d_ago": item.get("date30dAgo", ""),
            }
            if group in monthly_groups:
                monthly_groups[group].append(name)
        if item.get("advances") is None or item.get("declines") is None:
            continue
        indices[name] = {
            "advances": int(item.get("advances", 0) or 0),
            "declines": int(item.get("declines", 0) or 0),
            "unchanged": int(item.get("unchanged", 0) or 0),
            "last": float(item.get("last", 0) or 0),
            "pct": float(item.get("percentChange", 0) or 0),
            "trade_date": item.get("previousDay", ""),
            "group": group,
        }
        if group in groups:
            groups[group].append(name)
    if not indices and not monthly:
        return None
    for names in groups.values():
        names.sort()
    for names in monthly_groups.values():
        names.sort()
    return {
        "indices": indices,
        "groups": groups,
        "monthly": monthly,
        "monthly_groups": monthly_groups,
    }


def _fetch_nse_market_breadth_raw() -> dict | None:
    """Fetch advances/declines for all Nifty indices from NSE allIndices (no cache)."""
    last_error = ""
    for attempt in range(3):
        try:
            session = requests.Session()
            warmed = _warm_nse_session(session, "/option-chain")
            if not warmed:
                session.headers.update({
                    "User-Agent": _NSE_UA,
                    "Accept": "application/json, text/plain, */*",
                    "Referer": "https://www.nseindia.com/option-chain",
                })
            resp = session.get(
                "https://www.nseindia.com/api/allIndices",
                timeout=_NSE_API_TIMEOUT,
            )
            if resp.status_code != 200:
                last_error = f"allIndices HTTP {resp.status_code}"
                time.sleep(0.8 * (attempt + 1))
                continue
            parsed = _parse_nse_all_indices_payload(resp.json())
            if parsed:
                return parsed
            last_error = "allIndices returned no Nifty breadth rows"
        except Exception as e:
            last_error = str(e)
            logger.error(f"Market breadth fetch error (attempt {attempt + 1}): {e}")
        time.sleep(0.8 * (attempt + 1))
    logger.error(f"Market breadth unavailable after retries: {last_error}")
    return None


def _fetch_nse_market_breadth_cached() -> dict:
    data = _fetch_nse_market_breadth_raw()
    if not data:
        raise NseBreadthUnavailable()
    return data


def fetch_nse_market_breadth() -> dict | None:
    """Fetch advances/declines for all Nifty indices with breadth from NSE allIndices."""
    try:
        return _fetch_nse_market_breadth_cached()
    except NseBreadthUnavailable:
        return None


def _noop_cache_clear() -> None:
    pass


if hasattr(_fetch_nse_market_breadth_cached, "clear"):
    fetch_nse_market_breadth.clear = _fetch_nse_market_breadth_cached.clear  # type: ignore[attr-defined]
else:
    fetch_nse_market_breadth.clear = _noop_cache_clear  # type: ignore[attr-defined]


def _parse_bhavcopy_eq_stocks(csv_text: str) -> list[dict]:
    """
    Parse NSE sec_bhavdata_full CSV into EQ stock rows.

    CSV columns (0-based):
    SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN, HIGH, LOW, LAST, CLOSE, AVG,
    TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER
    """
    stocks = []
    for line in csv_text.strip().splitlines()[1:]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 15:
            continue
        symbol, series = parts[0], parts[1]
        if series != "EQ":
            continue
        try:
            qty = int(float(parts[10] or 0))
            turnover_lacs = float(parts[11] or 0)
            deliv_qty = int(float(parts[13] or 0))
            deliv_per = float(parts[14] or 0)
            close_px = float(parts[8] or 0)
        except (ValueError, IndexError):
            continue
        if qty <= 0:
            continue
        stocks.append({
            "symbol": symbol,
            "qty": qty,
            "turnover_lacs": turnover_lacs,
            "deliv_qty": deliv_qty,
            "deliv_per": deliv_per,
            "close": close_px,
        })
    return stocks


def _summarize_bhavcopy_stocks(stocks: list[dict], trade_date: str) -> dict | None:
    """Build turnover/delivery snapshot dict from parsed EQ rows."""
    if not stocks:
        return None
    total_turnover_lacs = sum(s["turnover_lacs"] for s in stocks)
    total_qty = sum(s["qty"] for s in stocks)
    total_deliv_qty = sum(s["deliv_qty"] for s in stocks)
    avg_deliv_per = (total_deliv_qty / total_qty * 100) if total_qty > 0 else 0
    liquid = [s for s in stocks if s["qty"] >= 100_000]
    return {
        "trade_date": trade_date,
        "total_turnover_cr": round(total_turnover_lacs / 100, 2),
        "total_stocks": len(stocks),
        "avg_delivery_pct": round(avg_deliv_per, 2),
        "high_delivery": sorted(liquid, key=lambda x: x["deliv_per"], reverse=True)[:10],
        "low_delivery": sorted(liquid, key=lambda x: x["deliv_per"])[:10],
        "high_turnover": sorted(liquid, key=lambda x: x["turnover_lacs"], reverse=True)[:10],
    }


def _fetch_bhavcopy_csv(session: requests.Session, dt: datetime.date) -> str | None:
    """Download one day's sec_bhavdata_full CSV from NSE archives."""
    ds = dt.strftime("%d%m%Y")
    url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ds}.csv"
    try:
        resp = session.get(url, timeout=20)
        if resp.status_code == 200 and len(resp.content) > 5000:
            return resp.text
    except Exception:
        pass
    return None


def fetch_nse_turnover_delivery() -> dict | None:
    """Latest cash-market turnover and delivery stats from NSE bhavcopy archive."""
    try:
        session = requests.Session()
        _warm_nse_session(session, "/market-data/live-equity-market")

        today = datetime.now().date()
        for offset in range(0, 10):
            dt = today - timedelta(days=offset)
            if dt.weekday() >= 5:
                continue
            csv_text = _fetch_bhavcopy_csv(session, dt)
            if csv_text:
                stocks = _parse_bhavcopy_eq_stocks(csv_text)
                return _summarize_bhavcopy_stocks(stocks, dt.strftime("%d-%b-%Y"))
        return None
    except Exception as e:
        logger.error(f"Turnover/delivery fetch error: {e}")
        return None


def fetch_nse_delivery_turnover_history(trading_days: int = 22) -> dict | None:
    """
    Fetch ~1 month of daily delivery % and turnover per symbol from NSE bhavcopy.
    Returns series sorted oldest → newest for trend charts.
    """
    try:
        session = requests.Session()
        _warm_nse_session(session, "/market-data/live-equity-market")

        series = []
        today = datetime.now().date()
        for offset in range(0, 45):
            if len(series) >= trading_days:
                break
            dt = today - timedelta(days=offset)
            if dt.weekday() >= 5:
                continue
            csv_text = _fetch_bhavcopy_csv(session, dt)
            if not csv_text:
                continue
            stocks = _parse_bhavcopy_eq_stocks(csv_text)
            if not stocks:
                continue
            by_symbol = {s["symbol"]: s for s in stocks}
            series.append({
                "date": dt.strftime("%d-%b-%Y"),
                "date_iso": dt.isoformat(),
                "stocks": by_symbol,
            })
            time.sleep(0.15)

        if len(series) < 5:
            return None
        series.reverse()
        return {"series": series, "trading_days": len(series)}
    except Exception as e:
        logger.error(f"Delivery/turnover history fetch error: {e}")
        return None


def _symbol_metric_series(history: dict, symbol: str, metric: str) -> tuple[list[str], list[float]]:
    """Extract dated metric values for one symbol from bhavcopy history."""
    dates, values = [], []
    for day in history.get("series") or []:
        row = (day.get("stocks") or {}).get(symbol)
        if row is None:
            continue
        val = row.get(metric)
        if val is None:
            continue
        dates.append(day["date"])
        values.append(float(val))
    return dates, values


def _classify_symbol_trends(
    history: dict,
    symbols: list[str],
    metric: str,
    *,
    min_points: int = 8,
) -> tuple[list[dict], list[dict]]:
    """Split symbols into increasing vs decreasing linear trends over the history window."""
    increasing, decreasing = [], []
    for sym in symbols:
        dates, values = _symbol_metric_series(history, sym, metric)
        if len(values) < min_points:
            continue
        x = np.arange(len(values), dtype=float)
        slope = float(np.polyfit(x, values, 1)[0])
        start_val, end_val = values[0], values[-1]
        pct_chg = ((end_val - start_val) / start_val * 100) if start_val else 0.0
        entry = {
            "symbol": sym,
            "dates": dates,
            "values": values,
            "slope": slope,
            "start": start_val,
            "end": end_val,
            "pct_chg": pct_chg,
        }
        if slope > 0:
            increasing.append(entry)
        elif slope < 0:
            decreasing.append(entry)
    increasing.sort(key=lambda e: e["slope"], reverse=True)
    decreasing.sort(key=lambda e: e["slope"])
    return increasing, decreasing


def _delivery_turnover_trend_chart_layout(fig: go.Figure, title: str, y_title: str, height: int = 300) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=13, color="#cbd5e1")),
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15, 23, 41, 0.8)",
        font=dict(color="#94a3b8", size=10),
        xaxis=dict(title="", gridcolor="#1e3a5f", tickangle=-45),
        yaxis=dict(title=y_title, gridcolor="#1e3a5f"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=55, r=15, t=55, b=70),
        hovermode="x unified",
    )
    return fig


_TREND_LINE_COLORS = [
    "#10b981", "#06b6d4", "#60a5fa", "#a78bfa", "#f59e0b",
    "#ef4444", "#f472b6", "#34d399", "#818cf8", "#fb923c",
]


def _render_symbol_trend_chart(entries: list[dict], title: str, y_title: str) -> None:
    """Plot multi-symbol 1-month line chart and summary table."""
    if not entries:
        st.caption("No symbols with enough history for a clear trend.")
        return
    fig = go.Figure()
    for i, e in enumerate(entries[:5]):
        color = _TREND_LINE_COLORS[i % len(_TREND_LINE_COLORS)]
        fig.add_trace(go.Scatter(
            x=e["dates"],
            y=e["values"],
            mode="lines+markers",
            name=e["symbol"],
            line=dict(color=color, width=2),
            marker=dict(size=4),
            hovertemplate=f"{e['symbol']}<br>%{{x}}<br>{y_title}: %{{y:.2f}}<extra></extra>",
        ))
    _delivery_turnover_trend_chart_layout(fig, title, y_title)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    rows = [{
        "Symbol": e["symbol"],
        "Start": e["start"],
        "Latest": e["end"],
        "Change %": e["pct_chg"],
    } for e in entries[:5]]
    fmt_rows = []
    for r in rows:
        if "Turnover" in y_title:
            fmt_rows.append({
                "Symbol": r["Symbol"],
                "Start (₹ L)": f"{r['Start']:,.0f}",
                "Latest · 1M Δ %": fmt_last_pct(r["Latest"], r["Change %"], decimals=0),
            })
        else:
            fmt_rows.append({
                "Symbol": r["Symbol"],
                "Start %": f"{r['Start']:.1f}",
                "Latest · 1M Δ %": fmt_last_pct(r["Latest"], r["Change %"], decimals=1),
            })
    st.dataframe(pd.DataFrame(fmt_rows), hide_index=True, width='stretch')


def _render_delivery_turnover_trend_section(
    history: dict,
    symbols: list[str],
    metric: str,
    section_title: str,
    y_title: str,
) -> None:
    """One collapsible block: increasing vs decreasing 1-month trends."""
    increasing, decreasing = _classify_symbol_trends(history, symbols, metric)
    st.markdown(f"**{section_title}**")
    col_up, col_dn = st.columns(2)
    with col_up:
        st.markdown("📈 **Increasing trend**")
        _render_symbol_trend_chart(
            increasing,
            f"{section_title} — Rising",
            y_title,
        )
    with col_dn:
        st.markdown("📉 **Decreasing trend**")
        _render_symbol_trend_chart(
            decreasing,
            f"{section_title} — Falling",
            y_title,
        )
    st.markdown("<div style='margin-bottom:12px;'></div>", unsafe_allow_html=True)


def _render_delivery_turnover_monthly_trends(turnover_delivery_data: dict, history: dict) -> None:
    """Render 1-month trend charts for high/low delivery and high turnover lists."""
    n_days = history.get("trading_days", len(history.get("series") or []))
    st.caption(
        f"Trends over last **{n_days} trading days** (NSE bhavcopy) for today's top-list symbols. "
        "Classification uses linear slope on daily delivery % or turnover (₹ Lacs)."
    )
    high_syms = [s["symbol"] for s in turnover_delivery_data.get("high_delivery", [])]
    low_syms = [s["symbol"] for s in turnover_delivery_data.get("low_delivery", [])]
    to_syms = [s["symbol"] for s in turnover_delivery_data.get("high_turnover", [])]

    _render_delivery_turnover_trend_section(
        history, high_syms, "deliv_per",
        "🔥 Highest Delivery % (liquid stocks)",
        "Delivery %",
    )
    _render_delivery_turnover_trend_section(
        history, low_syms, "deliv_per",
        "💨 Lowest Delivery % (speculative)",
        "Delivery %",
    )
    _render_delivery_turnover_trend_section(
        history, to_syms, "turnover_lacs",
        "💰 Highest Turnover (₹ Lacs)",
        "Turnover (₹ Lacs)",
    )


def _calculate_max_pain(strikes, underlying):
    """
    Calculate Max Pain — the strike price at which total loss to option buyers
    is maximum (i.e., option writers profit the most).
    """
    if not strikes:
        return underlying

    pain = {}
    for target_strike_data in strikes:
        target_strike = target_strike_data["strike"]
        total_pain = 0
        for s in strikes:
            strike = s["strike"]
            # Call buyers' pain at this target strike
            if strike < target_strike:
                total_pain += (target_strike - strike) * s["ce_oi"]
            # Put buyers' pain at this target strike
            if strike > target_strike:
                total_pain += (strike - target_strike) * s["pe_oi"]
        pain[target_strike] = total_pain

    if pain:
        return min(pain, key=pain.get)
    return underlying


def analyze_options_sentiment(option_data):
    """
    Analyze options data and produce a directional sentiment verdict.
    Returns dict with verdict, score, and reasoning points.
    """
    if not option_data:
        return {
            "verdict": "⚪ UNAVAILABLE",
            "verdict_color": "#94a3b8",
            "score": 0,
            "reasons": ["Options data not available — NSE may be unreachable or market is closed."]
        }

    pcr = option_data["pcr_oi"]
    max_pain = option_data["max_pain"]
    underlying = option_data["underlying"]
    total_call_oi = option_data["total_call_oi"]
    total_put_oi = option_data["total_put_oi"]
    top_call_oi = option_data["top_call_oi"]
    top_put_oi = option_data["top_put_oi"]
    top_call_chg = option_data["top_call_chg_oi"]
    top_put_chg = option_data["top_put_chg_oi"]

    score = 0  # -100 (very bearish) to +100 (very bullish)
    reasons = []

    # 1. PCR Analysis
    if pcr > 1.3:
        score += 30
        reasons.append(f"**PCR = {pcr:.2f}** (High) → Strong put writing signals bullish sentiment. Option writers are confident Nifty won't fall.")
    elif pcr > 1.0:
        score += 15
        reasons.append(f"**PCR = {pcr:.2f}** (Moderately Bullish) → More puts being written than calls, mildly bullish undertone.")
    elif pcr > 0.7:
        score -= 5
        reasons.append(f"**PCR = {pcr:.2f}** (Neutral) → Balanced call-put writing, no clear directional bias from PCR.")
    elif pcr > 0.5:
        score -= 20
        reasons.append(f"**PCR = {pcr:.2f}** (Low) → Heavy call writing indicates bearish outlook. Market may face resistance.")
    else:
        score -= 35
        reasons.append(f"**PCR = {pcr:.2f}** (Very Low) → Extreme call writing dominance. Market is overbought or facing strong resistance.")

    # 2. Max Pain Analysis
    if underlying > 0 and max_pain > 0:
        diff_pct = ((max_pain - underlying) / underlying) * 100
        if abs(diff_pct) < 0.3:
            reasons.append(f"**Max Pain = {max_pain:,.0f}** — Nifty is near max pain ({diff_pct:+.2f}%). Market likely to stay rangebound near expiry.")
        elif diff_pct > 0:
            score += 10
            reasons.append(f"**Max Pain = {max_pain:,.0f}** — Nifty is {abs(diff_pct):.1f}% BELOW max pain. Gravitational pull upwards towards {max_pain:,.0f} is expected.")
        else:
            score -= 10
            reasons.append(f"**Max Pain = {max_pain:,.0f}** — Nifty is {abs(diff_pct):.1f}% ABOVE max pain. Gravitational pull downwards towards {max_pain:,.0f} is expected.")

    # 3. Highest Call OI = Immediate Resistance
    if top_call_oi:
        highest_call_strike = top_call_oi[0]["strike"]
        highest_call_oi_val = top_call_oi[0]["ce_oi"]
        reasons.append(f"**Immediate Resistance** at **{highest_call_strike:,.0f}** (Call OI: {highest_call_oi_val:,.0f}). Heavy call writing acts as a ceiling.")
        if underlying > highest_call_strike:
            score -= 10
            reasons.append(f"⚠️ Nifty is ABOVE highest call OI strike — either a breakout or call writers may face short-covering rally.")

    # 4. Highest Put OI = Immediate Support
    if top_put_oi:
        highest_put_strike = top_put_oi[0]["strike"]
        highest_put_oi_val = top_put_oi[0]["pe_oi"]
        reasons.append(f"**Immediate Support** at **{highest_put_strike:,.0f}** (Put OI: {highest_put_oi_val:,.0f}). Heavy put writing acts as a floor.")
        if underlying < highest_put_strike:
            score -= 15
            reasons.append(f"⚠️ Nifty is BELOW highest put OI strike — support breach signals potential selling pressure.")

    # 5. Change in OI Analysis (fresh writing = directional conviction)
    if top_call_chg and top_put_chg:
        total_fresh_call = sum(x["ce_chg_oi"] for x in top_call_chg if x["ce_chg_oi"] > 0)
        total_fresh_put = sum(x["pe_chg_oi"] for x in top_put_chg if x["pe_chg_oi"] > 0)
        if total_fresh_put > total_fresh_call * 1.5:
            score += 15
            reasons.append(f"**Fresh Put Writing** ({total_fresh_put:,.0f}) significantly exceeds fresh Call Writing ({total_fresh_call:,.0f}) → Bullish signal (writers expect puts to expire worthless).")
        elif total_fresh_call > total_fresh_put * 1.5:
            score -= 15
            reasons.append(f"**Fresh Call Writing** ({total_fresh_call:,.0f}) significantly exceeds fresh Put Writing ({total_fresh_put:,.0f}) → Bearish signal (writers expect calls to expire worthless).")
        else:
            reasons.append(f"Fresh writing balanced — Call: {total_fresh_call:,.0f}, Put: {total_fresh_put:,.0f}. No strong directional cue from OI changes.")

    # Determine verdict
    if score >= 25:
        verdict = "🟢 BULLISH"
        verdict_color = "#10b981"
    elif score >= 10:
        verdict = "🟢 MILDLY BULLISH"
        verdict_color = "#34d399"
    elif score <= -25:
        verdict = "🔴 BEARISH"
        verdict_color = "#ef4444"
    elif score <= -10:
        verdict = "🔴 MILDLY BEARISH"
        verdict_color = "#f87171"
    else:
        verdict = "🟡 NEUTRAL"
        verdict_color = "#f59e0b"

    return {
        "verdict": verdict,
        "verdict_color": verdict_color,
        "score": score,
        "reasons": reasons,
    }


def analyze_fii_dii_sentiment(fii_dii_data) -> dict:
    """Score FII/DII flows for market sentiment overlay."""
    if not fii_dii_data:
        return {"score": 0, "label": "Unavailable", "reasons": []}
    score = 0
    reasons = []
    fii = fii_dii_data.get("fii") or {}
    dii = fii_dii_data.get("dii") or {}
    if fii:
        net = fii.get("net_cr", 0)
        if net > 500:
            score += 12
            reasons.append(f"**FII net buy ₹{net:,.0f} Cr** — strong foreign inflow (bullish).")
        elif net > 0:
            score += 5
            reasons.append(f"**FII net buy ₹{net:,.0f} Cr** — mild foreign support.")
        elif net < -500:
            score -= 12
            reasons.append(f"**FII net sell ₹{abs(net):,.0f} Cr** — heavy foreign outflow (bearish).")
        elif net < 0:
            score -= 5
            reasons.append(f"**FII net sell ₹{abs(net):,.0f} Cr** — foreign selling pressure.")
    if dii:
        net = dii.get("net_cr", 0)
        if net > 500:
            score += 8
            reasons.append(f"**DII net buy ₹{net:,.0f} Cr** — domestic institutions absorbing supply.")
        elif net > 0:
            score += 3
            reasons.append(f"**DII net buy ₹{net:,.0f} Cr** — domestic support.")
        elif net < -500:
            score -= 6
            reasons.append(f"**DII net sell ₹{abs(net):,.0f} Cr** — domestic institutions exiting.")
    return {"score": score, "label": "FII/DII", "reasons": reasons}


def analyze_delivery_turnover_sentiment(td_data) -> dict:
    """Score delivery % and turnover for accumulation vs speculation read."""
    if not td_data:
        return {"score": 0, "label": "Unavailable", "reasons": []}
    score = 0
    reasons = []
    avg_del = td_data.get("avg_delivery_pct", 0)
    turnover_cr = td_data.get("total_turnover_cr", 0)
    if avg_del >= 55:
        score += 8
        reasons.append(f"**Market delivery {avg_del:.1f}%** — high delivery suggests genuine accumulation.")
    elif avg_del >= 40:
        score += 2
        reasons.append(f"**Market delivery {avg_del:.1f}%** — moderate delivery, mixed conviction.")
    elif avg_del < 30:
        score -= 6
        reasons.append(f"**Market delivery {avg_del:.1f}%** — low delivery, speculative intraday churn dominant.")
    if turnover_cr > 0:
        reasons.append(f"**Cash turnover ₹{turnover_cr:,.0f} Cr** on {td_data.get('trade_date', 'last session')}.")
    return {"score": score, "label": "Delivery/Turnover", "reasons": reasons}


# ─── Index support / resistance (Market Pulse) ─────────────────────────────
# Index -> Yahoo mappings: truebacktesting/nse_index_yfinance.py


def _yf_ohlcv_from_download(raw: pd.DataFrame, yf_sym: str) -> pd.DataFrame | None:
    """Extract one ticker's OHLCV from a yfinance batch download."""
    df = yf_ohlcv_from_download(raw, yf_sym)
    return df if df is not None and len(df) >= 10 else None


def _download_index_ohlcv(yf_sym: str) -> pd.DataFrame | None:
    """Single-index yfinance OHLCV fallback."""
    return download_yf_ticker_ohlcv(yf_sym, period="6mo")


def _sr_from_ohlcv(df: pd.DataFrame) -> dict[str, float | None]:
    """S1/S2/R1/R2 from daily OHLC using swing-level analysis."""
    from app.market_pulse.gap_trading import calculate_two_level_sr

    levels = calculate_two_level_sr(df)
    out = {
        "s1": levels.get("s1"),
        "s2": levels.get("s2"),
        "r1": levels.get("r1"),
        "r2": levels.get("r2"),
    }
    if any(out.values()):
        return out

    from app.market_pulse.price_action import detect_support_resistance

    sr = detect_support_resistance(df, window=3, num_levels=2)
    supports = sr.get("supports") or []
    resistances = sr.get("resistances") or []
    return {
        "s1": supports[0]["price"] if len(supports) > 0 else None,
        "s2": supports[1]["price"] if len(supports) > 1 else None,
        "r1": resistances[0]["price"] if len(resistances) > 0 else None,
        "r2": resistances[1]["price"] if len(resistances) > 1 else None,
    }


def _fmt_sr_level(val: float | None) -> str:
    if val is None:
        return "—"
    try:
        v = float(val)
        if np.isnan(v) or v <= 0:
            return "—"
        return f"{v:,.2f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_sr_pair(s1: float | None, s2: float | None) -> str:
    """Two support or resistance levels on one line."""
    return f"{_fmt_sr_level(s1)} · {_fmt_sr_level(s2)}"


def _index_quote_sr_columns(
    last,
    pct,
    sr: dict | None,
    *,
    pct_label: str = "Chg %",
) -> dict:
    """Last price, % change, and paired S/R columns for index tables."""
    sr = sr or {}
    last_s = f"{float(last):,.2f}" if last is not None else "—"
    if pct is not None:
        try:
            pct_s = f"{float(pct):+.2f}%"
        except (TypeError, ValueError):
            pct_s = "—"
    else:
        pct_s = "—"
    return {
        "Last": last_s,
        pct_label: pct_s,
        "Support (S1 · S2)": _fmt_sr_pair(sr.get("s1"), sr.get("s2")),
        "Resistance (R1 · R2)": _fmt_sr_pair(sr.get("r1"), sr.get("r2")),
    }


# Key indices shown on News Scanner cards — S/R fetched on data load.
_NEWS_SCANNER_SR_INDEX_NAMES: tuple[str, ...] = (
    "Nifty 50",
    "Sensex",
    "Bank Nifty",
    "Nifty IT",
    "Nifty Midcap 150",
    "Dow Jones",
    "S&P 500",
    "Nasdaq Composite",
    "Russell 2000",
    "Nikkei 225 (Japan)",
    "Hang Seng (HK)",
    "Shanghai (China)",
    "KOSPI (Korea)",
    "FTSE 100 (UK)",
    "DAX 40 (Germany)",
    "CAC 40 (France)",
)


def fetch_index_sr_levels(
    index_names: tuple[str, ...],
    use_groww: bool = False,
    exchange: str = "NSE",
) -> dict[str, dict]:
    """
    Two nearest support and two nearest resistance levels per index
    (swing clustering on ~6 months daily bars).
    """
    if not index_names:
        return {}

    groww_token = get_active_groww_token() if use_groww else ""
    out: dict[str, dict] = {}
    for name in index_names:
        resolved = fetch_index_daily_ohlcv(
            name, period="6mo", groww_token=groww_token, exchange=exchange,
        )
        if resolved is None or len(resolved) < 15:
            continue
        levels = _sr_from_ohlcv(resolved)
        if any(levels.values()):
            out[name] = levels
    return out


def _breadth_indices_map(breadth_data) -> dict:
    """Normalize breadth payload to index-name -> stats dict."""
    if not breadth_data:
        return {}
    if "indices" in breadth_data:
        return breadth_data["indices"]
    return breadth_data


def _breadth_card_html(name: str, b: dict, sr: dict | None = None) -> str:
    adv, dec, unch = b["advances"], b["declines"], b["unchanged"]
    sr = sr or {}
    sr_block = (
        f'<div style="font-size:0.68rem;color:#64748b;margin-top:8px;line-height:1.45;">'
        f'<span style="color:#34d399;">S1</span> {_fmt_sr_level(sr.get("s1"))} · '
        f'<span style="color:#34d399;">S2</span> {_fmt_sr_level(sr.get("s2"))}<br>'
        f'<span style="color:#f87171;">R1</span> {_fmt_sr_level(sr.get("r1"))} · '
        f'<span style="color:#f87171;">R2</span> {_fmt_sr_level(sr.get("r2"))}'
        f"</div>"
    )
    return f"""
    <div style="background:#0f1729;border:1px solid #1e3a5f;border-radius:10px;padding:12px 14px;height:100%;">
        <div style="font-size:0.75rem;font-weight:600;color:#cbd5e1;margin-bottom:6px;">{name}</div>
        <div style="font-size:0.8rem;color:#e2e8f0;margin-bottom:4px;font-weight:600;">
            <span>Last {_fmt_sr_level(b.get('last'))}</span>
            <span style="color:#94a3b8;margin-left:8px;">{f"{b.get('pct'):+.2f}%" if b.get('pct') is not None else "—"}</span>
        </div>
        <div style="font-size:0.8rem;color:#10b981;">▲ {adv} advances</div>
        <div style="font-size:0.8rem;color:#ef4444;">▼ {dec} declines</div>
        <div style="font-size:0.75rem;color:#64748b;">— {unch} unchanged</div>
        {sr_block}
    </div>"""


def _sorted_index_movers(indices: dict, names: list[str] | None = None, top_n: int = 10):
    """Return top gainers/losers among indices by % change."""
    pool = []
    for name, b in indices.items():
        if names is not None and name not in names:
            continue
        pool.append({"name": name, "pct": b.get("pct", 0), "last": b.get("last", 0)})
    if not pool:
        return [], []
    gainers = sorted(pool, key=lambda x: x["pct"], reverse=True)[:top_n]
    losers = sorted(pool, key=lambda x: x["pct"])[:top_n]
    return gainers, losers


def _movers_table_rows(
    items: list[dict],
    name_key: str = "name",
    sr_map: dict[str, dict] | None = None,
) -> list[dict]:
    rows = []
    for item in items:
        key = item[name_key]
        sr = (sr_map or {}).get(key, {})
        row = {"Name": key}
        row.update(_index_quote_sr_columns(item.get("last"), item.get("pct"), sr))
        rows.append(row)
    return rows


def _render_gainers_losers_columns(
    gainers: list[dict],
    losers: list[dict],
    *,
    name_key: str = "name",
    sr_map: dict[str, dict] | None = None,
):
    col_g, col_l = st.columns(2)
    with col_g:
        st.markdown("**🟢 Top Gainers**")
        if gainers:
            st.dataframe(
                pd.DataFrame(_movers_table_rows(gainers, name_key, sr_map)),
                hide_index=True,
                width='stretch',
            )
        else:
            st.caption("No data")
    with col_l:
        st.markdown("**🔴 Top Losers**")
        if losers:
            st.dataframe(
                pd.DataFrame(_movers_table_rows(losers, name_key, sr_map)),
                hide_index=True,
                width='stretch',
            )
        else:
            st.caption("No data")


_MARKET_PULSE_LAZY_BATCH_SIZE = 10
_NIFTY_BREADTH_BATCH_SIZE = _MARKET_PULSE_LAZY_BATCH_SIZE


def _build_nifty_breadth_work_units(breadth_data: dict) -> list[dict]:
    """Ordered index cards for lazy breadth loading (10 per click)."""
    indices = _breadth_indices_map(breadth_data)
    groups = breadth_data.get("groups") or {}
    units: list[dict] = []
    for group in _NIFTY_BREADTH_GROUP_ORDER:
        names = groups.get(group) or [
            n for n, b in indices.items() if b.get("group") == group
        ]
        label = _NIFTY_BREADTH_GROUP_LABELS.get(group, group.title())
        for name in names:
            if name not in indices:
                continue
            units.append({
                "name": name,
                "group": group,
                "group_label": label,
            })
    return units


def _render_nifty_breadth_paginated(
    breadth_data: dict,
    units: list[dict],
    loaded_count: int,
    sr_map: dict[str, dict],
) -> None:
    """Render loaded breadth index cards (S/R fetched per batch)."""
    indices = _breadth_indices_map(breadth_data)
    loaded = units[:loaded_count]
    if not loaded:
        return

    st.caption(
        f"Last · % chg · Support (S1 · S2) · Resistance (R1 · R2) from 6M swings · "
        f"S/R loaded for {len(sr_map)}/{len(indices)} indices"
    )

    prev_group: str | None = None
    row_buf: list[dict] = []

    def _flush_row(buf: list[dict]) -> None:
        if not buf:
            return
        bcols = st.columns(2)
        for col_i, unit in enumerate(buf):
            name = unit["name"]
            b = indices.get(name)
            if not b:
                continue
            with bcols[col_i]:
                st.markdown(
                    _breadth_card_html(name, b, sr_map.get(name)),
                    unsafe_allow_html=True,
                )

    for unit in loaded:
        if unit["group"] != prev_group:
            if row_buf:
                _flush_row(row_buf)
                row_buf = []
            st.markdown(
                f'<div style="font-size:0.78rem;font-weight:600;color:#94a3b8;'
                f'margin:14px 0 8px;">{unit["group_label"]}</div>',
                unsafe_allow_html=True,
            )
            prev_group = unit["group"]
        row_buf.append(unit)
        if len(row_buf) >= 2:
            _flush_row(row_buf)
            row_buf = []
    if row_buf:
        _flush_row(row_buf)


def _reset_nifty_breadth_session() -> None:
    for key in (
        "nifty_breadth_data",
        "nifty_breadth_units",
        "nifty_breadth_loaded_count",
        "nifty_breadth_sr_map",
    ):
        st.session_state.pop(key, None)


def render_nifty_index_breadth_tab() -> None:
    """Nifty index breadth cards — lazy-loaded 10 indices per click."""
    _render_news_scanner_styles()
    st.markdown(
        '<div class="section-header-ns">📊 Nifty Index Breadth</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Loads **{_NIFTY_BREADTH_BATCH_SIZE} indices per click** with advances/declines "
        "and S1/S2/R1/R2 (fetched only for the batch being loaded)."
    )

    breadth = st.session_state.get("nifty_breadth_data")
    units: list[dict] = st.session_state.get("nifty_breadth_units") or []
    loaded_count = int(st.session_state.get("nifty_breadth_loaded_count") or 0)
    total = len(units)

    btn_col, reset_col, prog_col = st.columns([2, 1, 2])
    with btn_col:
        if total == 0 or loaded_count < total:
            batch_label = (
                f"▶ Load first {_NIFTY_BREADTH_BATCH_SIZE} indices"
                if loaded_count == 0
                else f"▶ Load next {_NIFTY_BREADTH_BATCH_SIZE} indices"
            )
            load_batch_btn = st.button(
                batch_label,
                key="nifty_breadth_load_batch_btn",
                type="primary",
            )
        else:
            load_batch_btn = False
            st.success("All indices loaded.")
    with reset_col:
        if st.button("↺ Reset", key="nifty_breadth_reset_btn"):
            _reset_nifty_breadth_session()
            fetch_nse_market_breadth.clear()
            fetch_index_sr_levels.clear()
            st.rerun()

    if load_batch_btn:
        if not breadth:
            with nullcontext():
                breadth = fetch_nse_market_breadth()
            if not breadth:
                st.error(
                    "Unable to load NSE index breadth (NSE allIndices timed out or blocked). "
                    "Click **↺ Reset** and try again — failed fetches are no longer cached."
                )
            else:
                st.session_state["nifty_breadth_data"] = breadth
                units = _build_nifty_breadth_work_units(breadth)
                st.session_state["nifty_breadth_units"] = units
                st.session_state["nifty_breadth_loaded_count"] = 0
                st.session_state["nifty_breadth_sr_map"] = {}
                total = len(units)

        if breadth and units:
            sr_map: dict[str, dict] = st.session_state.get("nifty_breadth_sr_map") or {}
            start = loaded_count
            end = min(loaded_count + _NIFTY_BREADTH_BATCH_SIZE, total)
            batch_units = units[start:end]
            batch_names = [u["name"] for u in batch_units]
            with nullcontext():
                if batch_names:
                    sr_map.update(fetch_index_sr_levels(tuple(batch_names)))
            st.session_state["nifty_breadth_sr_map"] = sr_map
            st.session_state["nifty_breadth_loaded_count"] = end
            loaded_count = end

    breadth = st.session_state.get("nifty_breadth_data")
    units = st.session_state.get("nifty_breadth_units") or []
    loaded_count = int(st.session_state.get("nifty_breadth_loaded_count") or 0)
    total = len(units)

    with prog_col:
        if total > 0:
            st.caption(f"**{loaded_count} / {total}** indices loaded")
            st.progress(loaded_count / total if total else 0.0)

    if not breadth:
        st.info(
            f"Click **▶ Load first {_NIFTY_BREADTH_BATCH_SIZE} indices** to fetch NSE breadth, "
            f"then **Load next {_NIFTY_BREADTH_BATCH_SIZE}** until all index cards are shown."
        )
        return

    indices = _breadth_indices_map(breadth)
    st.markdown(f"**{len(indices)}** Nifty indices in breadth snapshot (NSE allIndices)")
    _render_nifty_breadth_paginated(
        breadth,
        units,
        loaded_count,
        st.session_state.get("nifty_breadth_sr_map") or {},
    )
    from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
    snapshot_section_for_ask_ai("nifty_breadth")


_NIFTY_GL_BATCH_SIZE = _MARKET_PULSE_LAZY_BATCH_SIZE


def _build_nifty_gl_work_units(breadth_data: dict) -> list[dict]:
    """Ordered sections to load in batches (10 per click)."""
    indices = _breadth_indices_map(breadth_data)
    groups = breadth_data.get("groups") or {}
    units: list[dict] = [{"kind": "overview", "label": "All Nifty Indices"}]
    for group in _NIFTY_BREADTH_GROUP_ORDER:
        names = groups.get(group) or [
            n for n, b in indices.items() if b.get("group") == group
        ]
        if not names:
            continue
        label = _NIFTY_BREADTH_GROUP_LABELS.get(group, group.title())
        units.append({
            "kind": "group",
            "group": group,
            "label": label,
            "names": names,
        })
    for index_name in _FO_INDICES_FOR_STOCK_MOVERS:
        units.append({
            "kind": "fo_stocks",
            "index_name": index_name,
            "label": f"{index_name} — Stock Movers",
        })
    return units


def _load_nifty_gl_work_unit(
    unit: dict,
    breadth_data: dict,
    sr_map: dict[str, dict],
    fo_movers: dict[str, dict | None],
) -> None:
    """Fetch S/R or constituent movers for one section only."""
    indices = _breadth_indices_map(breadth_data)
    kind = unit["kind"]
    if kind == "overview":
        gainers, losers = _sorted_index_movers(indices, top_n=10)
        names = list({x["name"] for x in gainers + losers})
        if names:
            sr_map.update(fetch_index_sr_levels(tuple(names)))
    elif kind == "group":
        names = unit.get("names") or []
        if names:
            sr_map.update(fetch_index_sr_levels(tuple(names)))
    elif kind == "fo_stocks":
        index_name = unit["index_name"]
        if index_name not in fo_movers:
            fo_movers[index_name] = fetch_nse_index_stock_movers(index_name, top_n=10)


def _render_nifty_gl_work_unit(
    unit: dict,
    breadth_data: dict,
    sr_map: dict[str, dict],
    fo_movers: dict[str, dict | None],
) -> None:
    indices = _breadth_indices_map(breadth_data)
    kind = unit["kind"]
    if kind == "overview":
        st.markdown("**All Nifty Indices**")
        gainers, losers = _sorted_index_movers(indices, top_n=10)
        _render_gainers_losers_columns(gainers, losers, sr_map=sr_map)
    elif kind == "group":
        label = unit.get("label", unit.get("group", "Group"))
        with st.expander(f"{label} — Top 10 Gainers & Losers", expanded=False):
            g, l = _sorted_index_movers(indices, names=unit.get("names"), top_n=10)
            _render_gainers_losers_columns(g, l, sr_map=sr_map)
    elif kind == "fo_stocks":
        index_name = unit["index_name"]
        with st.expander(f"{index_name} — Top 10 Stock Gainers & Losers", expanded=False):
            movers = fo_movers.get(index_name)
            if not movers:
                st.caption("Unable to fetch constituent movers for this index.")
            else:
                _render_gainers_losers_columns(
                    movers["gainers"], movers["losers"], name_key="symbol",
                )


def _render_nifty_gainers_losers_paginated(
    breadth_data: dict,
    units: list[dict],
    loaded_count: int,
    sr_map: dict[str, dict],
    fo_movers: dict[str, dict | None],
) -> None:
    if loaded_count <= 0:
        return
    st.caption(
        "Last price and % change with **Support (S1 · S2)** and **Resistance (R1 · R2)** "
        "from 6M daily swing levels."
    )
    fo_header_shown = False
    for unit in units[:loaded_count]:
        if unit["kind"] == "fo_stocks" and not fo_header_shown:
            st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)
            st.markdown("**F&O Index Constituents — Stock Movers**")
            fo_header_shown = True
        _render_nifty_gl_work_unit(unit, breadth_data, sr_map, fo_movers)


def _monthly_index_table_rows(
    items: list[tuple[str, dict]],
    sr_map: dict[str, dict] | None = None,
) -> list[dict]:
    rows = []
    for name, data in items:
        sr = (sr_map or {}).get(name, {})
        row = {"Index": name}
        row.update(
            _index_quote_sr_columns(
                data.get("last"),
                data.get("pct_30d"),
                sr,
                pct_label="1M Chg %",
            )
        )
        rows.append(row)
    return rows


_NIFTY_MONTHLY_BATCH_SIZE = _MARKET_PULSE_LAZY_BATCH_SIZE


def _render_nifty_monthly_overview(breadth_data: dict, sr_map: dict[str, dict]) -> None:
    """Top/bottom index tables and full 1M performance chart."""
    monthly = (breadth_data or {}).get("monthly") or {}
    if not monthly:
        st.caption("1-month index performance data unavailable from NSE.")
        return

    sorted_all = sorted(monthly.items(), key=lambda x: x[1]["pct_30d"], reverse=True)
    ref_date = next(iter(monthly.values())).get("date_30d_ago", "")
    st.caption(
        f"~1-month change vs {ref_date or '30 trading days ago'} · "
        f"{len(monthly)} Nifty indices · Source: NSE allIndices · "
        "Last · 1M % · Support (S1 · S2) · Resistance (R1 · R2)"
    )

    col_best, col_worst = st.columns(2)
    with col_best:
        st.markdown(f"**🏆 Top {_MONTHLY_MOVERS_TOP_N} Indices — 1M Gainers**")
        st.dataframe(
            pd.DataFrame(_monthly_index_table_rows(sorted_all[:_MONTHLY_MOVERS_TOP_N], sr_map)),
            hide_index=True,
            width='stretch',
        )
    with col_worst:
        st.markdown(f"**📉 Top {_MONTHLY_MOVERS_TOP_N} Indices — 1M Losers**")
        st.dataframe(
            pd.DataFrame(_monthly_index_table_rows(sorted_all[-_MONTHLY_MOVERS_TOP_N:][::-1], sr_map)),
            hide_index=True,
            width='stretch',
        )

    names = [n for n, _ in sorted_all]
    pcts = [d["pct_30d"] for _, d in sorted_all]
    quotes = [fmt_last_pct(d.get("last"), d.get("pct_30d")) for _, d in sorted_all]
    colors = ["rgba(16, 185, 129, 0.8)" if p >= 0 else "rgba(239, 68, 68, 0.8)" for p in pcts]
    chart_h = min(1400, max(420, len(names) * 15))
    fig = go.Figure(go.Bar(
        x=pcts,
        y=names,
        orientation="h",
        marker_color=colors,
        customdata=quotes,
        hovertemplate="%{y}<br>%{customdata}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(
            text="Nifty Indices — 1-Month Performance (%)",
            font=dict(size=14, color="#cbd5e1"),
        ),
        height=chart_h,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15, 23, 41, 0.8)",
        font=dict(color="#94a3b8", size=10),
        xaxis=dict(title="1-Month % Change", gridcolor="#1e3a5f", zerolinecolor="#475569"),
        yaxis=dict(autorange="reversed", gridcolor="#1e3a5f"),
        margin=dict(l=20, r=20, t=50, b=40),
    )
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def _build_nifty_monthly_work_units(breadth_data: dict) -> list[dict]:
    """Overview first, then each index in group order (10 per lazy-load click)."""
    monthly = (breadth_data or {}).get("monthly") or {}
    monthly_groups = (breadth_data or {}).get("monthly_groups") or {}
    units: list[dict] = [{"kind": "overview", "label": "1M Overview & Chart"}]
    for group in _NIFTY_BREADTH_GROUP_ORDER:
        g_names = monthly_groups.get(group) or [
            n for n, d in monthly.items() if d.get("group") == group
        ]
        if not g_names:
            continue
        g_sorted = sorted(
            [(n, monthly[n]) for n in g_names if n in monthly],
            key=lambda x: x[1]["pct_30d"],
            reverse=True,
        )
        label = _NIFTY_BREADTH_GROUP_LABELS.get(group, group.title())
        for name, data in g_sorted:
            units.append({
                "kind": "index",
                "name": name,
                "pct_30d": data["pct_30d"],
                "group": group,
                "group_label": label,
            })
    return units


def _load_nifty_monthly_work_unit(
    unit: dict,
    breadth_data: dict,
    sr_map: dict[str, dict],
    stock_movers: dict[str, dict | None],
    *,
    load_stocks: bool,
) -> None:
    monthly = (breadth_data or {}).get("monthly") or {}
    kind = unit["kind"]
    if kind == "overview":
        sorted_all = sorted(monthly.items(), key=lambda x: x[1]["pct_30d"], reverse=True)
        top_names = [n for n, _ in sorted_all[:_MONTHLY_MOVERS_TOP_N]]
        bottom_names = [n for n, _ in sorted_all[-_MONTHLY_MOVERS_TOP_N:]]
        names = list(dict.fromkeys(top_names + bottom_names))
        if names:
            sr_map.update(fetch_index_sr_levels(tuple(names)))
    elif kind == "index":
        name = unit["name"]
        sr_map.update(fetch_index_sr_levels((name,)))
        if load_stocks and name not in stock_movers:
            stock_movers[name] = fetch_index_monthly_stock_movers(name)


def _render_nifty_monthly_index_unit(
    unit: dict,
    breadth_data: dict,
    sr_map: dict[str, dict],
    stock_movers: dict[str, dict | None],
    *,
    load_stocks: bool,
) -> None:
    monthly = (breadth_data or {}).get("monthly") or {}
    name = unit["name"]
    data = monthly.get(name)
    if not data:
        return
    pct = data["pct_30d"]
    trend = "🟢" if pct >= 0 else "🔴"
    quote = fmt_last_pct(data.get("last"), pct)
    with st.expander(
        f"{trend} **{name}** — {quote} (1M)",
        expanded=False,
    ):
        st.dataframe(
            pd.DataFrame(_monthly_index_table_rows([(name, data)], sr_map)),
            hide_index=True,
            width='stretch',
        )
        if load_stocks:
            movers = stock_movers.get(name)
            if movers is None:
                st.caption("Constituent movers not loaded yet.")
            else:
                _render_index_monthly_stock_movers_from_data(name, movers)
        else:
            st.caption(
                f"Enable **Load constituent stock movers** above to see top "
                f"{_MONTHLY_MOVERS_TOP_N} stocks for this index."
            )


def _render_index_monthly_stock_movers_from_data(index_name: str, movers: dict) -> None:
    """Render pre-fetched monthly stock movers."""
    if movers.get("skipped"):
        st.caption(
            f"{index_name} has {movers.get('constituent_count', '?')} constituents — "
            f"stock drill-down is limited to indices with "
            f"≤{_MONTHLY_STOCK_MAX_CONSTITUENTS} stocks."
        )
        return
    col_g, col_l = st.columns(2)
    with col_g:
        st.markdown(f"**🟢 Top {_MONTHLY_MOVERS_TOP_N} — 1M Gainers**")
        rows = [{
            "Stock": s["symbol"],
            **_index_quote_sr_columns(s.get("last"), s.get("pct"), None, pct_label="1M %"),
        } for s in movers.get("gainers", [])]
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')
    with col_l:
        st.markdown(f"**🔴 Top {_MONTHLY_MOVERS_TOP_N} — 1M Losers**")
        rows = [{
            "Stock": s["symbol"],
            **_index_quote_sr_columns(s.get("last"), s.get("pct"), None, pct_label="1M %"),
        } for s in movers.get("losers", [])]
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')


def _render_index_monthly_stock_movers(index_name: str):
    """Render top monthly stock gainers/losers for one index."""
    movers = fetch_index_monthly_stock_movers(index_name, top_n=_MONTHLY_MOVERS_TOP_N)
    if not movers:
        st.caption("Constituent monthly data unavailable.")
        return
    _render_index_monthly_stock_movers_from_data(index_name, movers)


def _render_nifty_monthly_paginated(
    breadth_data: dict,
    units: list[dict],
    loaded_count: int,
    sr_map: dict[str, dict],
    stock_movers: dict[str, dict | None],
    *,
    load_stocks: bool,
) -> None:
    if loaded_count <= 0:
        return
    loaded = units[:loaded_count]
    prev_group: str | None = None
    for unit in loaded:
        if unit["kind"] == "overview":
            _render_nifty_monthly_overview(breadth_data, sr_map)
            st.markdown("<div style='margin-top:12px;'></div>", unsafe_allow_html=True)
            st.markdown("**Per-index 1M rankings & constituent movers**")
            continue
        if unit.get("group") != prev_group:
            st.markdown(
                f'<div style="font-size:0.78rem;font-weight:600;color:#94a3b8;'
                f'margin:14px 0 8px;">{unit.get("group_label", "")}</div>',
                unsafe_allow_html=True,
            )
            prev_group = unit.get("group")
        _render_nifty_monthly_index_unit(
            unit, breadth_data, sr_map, stock_movers, load_stocks=load_stocks,
        )


def _reset_nifty_monthly_session() -> None:
    for key in (
        "nifty_monthly_breadth",
        "nifty_monthly_units",
        "nifty_monthly_loaded_count",
        "nifty_monthly_sr_map",
        "nifty_monthly_stock_movers",
    ):
        st.session_state.pop(key, None)


def render_nifty_monthly_performance_tab() -> None:
    """1-month Nifty performance — lazy-loaded 10 indices per click."""
    _render_news_scanner_styles()
    st.markdown(
        '<div class="section-header-ns">📅 Nifty 1-Month Performance & Constituent Movers</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Loads **{_NIFTY_MONTHLY_BATCH_SIZE} indices per click** after an overview chart. "
        "S/R and constituent stock movers are fetched only for the batch being loaded."
    )

    load_stocks = st.checkbox(
        f"Load top {_MONTHLY_MOVERS_TOP_N} stock gainers/losers per index (1 month)",
        value=False,
        key="nifty_monthly_load_stocks",
        help="When enabled, each batch also fetches constituent 1M movers via yfinance (cached 1 hour).",
    )

    breadth = st.session_state.get("nifty_monthly_breadth")
    units: list[dict] = st.session_state.get("nifty_monthly_units") or []
    loaded_count = int(st.session_state.get("nifty_monthly_loaded_count") or 0)
    total = len(units)

    btn_col, reset_col, prog_col = st.columns([2, 1, 2])
    with btn_col:
        if total == 0 or loaded_count < total:
            batch_label = (
                f"▶ Load first {_NIFTY_MONTHLY_BATCH_SIZE} sections"
                if loaded_count == 0
                else f"▶ Load next {_NIFTY_MONTHLY_BATCH_SIZE} indices"
            )
            load_batch_btn = st.button(
                batch_label,
                key="nifty_monthly_load_batch_btn",
                type="primary",
            )
        else:
            load_batch_btn = False
            st.success("All indices loaded.")
    with reset_col:
        if st.button("↺ Reset", key="nifty_monthly_reset_btn"):
            _reset_nifty_monthly_session()
            fetch_nse_market_breadth.clear()
            fetch_index_sr_levels.clear()
            fetch_index_monthly_stock_movers.clear()
            st.rerun()

    if load_batch_btn:
        if not breadth:
            with nullcontext():
                breadth = fetch_nse_market_breadth()
            if not breadth:
                st.error(
                    "Unable to load NSE index breadth (NSE allIndices timed out or blocked). "
                    "Click **↺ Reset** and try again."
                )
            elif not (breadth.get("monthly") or {}):
                st.error("1-month index performance unavailable from NSE.")
            else:
                st.session_state["nifty_monthly_breadth"] = breadth
                units = _build_nifty_monthly_work_units(breadth)
                st.session_state["nifty_monthly_units"] = units
                st.session_state["nifty_monthly_loaded_count"] = 0
                st.session_state["nifty_monthly_sr_map"] = {}
                st.session_state["nifty_monthly_stock_movers"] = {}
                total = len(units)

        if breadth and units:
            sr_map: dict[str, dict] = st.session_state.get("nifty_monthly_sr_map") or {}
            stock_movers: dict[str, dict | None] = st.session_state.get("nifty_monthly_stock_movers") or {}
            start = loaded_count
            end = min(loaded_count + _NIFTY_MONTHLY_BATCH_SIZE, total)
            batch_units = units[start:end]
            labels = ", ".join(
                u.get("label", u.get("name", ""))[:36] for u in batch_units
            )
            with st.spinner(f"Loading sections {start + 1}–{end} of {total}… ({labels})"):
                for unit in batch_units:
                    _load_nifty_monthly_work_unit(
                        unit, breadth, sr_map, stock_movers, load_stocks=load_stocks,
                    )
            st.session_state["nifty_monthly_sr_map"] = sr_map
            st.session_state["nifty_monthly_stock_movers"] = stock_movers
            st.session_state["nifty_monthly_loaded_count"] = end
            loaded_count = end

    breadth = st.session_state.get("nifty_monthly_breadth")
    units = st.session_state.get("nifty_monthly_units") or []
    loaded_count = int(st.session_state.get("nifty_monthly_loaded_count") or 0)
    total = len(units)

    with prog_col:
        if total > 0:
            st.caption(f"**{loaded_count} / {total}** sections loaded")
            st.progress(loaded_count / total if total else 0.0)

    if not breadth:
        st.info(
            f"Click **▶ Load first {_NIFTY_MONTHLY_BATCH_SIZE} sections** for the 1M overview chart, "
            f"then **Load next {_NIFTY_MONTHLY_BATCH_SIZE} indices** for per-index rankings and stock movers."
        )
        return

    monthly = (breadth or {}).get("monthly") or {}
    st.markdown(f"**{len(monthly)}** Nifty indices with 1-month performance (NSE allIndices)")
    _render_nifty_monthly_paginated(
        breadth,
        units,
        loaded_count,
        st.session_state.get("nifty_monthly_sr_map") or {},
        st.session_state.get("nifty_monthly_stock_movers") or {},
        load_stocks=load_stocks,
    )
    from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
    snapshot_section_for_ask_ai("nifty_monthly")


# ─── Sector Rotation ──────────────────────────────────────────────────────

_SECTOR_ROTATION_TOP_N: int | None = None  # return full ranked sector lists
_NIFTY50_YF = NIFTY50_YF
_SECTOR_YF_TICKERS = SECTOR_INDEX_YF_TICKERS


def _get_sectoral_index_names(breadth_data: dict | None = None) -> list[str]:
    """Sector universe from NSE breadth (SECTORAL INDICES) with static fallback."""
    names: list[str] = []
    if breadth_data:
        groups = breadth_data.get("groups") or {}
        monthly_groups = breadth_data.get("monthly_groups") or {}
        for bucket in (groups.get("SECTORAL INDICES"), monthly_groups.get("SECTORAL INDICES")):
            if bucket:
                for n in bucket:
                    if n not in names:
                        names.append(n)
    if not names:
        names = sector_fallback_index_names()
    return sorted(names)


def _pct_return_over_bars(close_series, bars: int) -> float | None:
    closes = close_series.dropna()
    if closes is None or len(closes) < 2:
        return None
    bars = min(int(bars), len(closes) - 1)
    if bars < 1:
        return None
    start = float(closes.iloc[-1 - bars])
    end = float(closes.iloc[-1])
    if start <= 0:
        return None
    return (end / start - 1) * 100


def _yf_close_series(raw: pd.DataFrame, yf_sym: str) -> pd.Series | None:
    """Extract daily close series for one ticker from a yfinance download."""
    df = _yf_ohlcv_from_download(raw, yf_sym)
    if df is None or df.empty or "close" not in df.columns:
        return None
    closes = pd.to_numeric(df["close"], errors="coerce").dropna()
    return closes if not closes.empty else None


def _load_yf_close_map(symbols: list[str], fetch_months: int) -> dict[str, pd.Series]:
    """Batch + per-symbol fallback load of close prices from Yahoo Finance."""
    sym_closes: dict[str, pd.Series] = {}
    unique = list(dict.fromkeys(s for s in symbols if s))
    chunk_size = 35
    for start in range(0, len(unique), chunk_size):
        chunk = unique[start:start + chunk_size]
        try:
            raw = yf.download(
                chunk,
                period=f"{fetch_months}mo",
                interval="1d",
                group_by="ticker",
                progress=False,
                auto_adjust=True,
                threads=True,
            )
        except Exception as e:
            logger.warning(f"yfinance batch error ({chunk[:3]}…): {e}")
            continue
        if raw is None or raw.empty:
            continue
        for sym in chunk:
            closes = _yf_close_series(raw, sym)
            if closes is not None:
                sym_closes[sym] = closes

    for sym in unique:
        if sym in sym_closes:
            continue
        df = _download_index_ohlcv(sym)
        if df is not None and not df.empty and "close" in df.columns:
            closes = pd.to_numeric(df["close"], errors="coerce").dropna()
            if not closes.empty:
                sym_closes[sym] = closes
    return sym_closes


def compute_sector_rotation(
    sector_names: tuple[str, ...],
    days: int,
    weeks: int,
    months: int,
    use_groww: bool = False,
    exchange: str = "NSE",
) -> dict | None:
    """Compute sector % returns for daily / weekly / monthly lookbacks vs Nifty 50."""
    if not sector_names:
        return None

    groww_token = get_active_groww_token() if use_groww else ""
    fetch_months = max(int(months) + 1, 2)
    period = f"{fetch_months}mo"
    nifty_closes = fetch_index_close_series(
        "NIFTY 50", period=period, groww_token=groww_token, exchange=exchange,
    )
    if nifty_closes is None:
        sym_closes = _load_yf_close_map([_NIFTY50_YF], fetch_months)
        nifty_closes = sym_closes.get(_NIFTY50_YF)
    if nifty_closes is None or nifty_closes.dropna().empty:
        logger.error("Sector rotation: Nifty 50 (^NSEI) close series unavailable")
        return None

    index_closes: dict[str, pd.Series] = {}
    for name in sector_names:
        closes = fetch_index_close_series(
            name, period=period, groww_token=groww_token, exchange=exchange,
        )
        if closes is not None and not closes.dropna().empty:
            index_closes[name] = closes
    if not index_closes:
        logger.error("Sector rotation: no sector close series resolved")
        return None

    day_bars = max(1, int(days))
    week_bars = max(1, int(weeks) * 5)
    month_bars = max(1, int(months) * 21)

    def _build_window(bars: int) -> dict:
        bench = _pct_return_over_bars(nifty_closes, bars)
        rows: list[dict] = []
        for name, closes in index_closes.items():
            pct = _pct_return_over_bars(closes, bars)
            if pct is None:
                continue
            rel = pct - bench if bench is not None else pct
            closes_clean = closes.dropna()
            last_px = float(closes_clean.iloc[-1]) if len(closes_clean) else None
            rows.append({
                "name": name,
                "pct": pct,
                "relative": rel,
                "last": last_px,
                "yf": _index_name_to_yf(name) or "constituent-proxy",
            })
        rows.sort(key=lambda x: x["pct"], reverse=True)
        return {
            "benchmark_pct": bench,
            "sectors": rows,
            "inflow": rows[:_SECTOR_ROTATION_TOP_N],
            "outflow": list(reversed(rows[-_SECTOR_ROTATION_TOP_N:])),
        }

    return {
        "daily": _build_window(day_bars),
        "weekly": _build_window(week_bars),
        "monthly": _build_window(month_bars),
        "sector_count": len(index_closes),
        "days": days,
        "weeks": weeks,
        "months": months,
        "data_feed": "groww" if groww_token else "yfinance",
        "exchange": exchange,
    }


def _rotation_period_label(kind: str, days: int, weeks: int, months: int) -> str:
    if kind == "daily":
        return f"last {days} trading day{'s' if days != 1 else ''}"
    if kind == "weekly":
        return f"last {weeks} week{'s' if weeks != 1 else ''} (~{weeks * 5} sessions)"
    return f"last {months} month{'s' if months != 1 else ''} (~{months * 21} sessions)"


def _rotation_explanation(
    kind: str,
    window: dict,
    days: int,
    weeks: int,
    months: int,
    *,
    benchmark_label: str = "Nifty 50",
) -> str:
    inflow = window.get("inflow") or []
    outflow = window.get("outflow") or []
    bench = window.get("benchmark_pct")
    period = _rotation_period_label(kind, days, weeks, months)
    if not inflow:
        return f"No sector return data for the {period}."
    top = inflow[0]
    bottom = outflow[0] if outflow else inflow[-1]
    bench_txt = f"{bench:+.2f}%" if bench is not None else "N/A"
    tone = (
        "Risk-on rotation — capital chasing outperforming cyclicals and growth pockets."
        if top["pct"] > 1.5 and (bench or 0) >= 0
        else "Defensive rotation — flows favor stable sectors as the benchmark softens."
        if (bench or 0) < -0.5
        else "Selective rotation — leadership is narrow; money is rotating between sectors, not broad risk-on."
    )
    top_q = fmt_last_pct(top.get("last"), top.get("pct"))
    bottom_q = fmt_last_pct(bottom.get("last"), bottom.get("pct"))
    return (
        f"Over the **{period}**, **{top['name'].replace('NIFTY ', '')}** led with "
        f"**{top_q}** ({top['relative']:+.2f}% vs {benchmark_label}), while "
        f"**{bottom['name'].replace('NIFTY ', '')}** lagged at **{bottom_q}**. "
        f"{benchmark_label} returned **{bench_txt}** in the same window. {tone}"
    )


def _render_rotation_sector_table(
    sectors: list[dict],
    title: str,
    sr_map: dict[str, dict] | None = None,
    *,
    benchmark_label: str = "Nifty 50",
) -> None:
    st.markdown(f"**{title}**")
    if not sectors:
        st.caption("No data.")
        return
    rows = []
    for s in sectors:
        sr = (sr_map or {}).get(s["name"], {})
        row = {"Sector": s["name"].replace("NIFTY ", "")}
        row.update(
            _index_quote_sr_columns(
                s.get("last"),
                s.get("pct"),
                sr,
                pct_label="Return %",
            )
        )
        row["vs Nifty 50"] = f"{s['relative']:+.2f}%"
        if benchmark_label != "Nifty 50":
            row[f"vs {benchmark_label}"] = row.pop("vs Nifty 50")
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')


def _render_rotation_bar_chart(
    window: dict,
    title: str,
    *,
    benchmark_label: str = "Nifty",
) -> None:
    sectors = window.get("sectors") or []
    if len(sectors) < 2:
        return
    names = [s["name"].replace("NIFTY ", "") for s in sectors]
    pcts = [s["pct"] for s in sectors]
    quotes = [fmt_last_pct(s.get("last"), s.get("pct")) for s in sectors]
    colors = ["rgba(16,185,129,0.85)" if p >= 0 else "rgba(239,68,68,0.85)" for p in pcts]
    fig = go.Figure(go.Bar(
        x=pcts,
        y=names,
        orientation="h",
        marker_color=colors,
        customdata=quotes,
        hovertemplate="%{y}<br>%{customdata}<extra></extra>",
    ))
    bench = window.get("benchmark_pct")
    if bench is not None:
        fig.add_vline(
            x=bench, line_dash="dash", line_color="#fbbf24", line_width=1,
            annotation_text=f"{benchmark_label} {bench:+.1f}%",
            annotation_position="top",
        )
    fig.update_layout(
        title=dict(text=title, font=dict(size=12, color="#cbd5e1")),
        height=min(520, max(280, len(names) * 22)),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15, 23, 41, 0.8)",
        font=dict(color="#94a3b8", size=10),
        xaxis=dict(title="Return %", gridcolor="#1e3a5f", zerolinecolor="#475569"),
        yaxis=dict(autorange="reversed", gridcolor="#1e3a5f"),
        margin=dict(l=10, r=20, t=40, b=30),
    )
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def _render_rotation_timeframe_block(
    label: str,
    icon: str,
    kind: str,
    window: dict,
    days: int,
    weeks: int,
    months: int,
    sr_map: dict[str, dict] | None = None,
    *,
    benchmark_label: str = "Nifty 50",
) -> None:
    period = _rotation_period_label(kind, days, weeks, months)
    with st.expander(f"{icon} **{label}** — {period}", expanded=(kind == "daily")):
        st.markdown(_rotation_explanation(kind, window, days, weeks, months, benchmark_label=benchmark_label))
        st.markdown("<div style='margin-top:8px;'></div>", unsafe_allow_html=True)
        col_in, col_out = st.columns(2)
        with col_in:
            _render_rotation_sector_table(
                window.get("inflow") or [],
                f"🟢 Money rotating IN (top {_SECTOR_ROTATION_TOP_N})",
                sr_map,
                benchmark_label=benchmark_label,
            )
        with col_out:
            _render_rotation_sector_table(
                window.get("outflow") or [],
                f"🔴 Money rotating OUT (weakest {_SECTOR_ROTATION_TOP_N})",
                sr_map,
                benchmark_label=benchmark_label,
            )
        _render_rotation_bar_chart(window, f"All sectors — {label} returns (%)", benchmark_label=benchmark_label.split()[0])


def _render_sector_rotation_content(payload: dict) -> None:
    days = payload.get("days", 5)
    weeks = payload.get("weeks", 4)
    months = payload.get("months", 3)
    sector_names: list[str] = []
    for window_key in ("daily", "weekly", "monthly"):
        for s in (payload.get(window_key) or {}).get("sectors") or []:
            if s["name"] not in sector_names:
                sector_names.append(s["name"])
    sr_map = fetch_index_sr_levels(
        tuple(sector_names),
        use_groww=(payload.get("data_feed") == "groww"),
        exchange=payload.get("exchange", "NSE"),
    ) if sector_names else {}
    st.caption(
        f"Tracking **{payload.get('sector_count', 0)}** Nifty sectoral indices vs Nifty 50 · "
        f"Feed: **{payload.get('data_feed', 'yfinance').upper()}** · "
        "Last · Return % · Support (S1 · S2) · Resistance (R1 · R2) — 6M swings"
    )
    _render_rotation_timeframe_block(
        "Daily", "📅", "daily", payload["daily"], days, weeks, months, sr_map,
    )
    _render_rotation_timeframe_block(
        "Weekly", "📆", "weekly", payload["weekly"], days, weeks, months, sr_map,
    )
    _render_rotation_timeframe_block(
        "Monthly", "🗓️", "monthly", payload["monthly"], days, weeks, months, sr_map,
    )


def _reset_nifty_gl_session() -> None:
    for key in (
        "nifty_gainers_losers_breadth",
        "nifty_gl_units",
        "nifty_gl_loaded_count",
        "nifty_gl_sr_map",
        "nifty_gl_fo_movers",
    ):
        st.session_state.pop(key, None)


def render_nifty_gainers_losers_tab() -> None:
    """Nifty index gainers/losers — lazy-loaded in batches of 10 for faster hub load."""
    _render_news_scanner_styles()
    st.markdown(
        '<div class="section-header-ns">📈 Nifty Index Gainers & Losers</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Loads **{_NIFTY_GL_BATCH_SIZE} sections per click**: overview, index groups, then F&O constituent "
        "stock movers. S/R levels are fetched only for the section being loaded."
    )

    breadth = st.session_state.get("nifty_gainers_losers_breadth")
    units: list[dict] = st.session_state.get("nifty_gl_units") or []
    loaded_count = int(st.session_state.get("nifty_gl_loaded_count") or 0)
    total = len(units)

    btn_col, reset_col, prog_col = st.columns([2, 1, 2])
    with btn_col:
        if total == 0 or loaded_count < total:
            batch_label = (
                f"▶ Load first {_NIFTY_GL_BATCH_SIZE} sections"
                if loaded_count == 0
                else f"▶ Load next {_NIFTY_GL_BATCH_SIZE} sections"
            )
            load_batch_btn = st.button(
                batch_label,
                key="nifty_gl_load_batch_btn",
                type="primary",
            )
        else:
            load_batch_btn = False
            st.success("All sections loaded.")
    with reset_col:
        if st.button("↺ Reset", key="nifty_gl_reset_btn"):
            _reset_nifty_gl_session()
            fetch_nse_market_breadth.clear()
            fetch_index_sr_levels.clear()
            st.rerun()

    if load_batch_btn:
        if not breadth:
            with nullcontext():
                breadth = fetch_nse_market_breadth()
            if not breadth:
                st.error(
                    "Unable to load NSE index breadth (NSE allIndices timed out or blocked). "
                    "Click **↺ Reset** and try again."
                )
            else:
                st.session_state["nifty_gainers_losers_breadth"] = breadth
                units = _build_nifty_gl_work_units(breadth)
                st.session_state["nifty_gl_units"] = units
                st.session_state["nifty_gl_loaded_count"] = 0
                st.session_state["nifty_gl_sr_map"] = {}
                st.session_state["nifty_gl_fo_movers"] = {}
                total = len(units)

        if breadth and units:
            sr_map: dict[str, dict] = st.session_state.get("nifty_gl_sr_map") or {}
            fo_movers: dict[str, dict | None] = st.session_state.get("nifty_gl_fo_movers") or {}
            start = loaded_count
            end = min(loaded_count + _NIFTY_GL_BATCH_SIZE, total)
            batch_units = units[start:end]
            labels = ", ".join(u.get("label", u.get("kind", ""))[:40] for u in batch_units)
            with nullcontext():
                for unit in batch_units:
                    _load_nifty_gl_work_unit(unit, breadth, sr_map, fo_movers)
            st.session_state["nifty_gl_sr_map"] = sr_map
            st.session_state["nifty_gl_fo_movers"] = fo_movers
            st.session_state["nifty_gl_loaded_count"] = end
            loaded_count = end

    breadth = st.session_state.get("nifty_gainers_losers_breadth")
    units = st.session_state.get("nifty_gl_units") or []
    loaded_count = int(st.session_state.get("nifty_gl_loaded_count") or 0)
    total = len(units)

    with prog_col:
        if total > 0:
            st.caption(f"**{loaded_count} / {total}** sections loaded")
            st.progress(loaded_count / total if total else 0.0)

    if not breadth:
        st.info(
            f"Click **▶ Load first {_NIFTY_GL_BATCH_SIZE} sections** to fetch NSE breadth, then continue with "
            f"**Load next {_NIFTY_GL_BATCH_SIZE}** until all groups and F&O stock movers are shown."
        )
        return

    indices = _breadth_indices_map(breadth)
    st.markdown(
        f"**{len(indices)}** Nifty indices in breadth snapshot (NSE allIndices)"
    )
    _render_nifty_gainers_losers_paginated(
        breadth,
        units,
        loaded_count,
        st.session_state.get("nifty_gl_sr_map") or {},
        st.session_state.get("nifty_gl_fo_movers") or {},
    )
    from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
    snapshot_section_for_ask_ai("nifty_gainers_losers")


def render_sector_rotation_tab() -> None:
    """Sector rotation — daily / weekly / monthly money flow across Nifty sectors."""
    _render_news_scanner_styles()
    st.markdown(
        '<div class="section-header-ns">🔄 Sector Rotation — Where Money Is Moving</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Compare Nifty sectoral index returns over configurable daily, weekly, and monthly "
        "windows. Sectors beating Nifty 50 suggest inflows; laggards suggest rotation out."
    )

    from app.market_pulse.sector_rotation_markets import render_india_sector_index_filter

    st.markdown("##### 🎯 Sector index filter")
    india_sector_filter = render_india_sector_index_filter("sr")

    c1, c2, c3 = st.columns(3)
    with c1:
        rot_days = st.slider(
            "Daily lookback (trading days)", 1, 20, 5, key="sr_rot_days",
        )
    with c2:
        rot_weeks = st.slider(
            "Weekly lookback (weeks)", 1, 12, 4, key="sr_rot_weeks",
        )
    with c3:
        rot_months = st.slider(
            "Monthly lookback (months)", 1, 12, 3, key="sr_rot_months",
        )

    load_btn = st.button("🔄 Load Sector Rotation", key="sr_load_btn", type="primary")

    use_groww, _, exchange = _sector_rotation_feed_mode()
    _render_market_pulse_feed_banner(use_groww)

    if load_btn:
        compute_sector_rotation.clear()
        breadth = fetch_nse_market_breadth()
        sector_names = tuple(
            n for n in _get_sectoral_index_names(breadth) if n in india_sector_filter
        ) if india_sector_filter else tuple(_get_sectoral_index_names(breadth))
        feed_label = "Groww API" if use_groww else "yfinance"
        with st.spinner(
            f"Computing sector returns for {len(sector_names)} indices "
            f"({rot_days}d · {rot_weeks}w · {rot_months}mo) via {feed_label}..."
        ):
            rotation = compute_sector_rotation(
                sector_names, rot_days, rot_weeks, rot_months,
                use_groww=use_groww, exchange=exchange,
            )
        if rotation:
            st.session_state["sector_rotation_payload"] = rotation
        else:
            st.session_state.pop("sector_rotation_payload", None)
            st.error("Unable to compute sector rotation. Check network or try again later.")

    payload = st.session_state.get("sector_rotation_payload")
    if not payload:
        st.info(
            "Click **🔄 Load Sector Rotation** to analyse which Nifty sectors are gaining "
            "and losing over your chosen daily, weekly, and monthly windows. "
            "Data is not fetched automatically on page load."
        )
        return

    if (
        payload.get("days") != rot_days
        or payload.get("weeks") != rot_weeks
        or payload.get("months") != rot_months
    ):
        st.warning(
            "Lookback settings changed — click **Load Sector Rotation** again to refresh."
        )

    _render_sector_rotation_content(payload)
    from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
    snapshot_section_for_ask_ai("sector_rotation")


# ─── Sector Rotation (intraday: mins · hours · days) ─────────────────────

_SR_INTRADAY_MINUTE_INTERVAL = "5m"
_SR_INTRADAY_HOUR_INTERVAL = "1h"
_SR_INTRADAY_DAY_INTERVAL = "1d"


def _load_intraday_close_map(
    index_names: list[str],
    interval: str,
    period: str,
    benchmark_yf: str,
    groww_token: str = "",
    exchange: str = "NSE",
    bar_limit: int = 400,
) -> dict[str, pd.Series]:
    """Load close series for Nifty 50 + sector indices — Groww when token set."""
    sym_closes: dict[str, pd.Series] = {}
    bench = fetch_index_interval_close_series(
        "NIFTY 50",
        interval=interval,
        period=period,
        groww_token=groww_token,
        exchange=exchange,
        limit=bar_limit,
    )
    if bench is not None and not bench.dropna().empty:
        sym_closes[benchmark_yf] = bench
    elif not groww_token:
        raw = yf.download(
            benchmark_yf,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=True,
        )
        closes = _yf_close_series(raw, benchmark_yf)
        if closes is not None:
            sym_closes[benchmark_yf] = closes

    for name in index_names:
        closes = fetch_index_interval_close_series(
            name,
            interval=interval,
            period=period,
            groww_token=groww_token,
            exchange=exchange,
            limit=bar_limit,
        )
        if closes is not None and not closes.dropna().empty:
            sym_closes[name] = closes
    return sym_closes


def _sector_rotation_feed_mode() -> tuple[bool, str, str]:
    """Whether to use Groww for sector rotation / opposite hedge index OHLC."""
    token = get_active_groww_token()
    exchange = (st.session_state.get("sr_groww_exchange") or "NSE").upper()
    return bool(token), token, exchange


def _render_market_pulse_feed_banner(use_groww: bool) -> None:
    if use_groww:
        st.success("🌐 **Active Feed:** Groww API — sector index OHLC & S/R")
    else:
        st.info(
            "ℹ️ **Active Feed:** yfinance fallback. Add your **Groww bearer token** in the "
            "sidebar to use the direct Groww API (recommended during market hours)."
        )


def compute_sector_rotation_intraday(
    sector_names: tuple[str, ...],
    minutes: int,
    hours: int,
    days: int,
    use_groww: bool = False,
    exchange: str = "NSE",
) -> dict | None:
    """Sector % returns over minute / hour / day windows vs Nifty 50 (intraday bars)."""
    if not sector_names:
        return None

    groww_token = get_active_groww_token() if use_groww else ""
    minute_bars = max(1, int(minutes) // 5)
    hour_bars = max(1, int(hours))
    day_bars = max(1, int(days))

    windows_cfg = {
        "minutes": (_SR_INTRADAY_MINUTE_INTERVAL, "5d", minute_bars, max(minute_bars + 20, 80)),
        "hours": (_SR_INTRADAY_HOUR_INTERVAL, "60d", hour_bars, max(hour_bars + 30, 120)),
        "days": (_SR_INTRADAY_DAY_INTERVAL, f"{max(day_bars + 10, 15)}d", day_bars, max(day_bars + 25, 60)),
    }

    result_windows: dict[str, dict] = {}
    sector_count = 0

    for kind, (interval, period, bars, bar_limit) in windows_cfg.items():
        sym_closes = _load_intraday_close_map(
            list(sector_names), interval, period, _NIFTY50_YF,
            groww_token=groww_token, exchange=exchange, bar_limit=bar_limit,
        )
        nifty_closes = sym_closes.get(_NIFTY50_YF)
        if nifty_closes is None or nifty_closes.dropna().empty:
            logger.error("Sector rotation intraday (%s): Nifty 50 unavailable", kind)
            continue

        index_closes = {
            name: sym_closes[name]
            for name in sector_names
            if name in sym_closes
        }
        if not index_closes:
            continue
        sector_count = max(sector_count, len(index_closes))

        bench = _pct_return_over_bars(nifty_closes, bars)
        rows: list[dict] = []
        for name, closes in index_closes.items():
            pct = _pct_return_over_bars(closes, bars)
            if pct is None:
                continue
            rel = pct - bench if bench is not None else pct
            closes_clean = closes.dropna()
            last_px = float(closes_clean.iloc[-1]) if len(closes_clean) else None
            rows.append({
                "name": name,
                "pct": pct,
                "relative": rel,
                "last": last_px,
                "yf": _index_name_to_yf(name) or "constituent-proxy",
            })
        rows.sort(key=lambda x: x["pct"], reverse=True)
        result_windows[kind] = {
            "benchmark_pct": bench,
            "sectors": rows,
            "inflow": rows[:_SECTOR_ROTATION_TOP_N],
            "outflow": list(reversed(rows[-_SECTOR_ROTATION_TOP_N:])),
            "bars": bars,
            "interval": interval,
        }

    if not result_windows:
        return None

    return {
        "minutes": result_windows.get("minutes"),
        "hours": result_windows.get("hours"),
        "days": result_windows.get("days"),
        "sector_count": sector_count,
        "minutes_lookback": minutes,
        "hours_lookback": hours,
        "days_lookback": days,
        "data_feed": "groww" if groww_token else "yfinance",
        "exchange": exchange,
    }


def _rotation_intraday_period_label(kind: str, minutes: int, hours: int, days: int) -> str:
    if kind == "minutes":
        bars = max(1, minutes // 5)
        return f"last {minutes} min (~{bars} × 5m bars)"
    if kind == "hours":
        return f"last {hours} hour{'s' if hours != 1 else ''} (~{hours} × 1h bars)"
    return f"last {days} trading day{'s' if days != 1 else ''}"


def _rotation_intraday_explanation(
    kind: str,
    window: dict,
    minutes: int,
    hours: int,
    days: int,
    *,
    benchmark_label: str = "Nifty 50",
) -> str:
    inflow = window.get("inflow") or []
    outflow = window.get("outflow") or []
    bench = window.get("benchmark_pct")
    period = _rotation_intraday_period_label(kind, minutes, hours, days)
    if not inflow:
        return f"No intraday sector data for the {period}."
    top = inflow[0]
    bottom = outflow[0] if outflow else inflow[-1]
    bench_txt = f"{bench:+.2f}%" if bench is not None else "N/A"
    tone = (
        "Short-term risk-on — sectors are catching bids into the session."
        if top["pct"] > 0.35 and (bench or 0) >= 0
        else "Defensive intraday tilt — flows favor stable sectors as the benchmark softens."
        if (bench or 0) < -0.25
        else "Rotational session — leadership is narrow; pick sectors, not blind index beta."
    )
    top_q = fmt_last_pct(top.get("last"), top.get("pct"))
    bottom_q = fmt_last_pct(bottom.get("last"), bottom.get("pct"))
    return (
        f"Over the **{period}**, **{top['name'].replace('NIFTY ', '')}** led with "
        f"**{top_q}** ({top['relative']:+.2f}% vs {benchmark_label}), while "
        f"**{bottom['name'].replace('NIFTY ', '')}** lagged at **{bottom_q}**. "
        f"{benchmark_label} returned **{bench_txt}** in the same window. {tone}"
    )


def _render_rotation_intraday_timeframe_block(
    label: str,
    icon: str,
    kind: str,
    window: dict | None,
    minutes: int,
    hours: int,
    days: int,
    sr_map: dict[str, dict] | None = None,
    *,
    benchmark_label: str = "Nifty 50",
) -> None:
    if not window:
        with st.expander(f"{icon} **{label}** — no data", expanded=False):
            st.caption("Yahoo Finance did not return bars for this window. Try again during market hours.")
        return
    period = _rotation_intraday_period_label(kind, minutes, hours, days)
    with st.expander(f"{icon} **{label}** — {period}", expanded=(kind == "minutes")):
        st.markdown(
            _rotation_intraday_explanation(
                kind, window, minutes, hours, days, benchmark_label=benchmark_label,
            )
        )
        st.caption(f"Interval: **{window.get('interval', '—')}** · bars: **{window.get('bars', '—')}**")
        st.markdown("<div style='margin-top:8px;'></div>", unsafe_allow_html=True)
        col_in, col_out = st.columns(2)
        with col_in:
            _render_rotation_sector_table(
                window.get("inflow") or [],
                f"🟢 Intraday IN (top {_SECTOR_ROTATION_TOP_N})",
                sr_map,
                benchmark_label=benchmark_label,
            )
        with col_out:
            _render_rotation_sector_table(
                window.get("outflow") or [],
                f"🔴 Intraday OUT (weakest {_SECTOR_ROTATION_TOP_N})",
                sr_map,
                benchmark_label=benchmark_label,
            )
        _render_rotation_bar_chart(
            window, f"All sectors — {label} returns (%)",
            benchmark_label=benchmark_label.split()[0],
        )


def _render_sector_rotation_intraday_content(payload: dict) -> None:
    minutes = payload.get("minutes_lookback", 60)
    hours = payload.get("hours_lookback", 4)
    days = payload.get("days_lookback", 3)
    sector_names: list[str] = []
    for window_key in ("minutes", "hours", "days"):
        w = payload.get(window_key)
        if not w:
            continue
        for s in (w.get("sectors") or []):
            if s["name"] not in sector_names:
                sector_names.append(s["name"])
    sr_map = fetch_index_sr_levels(
        tuple(sector_names),
        use_groww=(payload.get("data_feed") == "groww"),
        exchange=payload.get("exchange", "NSE"),
    ) if sector_names else {}
    st.caption(
        f"Intraday rotation across **{payload.get('sector_count', 0)}** Nifty sectoral indices vs Nifty 50 · "
        f"Feed: **{payload.get('data_feed', 'yfinance').upper()}** · "
        "5m bars (minutes) · 1h bars (hours) · daily closes (days) · "
        "Last · Return % · S/R levels — 6M swings"
    )
    _render_rotation_intraday_timeframe_block(
        "Minutes", "⏱️", "minutes", payload.get("minutes"), minutes, hours, days, sr_map,
    )
    _render_rotation_intraday_timeframe_block(
        "Hours", "🕐", "hours", payload.get("hours"), minutes, hours, days, sr_map,
    )
    _render_rotation_intraday_timeframe_block(
        "Days", "📅", "days", payload.get("days"), minutes, hours, days, sr_map,
    )


def render_sector_rotation_intraday_tab() -> None:
    """Sector rotation — minute / hour / day intraday money flow across Nifty sectors."""
    _render_news_scanner_styles()
    st.markdown(
        '<div class="section-header-ns">🔄 Sector Rotation — mins · hours · days</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Session-style rotation: compare Nifty sector index returns over configurable "
        "**minute** (5m bars), **hour** (1h bars), and **day** windows. "
        "Best used during Indian market hours for freshest intraday data."
    )

    from app.market_pulse.sector_rotation_markets import render_india_sector_index_filter

    st.markdown("##### 🎯 Sector index filter")
    india_sector_filter = render_india_sector_index_filter("sri")

    c1, c2, c3 = st.columns(3)
    with c1:
        rot_mins = st.slider(
            "Minutes lookback", 15, 240, 60, step=15, key="sri_rot_mins",
        )
    with c2:
        rot_hours = st.slider(
            "Hours lookback", 1, 24, 4, key="sri_rot_hours",
        )
    with c3:
        rot_days = st.slider(
            "Days lookback (sessions)", 1, 10, 3, key="sri_rot_days",
        )

    load_btn = st.button("🔄 Load Intraday Sector Rotation", key="sri_load_btn", type="primary")

    use_groww, _, exchange = _sector_rotation_feed_mode()
    _render_market_pulse_feed_banner(use_groww)

    if load_btn:
        compute_sector_rotation_intraday.clear()
        breadth = fetch_nse_market_breadth()
        sector_names = tuple(
            n for n in _get_sectoral_index_names(breadth) if n in india_sector_filter
        ) if india_sector_filter else tuple(_get_sectoral_index_names(breadth))
        feed_label = "Groww API" if use_groww else "yfinance"
        with st.spinner(
            f"Computing intraday sector returns for {len(sector_names)} indices "
            f"({rot_mins}m · {rot_hours}h · {rot_days}d) via {feed_label}..."
        ):
            rotation = compute_sector_rotation_intraday(
                sector_names, rot_mins, rot_hours, rot_days,
                use_groww=use_groww, exchange=exchange,
            )
        if rotation:
            st.session_state["sector_rotation_intraday_payload"] = rotation
        else:
            st.session_state.pop("sector_rotation_intraday_payload", None)
            st.error("Unable to compute intraday sector rotation. Check network or try during market hours.")

    payload = st.session_state.get("sector_rotation_intraday_payload")
    if not payload:
        st.info(
            "Click **🔄 Load Intraday Sector Rotation** to see which sectors are leading or lagging "
            "over your chosen minute, hour, and day windows. Data is not fetched on page load."
        )
        return

    if (
        payload.get("minutes_lookback") != rot_mins
        or payload.get("hours_lookback") != rot_hours
        or payload.get("days_lookback") != rot_days
    ):
        st.warning(
            "Lookback settings changed — click **Load Intraday Sector Rotation** again to refresh."
        )

    _render_sector_rotation_intraday_content(payload)
    from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
    snapshot_section_for_ask_ai("sector_rotation_intraday")


def analyze_breadth_sentiment(breadth_data) -> dict:
    """Score market breadth from Nifty 500 advances/declines."""
    if not breadth_data:
        return {"score": 0, "label": "Unavailable", "reasons": []}
    n500 = _breadth_indices_map(breadth_data).get("NIFTY 500") or {}
    adv = n500.get("advances", 0)
    dec = n500.get("declines", 0)
    if adv + dec == 0:
        return {"score": 0, "label": "Unavailable", "reasons": []}
    ratio = adv / max(dec, 1)
    score = 0
    reasons = []
    if ratio >= 1.5:
        score += 10
        reasons.append(f"**Nifty 500 breadth:** {adv} advances vs {dec} declines — broad participation.")
    elif ratio >= 1.1:
        score += 4
        reasons.append(f"**Nifty 500 breadth:** {adv} advances vs {dec} declines — mildly positive breadth.")
    elif ratio <= 0.65:
        score -= 10
        reasons.append(f"**Nifty 500 breadth:** {adv} advances vs {dec} declines — weak broad market.")
    elif ratio <= 0.9:
        score -= 4
        reasons.append(f"**Nifty 500 breadth:** {adv} advances vs {dec} declines — negative breadth.")
    else:
        reasons.append(f"**Nifty 500 breadth:** {adv} advances vs {dec} declines — neutral.")
    return {"score": score, "label": "Breadth", "reasons": reasons}


def analyze_today_market_sentiment(market_data, option_data=None, fii_dii_data=None,
                                   breadth_data=None, turnover_delivery_data=None):
    """
    Compute overall today's market sentiment (Bullish / Bearish / Neutral)
    from Indian indices, VIX, global futures, Asia markets, options chain,
    FII/DII flows, market breadth, and delivery/turnover.
    """
    score = 0
    signals = []

    def _pct(name):
        d = market_data.get(name, {})
        p = d.get("pct")
        return p if p is not None else None

    # 1. Indian indices (primary drivers)
    india_weights = [
        ("Nifty 50", 18),
        ("Bank Nifty", 14),
        ("Sensex", 10),
        ("Nifty IT", 6),
        ("Nifty Midcap 150", 5),
    ]
    for name, weight in india_weights:
        pct = _pct(name)
        if pct is None:
            continue
        quote = _market_quote_line(market_data, name, pct)
        if pct >= 0.75:
            score += weight
            signals.append(f"🟢 {name} {quote}")
        elif pct <= -0.75:
            score -= weight
            signals.append(f"🔴 {name} {quote}")
        elif pct >= 0.2:
            score += weight // 2
        elif pct <= -0.2:
            score -= weight // 2

    # 2. India VIX (inverse fear gauge)
    vix_pct = _pct("India VIX")
    if vix_pct is not None:
        vix_quote = _market_quote_line(market_data, "India VIX", vix_pct)
        if vix_pct >= 5:
            score -= 18
            signals.append(f"🔴 India VIX {vix_quote} — elevated fear")
        elif vix_pct >= 2:
            score -= 10
        elif vix_pct <= -5:
            score += 12
            signals.append(f"🟢 India VIX {vix_quote} — risk appetite improving")
        elif vix_pct <= -2:
            score += 6

    # 3. Gift Nifty (extended-hours pre-market cue)
    gift_pct = _pct("Gift Nifty")
    if gift_pct is not None:
        gift_quote = _market_quote_line(market_data, "Gift Nifty", gift_pct)
        if gift_pct >= 0.4:
            score += 12
            signals.append(f"🟢 Gift Nifty {gift_quote} — positive pre-market cue")
        elif gift_pct <= -0.4:
            score -= 12
            signals.append(f"🔴 Gift Nifty {gift_quote} — negative pre-market cue")

    # 4. US futures (overnight cue for Indian session)
    futures_names = ["S&P 500 Futures", "Nasdaq Futures", "Dow Futures"]
    futures_pcts = [_pct(n) for n in futures_names if _pct(n) is not None]
    if futures_pcts:
        avg_fut = sum(futures_pcts) / len(futures_pcts)
        if avg_fut >= 0.4:
            score += 14
            signals.append(f"🟢 US Futures avg +{avg_fut:.2f}% — supportive global cue")
        elif avg_fut <= -0.4:
            score -= 14
            signals.append(f"🔴 US Futures avg {avg_fut:.2f}% — global headwind")

    # 5. Asia markets
    asia_names = [
        "Nikkei 225 (Japan)", "Hang Seng (HK)", "Shanghai (China)",
        "KOSPI (Korea)", "Taiwan Weighted", "ASX 200 (Australia)",
    ]
    asia_pcts = [_pct(n) for n in asia_names if _pct(n) is not None]
    if asia_pcts:
        asia_avg = sum(asia_pcts) / len(asia_pcts)
        if asia_avg >= 0.5:
            score += 10
            signals.append(f"🟢 Asia markets broadly positive (avg +{asia_avg:.2f}%)")
        elif asia_avg <= -0.5:
            score -= 10
            signals.append(f"🔴 Asia markets broadly negative (avg {asia_avg:.2f}%)")

    # 6. US live markets
    us_names = ["Dow Jones", "S&P 500", "Nasdaq Composite"]
    us_pcts = [_pct(n) for n in us_names if _pct(n) is not None]
    if us_pcts:
        us_avg = sum(us_pcts) / len(us_pcts)
        if us_avg >= 0.5:
            score += 8
        elif us_avg <= -0.5:
            score -= 8

    # 7. Options chain overlay
    if option_data:
        opt = analyze_options_sentiment(option_data)
        opt_score = opt["score"]
        score += int(opt_score * 0.15)
        if opt_score >= 20:
            signals.append(f"🟢 Options: {opt['verdict']}")
        elif opt_score <= -20:
            signals.append(f"🔴 Options: {opt['verdict']}")

    # 8. FII / DII flows
    fii_sent = analyze_fii_dii_sentiment(fii_dii_data)
    score += fii_sent["score"]
    for r in fii_sent.get("reasons", [])[:2]:
        if "buy" in r.lower():
            signals.append(f"🟢 {r.replace('**', '')[:80]}")
        elif "sell" in r.lower():
            signals.append(f"🔴 {r.replace('**', '')[:80]}")

    # 9. Market breadth
    br_sent = analyze_breadth_sentiment(breadth_data)
    score += br_sent["score"]

    # 10. Delivery / turnover
    td_sent = analyze_delivery_turnover_sentiment(turnover_delivery_data)
    score += td_sent["score"]

    # Verdict thresholds
    if score >= 22:
        verdict = "BULLISH"
        label = "🟢 BULLISH"
        color = "#10b981"
        border_color = "#059669"
        emoji = "📈"
    elif score <= -22:
        verdict = "BEARISH"
        label = "🔴 BEARISH"
        color = "#ef4444"
        border_color = "#dc2626"
        emoji = "📉"
    else:
        verdict = "NEUTRAL"
        label = "🟡 NEUTRAL"
        color = "#f59e0b"
        border_color = "#d97706"
        emoji = "➡️"

    return {
        "verdict": verdict,
        "label": label,
        "color": color,
        "border_color": border_color,
        "emoji": emoji,
        "score": score,
        "signals": signals[:6],
    }


def _render_today_sentiment_banner(market_sentiment, now_ist):
    """Render the prominent today-market sentiment strip at the top."""
    color = market_sentiment["color"]
    border = market_sentiment["border_color"]
    label = market_sentiment["label"]
    verdict = market_sentiment["verdict"]
    score = market_sentiment["score"]
    emoji = market_sentiment["emoji"]
    date_str = now_ist.strftime("%A, %d %b %Y")
    time_str = now_ist.strftime("%H:%M IST")

    signals_html = ""
    if market_sentiment["signals"]:
        chips = "".join(
            f'<span style="display:inline-block;background:#1e293b;border:1px solid #334155;'
            f'border-radius:20px;padding:4px 12px;margin:4px 6px 0 0;font-size:0.72rem;color:#94a3b8;">'
            f'{s}</span>'
            for s in market_sentiment["signals"]
        )
        signals_html = f'<div style="margin-top:14px;">{chips}</div>'

    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #0f1729 0%, #0d1f3c 100%);
                border: 2px solid {border}; border-radius: 16px; padding: 22px 28px; margin-bottom: 20px;">
        <div style="display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 16px;">
            <div>
                <div style="font-size: 0.72rem; color: #64748b; text-transform: uppercase;
                            font-weight: 600; letter-spacing: 2px; margin-bottom: 6px;">
                    TODAY'S MARKET · {date_str}
                </div>
                <div style="font-size: 2.2rem; font-weight: 800; color: {color}; line-height: 1.1;">
                    {emoji} {label}
                </div>
                <div style="font-size: 0.82rem; color: #64748b; margin-top: 6px;">
                    Composite score: <span style="color:{color};font-weight:600;">{score:+d}</span>
                    &nbsp;·&nbsp; Updated {time_str}
                </div>
            </div>
            <div style="text-align: right; min-width: 180px;">
                <div style="font-size: 0.7rem; color: #475569; text-transform: uppercase;
                            letter-spacing: 1px; margin-bottom: 8px;">Sentiment Gauge</div>
                <div style="background: #1e293b; border-radius: 10px; height: 12px; overflow: hidden; width: 200px; margin-left: auto;">
                    <div style="width: {min(100, max(0, int(50 + score * 0.45)))}%; height: 100%;
                                background: linear-gradient(90deg, #ef4444, #f59e0b, #10b981); border-radius: 10px;"></div>
                </div>
                <div style="display:flex; justify-content:space-between; width:200px; margin: 4px 0 0 auto;
                            font-size:0.62rem; color:#475569;">
                    <span>BEARISH</span><span>NEUTRAL</span><span>BULLISH</span>
                </div>
            </div>
        </div>
        {signals_html}
    </div>
    """, unsafe_allow_html=True)


def _next_trading_day_ist(now_ist: datetime) -> datetime:
    """Return the next NSE trading session date (Mon–Fri)."""
    d = now_ist.date()
    for _ in range(7):
        d += timedelta(days=1)
        if d.weekday() < 5:
            return datetime.combine(d, now_ist.timetz())
    return now_ist + timedelta(days=1)


def analyze_tomorrow_market_outlook(
    market_data,
    option_data=None,
    fii_dii_data=None,
    breadth_data=None,
    turnover_delivery_data=None,
):
    """
    Forward-looking outlook for the next Indian cash session from all data feeds.
    Emphasizes Gift Nifty, US futures, FII/DII, options, breadth, and global cues.
    """
    score = 0
    bull_points = 0
    bear_points = 0
    drivers = []

    def _pct(name):
        d = market_data.get(name, {})
        p = d.get("pct")
        return p if p is not None else None

    def _add(delta, bull: bool, driver: str):
        nonlocal score, bull_points, bear_points
        score += delta
        drivers.append(driver)
        if delta > 0:
            bull_points += 1
        elif delta < 0:
            bear_points += 1

    # 1. Gift Nifty — strongest next-session cue
    gift_pct = _pct("Gift Nifty")
    if gift_pct is not None:
        gift_q = _market_quote_line(market_data, "Gift Nifty", gift_pct)
        if gift_pct >= 0.35:
            _add(22, True, f"Gift Nifty {gift_q} signals a positive gap-up bias")
        elif gift_pct <= -0.35:
            _add(-22, False, f"Gift Nifty {gift_q} signals a negative gap-down bias")
        elif gift_pct >= 0.1:
            _add(8, True, f"Gift Nifty mildly positive ({gift_q})")
        elif gift_pct <= -0.1:
            _add(-8, False, f"Gift Nifty mildly negative ({gift_q})")

    # 2. US futures — overnight global cue
    fut_names = ["S&P 500 Futures", "Nasdaq Futures", "Dow Futures"]
    fut_pcts = [_pct(n) for n in fut_names if _pct(n) is not None]
    if fut_pcts:
        avg_fut = sum(fut_pcts) / len(fut_pcts)
        if avg_fut >= 0.35:
            _add(18, True, f"US futures avg +{avg_fut:.2f}% — supportive overnight backdrop")
        elif avg_fut <= -0.35:
            _add(-18, False, f"US futures avg {avg_fut:.2f}% — risk-off global cue")
        elif avg_fut >= 0.1:
            _add(6, True, f"US futures slightly positive (+{avg_fut:.2f}%)")
        elif avg_fut <= -0.1:
            _add(-6, False, f"US futures slightly negative ({avg_fut:.2f}%)")

    # 3. US cash close
    us_pcts = [_pct(n) for n in ("Dow Jones", "S&P 500", "Nasdaq Composite") if _pct(n) is not None]
    if us_pcts:
        us_avg = sum(us_pcts) / len(us_pcts)
        if us_avg >= 0.5:
            _add(10, True, f"US markets closed strong (avg +{us_avg:.2f}%)")
        elif us_avg <= -0.5:
            _add(-10, False, f"US markets closed weak (avg {us_avg:.2f}%)")

    # 4. FII / DII cash flows
    if fii_dii_data:
        fii = (fii_dii_data.get("fii") or {})
        dii = (fii_dii_data.get("dii") or {})
        fii_net = fii.get("net_cr", 0)
        dii_net = dii.get("net_cr", 0)
        if fii_net >= 1500:
            _add(14, True, f"FII net buy ₹{fii_net:,.0f} Cr — foreign support")
        elif fii_net <= -1500:
            _add(-14, False, f"FII net sell ₹{abs(fii_net):,.0f} Cr — foreign outflow")
        elif fii_net >= 500:
            _add(5, True, f"FII mild net buy ₹{fii_net:,.0f} Cr")
        elif fii_net <= -500:
            _add(-5, False, f"FII mild net sell ₹{abs(fii_net):,.0f} Cr")
        if dii_net >= 2000 and fii_net < 0:
            _add(8, True, f"DII net buy ₹{dii_net:,.0f} Cr cushioning FII selling")
        elif dii_net <= -2000:
            _add(-6, False, f"DII net sell ₹{abs(dii_net):,.0f} Cr")

        history = fii_dii_data.get("history") or []
        if len(history) >= 5:
            recent_fii = sum(h.get("fii_net", 0) for h in history[-5:]) / 5
            if recent_fii >= 1000:
                _add(6, True, f"FII 5-day avg net buy ₹{recent_fii:,.0f} Cr — sustained inflow")
            elif recent_fii <= -1000:
                _add(-6, False, f"FII 5-day avg net sell ₹{abs(recent_fii):,.0f} Cr — sustained outflow")

    # 5. Options positioning
    if option_data:
        opt = analyze_options_sentiment(option_data)
        opt_score = opt["score"]
        score += int(opt_score * 0.18)
        if opt_score >= 20:
            bull_points += 1
            drivers.append(f"Nifty options {opt['verdict']} — supportive positioning")
        elif opt_score <= -20:
            bear_points += 1
            drivers.append(f"Nifty options {opt['verdict']} — cautious positioning")

    # 6. India VIX
    vix_pct = _pct("India VIX")
    if vix_pct is not None:
        vix_q = _market_quote_line(market_data, "India VIX", vix_pct)
        if vix_pct >= 4:
            _add(-12, False, f"India VIX {vix_q} — elevated fear into tomorrow")
        elif vix_pct >= 2:
            _add(-6, False, f"India VIX {vix_q} — caution warranted")
        elif vix_pct <= -4:
            _add(10, True, f"India VIX {vix_q} — fear subsiding")
        elif vix_pct <= -2:
            _add(5, True, f"India VIX {vix_q} — cooling")

    # 7. Market breadth
    br = analyze_breadth_sentiment(breadth_data)
    score += int(br["score"] * 0.85)
    if br["score"] >= 8:
        bull_points += 1
        drivers.append("Broad market breadth positive (Nifty 500 advances lead)")
    elif br["score"] <= -8:
        bear_points += 1
        drivers.append("Weak breadth — declines dominating Nifty 500")

    # 8. Asia session
    asia_pcts = [
        _pct(n) for n in (
            "Nikkei 225 (Japan)", "Hang Seng (HK)", "Shanghai (China)",
            "KOSPI (Korea)", "Taiwan Weighted",
        ) if _pct(n) is not None
    ]
    if asia_pcts:
        asia_avg = sum(asia_pcts) / len(asia_pcts)
        if asia_avg >= 0.4:
            _add(8, True, f"Asia markets positive (avg +{asia_avg:.2f}%)")
        elif asia_avg <= -0.4:
            _add(-8, False, f"Asia markets negative (avg {asia_avg:.2f}%)")

    # 9. Today's Nifty momentum (mild continuation bias)
    nifty_pct = _pct("Nifty 50")
    if nifty_pct is not None:
        nifty_q = _market_quote_line(market_data, "Nifty 50", nifty_pct)
        if nifty_pct >= 0.8:
            _add(5, True, f"Nifty 50 {nifty_q} — strong close, momentum carry")
        elif nifty_pct <= -0.8:
            _add(-5, False, f"Nifty 50 {nifty_q} — weak close, selling pressure")
        elif nifty_pct <= -0.3:
            _add(-3, False, f"Nifty 50 {nifty_q} — soft close")

    # 10. Delivery conviction
    if turnover_delivery_data:
        del_pct = turnover_delivery_data.get("avg_delivery_pct", 0)
        if del_pct >= 45:
            _add(4, True, f"High delivery {del_pct:.1f}% — conviction buying")
        elif del_pct < 28:
            _add(-3, False, f"Low delivery {del_pct:.1f}% — speculative tone")

    # Verdict
    if score >= 24:
        verdict = "BULLISH"
        label = "🟢 BULLISH OPEN EXPECTED"
        color = "#10b981"
        border_color = "#059669"
        emoji = "📈"
        tone = "positive bias"
    elif score >= 10:
        verdict = "MILDLY BULLISH"
        label = "🟢 MILDLY BULLISH"
        color = "#34d399"
        border_color = "#10b981"
        emoji = "↗️"
        tone = "slightly positive bias"
    elif score <= -24:
        verdict = "BEARISH"
        label = "🔴 BEARISH EXPECTATION"
        color = "#ef4444"
        border_color = "#dc2626"
        emoji = "📉"
        tone = "negative bias"
    elif score <= -10:
        verdict = "MILDLY BEARISH"
        label = "🔴 MILDLY BEARISH"
        color = "#f87171"
        border_color = "#ef4444"
        emoji = "↘️"
        tone = "slightly negative bias"
    else:
        verdict = "NEUTRAL"
        label = "🟡 NEUTRAL / RANGE-BOUND"
        color = "#f59e0b"
        border_color = "#d97706"
        emoji = "➡️"
        tone = "mixed signals — sideways action likely"

    aligned = max(bull_points, bear_points)
    total_signals = bull_points + bear_points
    if total_signals == 0:
        confidence = "Low"
    elif aligned >= 5 or (total_signals >= 4 and aligned >= total_signals - 1):
        confidence = "High"
    elif aligned >= 3:
        confidence = "Medium"
    else:
        confidence = "Low"

    top_bull = [d for d in drivers if any(
        w in d.lower() for w in ("positive", "buy", "support", "strong", "cooling", "inflow", "bullish")
    )][:2]
    top_bear = [d for d in drivers if any(
        w in d.lower() for w in ("negative", "sell", "weak", "outflow", "fear", "bearish", "caution", "declin")
    )][:2]

    explanation_parts = [
        "Composite read across Gift Nifty, US futures, FII/DII flows, options chain, "
        f"VIX, breadth, and global markets points to a <strong>{tone}</strong> for the next session."
    ]
    if top_bull:
        explanation_parts.append(f"Supporting factors: {'; '.join(top_bull)}.")
    if top_bear:
        explanation_parts.append(f"Headwinds: {'; '.join(top_bear)}.")
    if confidence == "Low":
        explanation_parts.append(
            "Signals are mixed — watch Gift Nifty and US futures before the open for confirmation."
        )
    elif confidence == "High":
        explanation_parts.append(
            "Multiple indicators align — conviction is relatively higher, but manage risk around key levels."
        )
    explanation = " ".join(explanation_parts)

    return {
        "verdict": verdict,
        "label": label,
        "color": color,
        "border_color": border_color,
        "emoji": emoji,
        "score": score,
        "confidence": confidence,
        "explanation": explanation,
        "drivers": drivers[:8],
    }


def _render_tomorrow_outlook_banner(outlook, now_ist):
    """Render the top tomorrow-market outlook hero section."""
    next_day = _next_trading_day_ist(now_ist)
    session_date = next_day.strftime("%A, %d %b %Y")
    time_str = now_ist.strftime("%H:%M IST")
    color = outlook["color"]
    border = outlook["border_color"]
    conf = outlook["confidence"]
    conf_color = "#10b981" if conf == "High" else "#f59e0b" if conf == "Medium" else "#94a3b8"

    drivers_html = ""
    if outlook.get("drivers"):
        items = "".join(
            f'<li style="margin-bottom:6px;color:#94a3b8;font-size:0.8rem;">{d}</li>'
            for d in outlook["drivers"][:6]
        )
        drivers_html = f'<ul style="margin:12px 0 0 18px;padding:0;">{items}</ul>'

    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #0a1628 0%, #0f2847 50%, #0a1628 100%);
                border: 2px solid {border}; border-radius: 18px; padding: 26px 30px; margin-bottom: 16px;
                box-shadow: 0 4px 24px rgba(0,0,0,0.35);">
        <div style="display:flex;flex-wrap:wrap;align-items:flex-start;justify-content:space-between;gap:20px;">
            <div style="flex:1;min-width:260px;">
                <div style="font-size:0.7rem;color:#64748b;text-transform:uppercase;font-weight:700;
                            letter-spacing:2.5px;margin-bottom:8px;">
                    🔮 TOMORROW'S MARKET OUTLOOK · {session_date}
                </div>
                <div style="font-size:2.4rem;font-weight:800;color:{color};line-height:1.15;margin-bottom:10px;">
                    {outlook['emoji']} {outlook['label']}
                </div>
                <div style="font-size:0.88rem;color:#cbd5e1;line-height:1.65;max-width:720px;">
                    {outlook['explanation']}
                </div>
                {drivers_html}
            </div>
            <div style="min-width:200px;text-align:right;">
                <div style="font-size:0.68rem;color:#475569;text-transform:uppercase;letter-spacing:1px;
                            margin-bottom:6px;">Outlook Score</div>
                <div style="font-size:1.8rem;font-weight:700;color:{color};">{outlook['score']:+d}</div>
                <div style="margin-top:12px;font-size:0.68rem;color:#475569;text-transform:uppercase;
                            letter-spacing:1px;margin-bottom:4px;">Confidence</div>
                <div style="font-size:1rem;font-weight:600;color:{conf_color};">{conf}</div>
                <div style="background:#1e293b;border-radius:10px;height:10px;overflow:hidden;width:180px;
                            margin:14px 0 0 auto;">
                    <div style="width:{min(100, max(0, int(50 + outlook['score'] * 0.42)))}%;height:100%;
                                background:linear-gradient(90deg,#ef4444,#f59e0b,#10b981);border-radius:10px;"></div>
                </div>
                <div style="font-size:0.62rem;color:#475569;margin-top:6px;">Updated {time_str}</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ─── News Fetchers ──────────────────────────────────────────────────────────

from app.market_pulse.market_pulse_feeds import (
    fetch_analyst_calls as _fetch_analyst_calls_raw,
    fetch_global_news as _fetch_global_news_raw,
    fetch_news as _fetch_news_raw,
    get_upcoming_events as _get_upcoming_events_raw,
)


def fetch_news():
    return _fetch_news_raw()


def fetch_global_news():
    return _fetch_global_news_raw()


def fetch_analyst_calls():
    return _fetch_analyst_calls_raw()


def get_upcoming_events():
    return _get_upcoming_events_raw()


def _render_analyst_calls_section(calls: list[dict], limit: int = 20) -> None:
    st.markdown(
        '<div class="section-header-ns" style="margin-top:20px;">'
        "📢 Analyst Calls & Brokerage Recommendations</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Live **Moneycontrol** brokerage recos & stock ideas RSS — sorted by action (Buy/Sell) "
        "and recency. Refreshes with **🔄 Refresh Market Data**."
    )
    if not calls:
        st.info("No recent analyst calls found. Try refreshing or check back during market hours.")
        return

    display = calls[:limit]
    rows = []
    for c in display:
        action = c.get("action", "—")
        action_color = "#10b981" if action == "BUY" else "#ef4444" if action == "SELL" else "#f59e0b"
        rows.append({
            "Action": action,
            "Stock": c.get("stock", "—"),
            "Brokerage": c.get("brokerage", "—"),
            "Headline": c.get("title", "")[:90],
            "When": c.get("published", "—"),
            "Source": c.get("source", "").replace("Moneycontrol ", "MC "),
        })

    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    for c in display[:8]:
        action = c.get("action", "—")
        ac = "#10b981" if action == "BUY" else "#ef4444" if action == "SELL" else "#f59e0b"
        st.markdown(f"""
        <div class="news-card-ns" style="border-left-color:{ac};">
            <div style="font-size:0.88rem;font-weight:500;color:#cbd5e1;margin-bottom:6px;">
                <span style="color:{ac};font-weight:700;margin-right:8px;">{action}</span>
                <a href="{c.get('link', '#')}" target="_blank" style="color:#cbd5e1;text-decoration:none;">
                    {c.get('title', '')}</a>
            </div>
            <div style="font-size:0.72rem;color:#475569;">
                <span style="color:#2563eb;font-weight:600;">{c.get('brokerage', '—')}</span>
                &nbsp;·&nbsp;{c.get('stock', '—')}
                &nbsp;·&nbsp;{c.get('published', '')}
            </div>
        </div>""", unsafe_allow_html=True)


def _render_upcoming_events_section(india_events: list, global_events: list, ref_date: date) -> None:
    st.markdown(
        '<div class="section-header-ns" style="margin-top:20px;">'
        "📅 Upcoming Important Events</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        f"Showing events **on or after {ref_date.strftime('%d %b %Y')}** (IST) only — past dates are hidden."
    )
    if not india_events and not global_events:
        st.info("No major scheduled macro events in the catalog from today onward.")
        return

    ev_col1, ev_col2 = st.columns(2)
    with ev_col1:
        st.markdown(
            '<div style="font-size:0.82rem;font-weight:600;color:#94a3b8;margin-bottom:10px;">'
            "🇮🇳 India Events</div>",
            unsafe_allow_html=True,
        )
        if not india_events:
            st.caption("No upcoming India events in catalog.")
        for e in india_events:
            impact_cls = e["impact"].lower()
            impact_color = "#ef4444" if impact_cls == "high" else "#f59e0b" if impact_cls == "medium" else "#10b981"
            st.markdown(f"""
            <div class="event-card-ns" style="border-left: 3px solid {impact_color};">
                <div style="font-size: 0.88rem; font-weight: 500; color: #cbd5e1;">{e['title']}</div>
                <div style="margin: 4px 0;">
                    <span style="color: {impact_color}; font-size: 0.72rem; font-weight: 600;">● {e['impact']} IMPACT</span>
                    <span style="font-size: 0.75rem; color: #64748b; margin-left:10px;">📅 {e['date']}</span>
                </div>
                <div style="font-size:0.77rem;color:#64748b;margin-top:4px;">{e['detail']}</div>
            </div>""", unsafe_allow_html=True)

    with ev_col2:
        st.markdown(
            '<div style="font-size:0.82rem;font-weight:600;color:#94a3b8;margin-bottom:10px;">'
            "🌐 Global Events</div>",
            unsafe_allow_html=True,
        )
        if not global_events:
            st.caption("No upcoming global events in catalog.")
        for e in global_events:
            impact_cls = e["impact"].lower()
            impact_color = "#ef4444" if impact_cls == "high" else "#f59e0b" if impact_cls == "medium" else "#10b981"
            st.markdown(f"""
            <div class="event-card-ns" style="border-left: 3px solid {impact_color};">
                <div style="font-size: 0.88rem; font-weight: 500; color: #cbd5e1;">{e['title']}</div>
                <div style="margin: 4px 0;">
                    <span style="color: {impact_color}; font-size: 0.72rem; font-weight: 600;">● {e['impact']} IMPACT</span>
                    <span style="font-size: 0.75rem; color: #64748b; margin-left:10px;">📅 {e['date']}</span>
                </div>
                <div style="font-size:0.77rem;color:#64748b;margin-top:4px;">{e['detail']}</div>
            </div>""", unsafe_allow_html=True)


# ─── AI Prompt & Summary ────────────────────────────────────────────────────

def build_ai_prompt(market_data, news_articles, global_news_articles, india_events, global_events,
                    option_data=None, fii_dii_data=None, breadth_data=None, turnover_delivery_data=None,
                    analyst_calls=None):
    lines = ["=== CURRENT MARKET DATA ==="]
    for name, d in market_data.items():
        p = fmt_price(d['price']) if d['price'] else "N/A"
        pct_val = f"{d['pct']:+.2f}%" if d['pct'] is not None else "N/A"
        lines.append(f"{name}: {p} ({pct_val})")

    if fii_dii_data:
        lines.append("\n=== FII / DII FLOWS (₹ Cr) ===")
        if fii_dii_data.get("fii"):
            f = fii_dii_data["fii"]
            lines.append(f"FII: Buy {f['buy_cr']:,.0f} · Sell {f['sell_cr']:,.0f} · Net {f['net_cr']:+,.0f}")
        if fii_dii_data.get("dii"):
            d = fii_dii_data["dii"]
            lines.append(f"DII: Buy {d['buy_cr']:,.0f} · Sell {d['sell_cr']:,.0f} · Net {d['net_cr']:+,.0f}")

    if breadth_data:
        lines.append("\n=== MARKET BREADTH (NIFTY) ===")
        indices = _breadth_indices_map(breadth_data)
        groups = breadth_data.get("groups") or {}
        for group in _NIFTY_BREADTH_GROUP_ORDER:
            if group not in _AI_BREADTH_GROUPS:
                continue
            names = groups.get(group) or [
                n for n, b in indices.items() if b.get("group") == group
            ]
            if not names:
                continue
            label = _NIFTY_BREADTH_GROUP_LABELS.get(group, group.title())
            lines.append(f"\n{label}:")
            for idx_name in names:
                b = indices.get(idx_name)
                if not b:
                    continue
                lines.append(
                    f"  {idx_name}: {b['advances']} advances, {b['declines']} declines, "
                    f"{b['unchanged']} unchanged ({fmt_last_pct(b.get('last'), b.get('pct'))})"
                )

    if turnover_delivery_data:
        lines.append("\n=== CASH TURNOVER & DELIVERY ===")
        lines.append(f"Trade Date: {turnover_delivery_data.get('trade_date', 'N/A')}")
        lines.append(f"Total Cash Turnover: ₹{turnover_delivery_data.get('total_turnover_cr', 0):,.0f} Cr")
        lines.append(f"Market Avg Delivery: {turnover_delivery_data.get('avg_delivery_pct', 0):.1f}%")

    # Options chain data
    if option_data:
        lines.append("\n=== NIFTY OPTIONS CHAIN ANALYSIS ===")
        lines.append(f"Nifty Spot: {option_data['underlying']:,.2f}")
        lines.append(f"Current Expiry: {option_data['current_expiry']}")
        lines.append(f"PCR (OI): {option_data['pcr_oi']:.4f}")
        lines.append(f"PCR (Volume): {option_data['pcr_vol']:.4f}")
        lines.append(f"Max Pain: {option_data['max_pain']:,.0f}")
        lines.append(f"Total Call OI: {option_data['total_call_oi']:,.0f}")
        lines.append(f"Total Put OI: {option_data['total_put_oi']:,.0f}")
        if option_data["top_call_oi"]:
            lines.append("Highest Call OI Strikes (Resistance):")
            for s in option_data["top_call_oi"][:3]:
                lines.append(f"  Strike {s['strike']:,.0f}: OI={s['ce_oi']:,.0f}, ChgOI={s['ce_chg_oi']:+,.0f}")
        if option_data["top_put_oi"]:
            lines.append("Highest Put OI Strikes (Support):")
            for s in option_data["top_put_oi"][:3]:
                lines.append(f"  Strike {s['strike']:,.0f}: OI={s['pe_oi']:,.0f}, ChgOI={s['pe_chg_oi']:+,.0f}")
        # Include verdict
        sentiment = analyze_options_sentiment(option_data)
        lines.append(f"Options Verdict: {sentiment['verdict']} (Score: {sentiment['score']})")

    lines.append("\n=== INDIA & CRYPTO NEWS ===")
    for a in news_articles[:12]:
        lines.append(f"- [{a['source']}] {a['title']}")
    lines.append("\n=== US MARKETS & GEOPOLITICS NEWS ===")
    for a in global_news_articles[:12]:
        lines.append(f"- [{a['source']}] {a['title']}")
    if analyst_calls:
        lines.append("\n=== ANALYST CALLS / BROKERAGE RECOS ===")
        for c in analyst_calls[:15]:
            lines.append(
                f"- [{c.get('action', '—')}] {c.get('stock', '—')} "
                f"({c.get('brokerage', '—')}): {c.get('title', '')}"
            )
    lines.append("\n=== UPCOMING INDIA EVENTS ===")
    for e in india_events:
        lines.append(f"- [{e['impact']}] {e['title']} | {e['date']}")
    lines.append("\n=== UPCOMING GLOBAL EVENTS ===")
    for e in global_events:
        lines.append(f"- [{e['impact']}] {e['title']} | {e['date']}")
    return "\n".join(lines)

def get_ai_summary(prompt_data, provider, model, api_key):
    system = """You are an expert Indian stock market analyst with deep knowledge of NSE, BSE, 
macroeconomics, FII/DII flows, RBI policy, Options chain analysis, and global market linkages.
Analyze the given market data, options chain data, news headlines and upcoming events. 
Provide a structured, actionable market intelligence summary covering:
1. Overall Market Sentiment (Bullish/Bearish/Neutral with reasoning)
2. Key Market Drivers Today (3-4 points)
3. Nifty Options Chain Insight (PCR interpretation, Max Pain, Support/Resistance from OI)
4. Impact Analysis of Global Signals on Indian Markets
5. Upcoming Event Risks & Opportunities 
6. Sectors to Watch (with reasoning)
7. Short-term Market Outlook (1-5 days)
Be specific, data-driven and concise. Format with clear sections."""

    user_msg = f"Analyze and summarize the following market data for Indian stock markets:\n\n{prompt_data}"

    try:
        if provider == "Groq (LLaMA)":
            client = Groq(api_key=api_key)
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg}
                ],
                max_tokens=2000,
                temperature=0.4
            )
            return resp.choices[0].message.content
        elif provider == "Google Gemini":
            if GENAI_NEW:
                client = genai_new.Client(api_key=api_key)
                combined = system + "\n\n" + user_msg
                resp = client.models.generate_content(model=model, contents=combined)
                return resp.text
            else:
                genai.configure(api_key=api_key)
                gmodel = genai.GenerativeModel(model, system_instruction=system)
                resp = gmodel.generate_content(user_msg)
                return resp.text
    except Exception as e:
        return f"❌ AI Summary Error: {str(e)}\n\nPlease check your API key and model selection."


# ─── UI Components ──────────────────────────────────────────────────────────

def render_metric_card(
    label,
    price,
    pct,
    prefix="",
    suffix="",
    decimals=2,
    sr: dict | None = None,
):
    price_str = f"{prefix}{fmt_price(price, decimals)}{suffix}" if price is not None else "—"
    change_str, cls = fmt_change(pct)
    chg_color = "#10b981" if cls == "pos" else "#ef4444" if cls == "neg" else "#94a3b8"
    sr_block = ""
    if sr:
        sr_block = (
            f'<div style="font-size:0.68rem;color:#64748b;margin-top:8px;line-height:1.45;">'
            f'<span style="color:#34d399;">S1</span> {_fmt_sr_level(sr.get("s1"))} · '
            f'<span style="color:#34d399;">S2</span> {_fmt_sr_level(sr.get("s2"))}<br>'
            f'<span style="color:#f87171;">R1</span> {_fmt_sr_level(sr.get("r1"))} · '
            f'<span style="color:#f87171;">R2</span> {_fmt_sr_level(sr.get("r2"))}'
            f"</div>"
        )
    return f"""
    <div style="background: #0f1729; border: 1px solid #1e3a5f; border-radius: 12px; padding: 16px 20px;">
        <div style="font-size: 0.72rem; color: #64748b; text-transform: uppercase; font-weight: 500; margin-bottom: 8px;">{label}</div>
        <div style="display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:8px;">
            <div style="font-size: 1.35rem; font-weight: 700; color: #e2e8f0; line-height: 1.1;">{price_str}</div>
            <div style="font-size: 0.88rem; font-weight: 600; color: {chg_color}; white-space: nowrap;">{change_str}</div>
        </div>
        {sr_block}
    </div>"""


def render_energy_metric_card(
    label: str,
    last: float | None,
    change: float | None,
    pct: float | None,
    *,
    prefix: str = "$",
    decimals: int = 2,
) -> str:
    """Oilprice-style card: last, absolute change, and % change."""
    last_str = f"{prefix}{fmt_price(last, decimals)}" if last is not None else "—"
    pct_str, cls = fmt_change(pct)
    pct_color = "#10b981" if cls == "pos" else "#ef4444" if cls == "neg" else "#94a3b8"
    if change is not None:
        chg_color = "#10b981" if change >= 0 else "#ef4444"
        chg_sign = "+" if change >= 0 else ""
        chg_part = f'<span style="color:{chg_color};">{chg_sign}{change:,.{decimals}f}</span>'
    else:
        chg_part = '<span style="color:#94a3b8;">—</span>'
    return f"""
    <div style="background: #0f1729; border: 1px solid #1e3a5f; border-radius: 12px; padding: 16px 20px;">
        <div style="font-size: 0.72rem; color: #64748b; text-transform: uppercase; font-weight: 500; margin-bottom: 8px;">{label}</div>
        <div style="display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:8px;">
            <div style="font-size: 1.35rem; font-weight: 700; color: #e2e8f0; line-height: 1.1;">{last_str}</div>
            <div style="font-size: 0.88rem; font-weight: 600; color: {pct_color}; white-space: nowrap;">{pct_str}</div>
        </div>
        <div style="font-size: 0.76rem; color: #94a3b8; margin-top: 6px;">Chg {chg_part}</div>
    </div>"""


def _render_market_section(
    title,
    items,
    market_data,
    cols_count=4,
    prefix_map=None,
    suffix_map=None,
    decimals_map=None,
    sr_map: dict | None = None,
):
    """Helper to render a row of metric cards for a market section."""
    st.markdown(f'<div class="section-header-ns" style="margin-top:20px;">{title}</div>', unsafe_allow_html=True)
    cols = st.columns(cols_count)
    for i, name in enumerate(items):
        d = market_data.get(name, {})
        pfx = prefix_map.get(name, "") if prefix_map else ""
        sfx = suffix_map.get(name, "") if suffix_map else ""
        dec = decimals_map.get(name, 2) if decimals_map else 2
        sr = (sr_map or {}).get(name)
        with cols[i % cols_count]:
            st.markdown(
                render_metric_card(
                    name, d.get("price"), d.get("pct"),
                    prefix=pfx, suffix=sfx, decimals=dec, sr=sr,
                ),
                unsafe_allow_html=True,
            )
            if (i + 1) % cols_count == 0 and i < len(items) - 1:
                st.markdown("<div style='margin-bottom: 10px;'></div>", unsafe_allow_html=True)


def _render_market_flows_section(fii_dii_data, breadth_data, turnover_delivery_data):
    """Render FII/DII, market breadth, turnover and delivery sentiment section."""
    st.markdown(
        '<div class="section-header-ns" style="margin-top:20px;">'
        "💹 Cash Market Flows — FII/DII · Breadth · Turnover · Delivery"
        "</div>",
        unsafe_allow_html=True,
    )

    if not fii_dii_data and not breadth_data and not turnover_delivery_data:
        st.warning(
            "⚠️ Unable to fetch cash-market flow data from NSE. "
            "Click **Refresh Market Data** or check during/after market hours."
        )
        return

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        fii = (fii_dii_data or {}).get("fii") or {}
        if fii:
            net = fii.get("net_cr", 0)
            color = "#10b981" if net >= 0 else "#ef4444"
            st.markdown(f"""
            <div style="background:#0f1729;border:1px solid #1e3a5f;border-radius:12px;padding:16px;">
                <div style="font-size:0.72rem;color:#64748b;text-transform:uppercase;">FII Net (₹ Cr)</div>
                <div style="font-size:1.4rem;font-weight:700;color:{color};">{net:+,.0f}</div>
                <div style="font-size:0.7rem;color:#64748b;">Buy {fii.get('buy_cr',0):,.0f} · Sell {fii.get('sell_cr',0):,.0f}</div>
            </div>""", unsafe_allow_html=True)
        else:
            st.metric("FII Net (₹ Cr)", "N/A")

    with c2:
        dii = (fii_dii_data or {}).get("dii") or {}
        if dii:
            net = dii.get("net_cr", 0)
            color = "#10b981" if net >= 0 else "#ef4444"
            st.markdown(f"""
            <div style="background:#0f1729;border:1px solid #1e3a5f;border-radius:12px;padding:16px;">
                <div style="font-size:0.72rem;color:#64748b;text-transform:uppercase;">DII Net (₹ Cr)</div>
                <div style="font-size:1.4rem;font-weight:700;color:{color};">{net:+,.0f}</div>
                <div style="font-size:0.7rem;color:#64748b;">Buy {dii.get('buy_cr',0):,.0f} · Sell {dii.get('sell_cr',0):,.0f}</div>
            </div>""", unsafe_allow_html=True)
        else:
            st.metric("DII Net (₹ Cr)", "N/A")

    with c3:
        if turnover_delivery_data:
            st.markdown(f"""
            <div style="background:#0f1729;border:1px solid #1e3a5f;border-radius:12px;padding:16px;">
                <div style="font-size:0.72rem;color:#64748b;text-transform:uppercase;">Cash Turnover (₹ Cr)</div>
                <div style="font-size:1.4rem;font-weight:700;color:#60a5fa;">
                    {turnover_delivery_data['total_turnover_cr']:,.0f}
                </div>
                <div style="font-size:0.7rem;color:#64748b;">
                    {turnover_delivery_data.get('trade_date', '')} · {turnover_delivery_data.get('total_stocks', 0)} EQ stocks
                </div>
            </div>""", unsafe_allow_html=True)
        else:
            st.metric("Cash Turnover (₹ Cr)", "N/A")

    with c4:
        if turnover_delivery_data:
            del_pct = turnover_delivery_data.get("avg_delivery_pct", 0)
            color = "#10b981" if del_pct >= 45 else "#f59e0b" if del_pct >= 30 else "#ef4444"
            st.markdown(f"""
            <div style="background:#0f1729;border:1px solid #1e3a5f;border-radius:12px;padding:16px;">
                <div style="font-size:0.72rem;color:#64748b;text-transform:uppercase;">Market Avg Delivery %</div>
                <div style="font-size:1.4rem;font-weight:700;color:{color};">{del_pct:.1f}%</div>
                <div style="font-size:0.7rem;color:#64748b;">Qty-weighted across EQ universe</div>
            </div>""", unsafe_allow_html=True)
        else:
            st.metric("Market Avg Delivery %", "N/A")

    history = (fii_dii_data or {}).get("history") or []
    if history:
        st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)
        hist_df = pd.DataFrame(history)
        fig_fii = go.Figure()
        fig_fii.add_trace(go.Bar(
            name="FII Net (₹ Cr)",
            x=hist_df["date"],
            y=hist_df["fii_net"],
            marker_color="rgba(239, 68, 68, 0.75)",
            hovertemplate="%{x}<br>FII Net: %{y:+,.0f} Cr<extra></extra>",
        ))
        fig_fii.add_trace(go.Bar(
            name="DII Net (₹ Cr)",
            x=hist_df["date"],
            y=hist_df["dii_net"],
            marker_color="rgba(16, 185, 129, 0.75)",
            hovertemplate="%{x}<br>DII Net: %{y:+,.0f} Cr<extra></extra>",
        ))
        fig_fii.update_layout(
            title=dict(
                text="FII / DII Cash Market Net Flows — Last 30 Trading Days",
                font=dict(size=14, color="#cbd5e1"),
            ),
            barmode="group",
            height=360,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(15, 23, 41, 0.8)",
            font=dict(color="#94a3b8", size=10),
            xaxis=dict(title="", gridcolor="#1e3a5f", tickangle=-45),
            yaxis=dict(title="Net Flow (₹ Cr)", gridcolor="#1e3a5f", zerolinecolor="#334155"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=60, r=20, t=60, b=90),
        )
        st.plotly_chart(fig_fii, width="stretch", config={"displayModeBar": False})
        source = (fii_dii_data or {}).get("source", "stockedge.com")
        st.caption(
            f"CM provisional cash flows · Source: {source} "
            f"([StockEdge FII Activity](https://web.stockedge.com/fii-activity))"
        )

    if fii_dii_data and fii_dii_data.get("date"):
        st.caption(f"Latest FII/DII buy/sell as of: {fii_dii_data['date']}")

    if breadth_data:
        indices = _breadth_indices_map(breadth_data)
        st.markdown("<div style='margin-top:12px;'></div>", unsafe_allow_html=True)
        st.caption(
            f"📊 **Nifty Index Breadth** ({len(indices)} indices) is in the "
            "**Market Pulse → Nifty Index Breadth** section (lazy-loaded)."
        )
        monthly_count = len((breadth_data or {}).get("monthly") or {})
        st.caption(
            f"📅 **Nifty 1-Month Performance & Constituent Movers** ({monthly_count} indices) is in "
            "**Market Pulse → Nifty 1-Month Performance** (lazy-loaded 2 per click)."
        )

    if turnover_delivery_data:
        t1, t2, t3 = st.columns(3)
        with t1:
            st.markdown("**🔥 Highest Delivery % (liquid stocks)**")
            rows = [{
                "Symbol": s["symbol"],
                "Delivery %": f"{s['deliv_per']:.1f}",
                "Qty (L)": f"{s['qty']/100000:.1f}",
            } for s in turnover_delivery_data.get("high_delivery", [])]
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')
        with t2:
            st.markdown("**💨 Lowest Delivery % (speculative)**")
            rows = [{
                "Symbol": s["symbol"],
                "Delivery %": f"{s['deliv_per']:.1f}",
                "Qty (L)": f"{s['qty']/100000:.1f}",
            } for s in turnover_delivery_data.get("low_delivery", [])]
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')
        with t3:
            st.markdown("**💰 Highest Turnover (₹ Lacs)**")
            rows = [{
                "Symbol": s["symbol"],
                "Turnover": f"{s['turnover_lacs']:,.0f}",
                "Del %": f"{s['deliv_per']:.1f}",
            } for s in turnover_delivery_data.get("high_turnover", [])]
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')

        with st.expander(
            "📈 1-Month Trend Charts — Delivery % & Turnover",
            expanded=False,
        ):
            load_trends = st.checkbox(
                "Load 1-month bhavcopy history for trend charts",
                value=False,
                key="ns_load_delivery_turnover_trends",
                help="Downloads ~22 trading days of NSE bhavcopy (may take 15–30 seconds on first load; cached 1 hour).",
            )
            if load_trends:
                with nullcontext():
                    history = fetch_nse_delivery_turnover_history()
                if history:
                    _render_delivery_turnover_monthly_trends(turnover_delivery_data, history)
                else:
                    st.warning(
                        "Unable to load historical bhavcopy data. "
                        "NSE archives may be temporarily unavailable."
                    )
            else:
                st.caption(
                    "Enable the checkbox above to plot increasing vs decreasing 1-month trends "
                    "for symbols in today's delivery and turnover leaderboards."
                )


def _add_strike_reference_line(fig, strike, y_top, *, y_bottom=0, line_dash="dash",
                               line_color="#c084fc", line_width=2,
                               annotation_text="", annotation_position="top"):
    """Add a vertical strike reference line via scatter trace (avoids Plotly add_vline bug)."""
    try:
        x = float(strike)
    except (TypeError, ValueError):
        return
    if not np.isfinite(x):
        return

    fig.add_trace(go.Scatter(
        x=[x, x],
        y=[y_bottom, y_top],
        mode="lines",
        line=dict(dash=line_dash, color=line_color, width=line_width),
        showlegend=False,
        hoverinfo="skip",
    ))
    if annotation_text:
        y_ann = y_top if annotation_position == "top" else y_bottom
        fig.add_annotation(
            x=x,
            y=y_ann,
            text=annotation_text,
            showarrow=False,
            yanchor="bottom" if annotation_position == "top" else "top",
            font=dict(color=line_color, size=10),
            xanchor="center",
        )


def _render_options_section(option_data, sentiment):
    """Render the Nifty Options Chain Analysis section."""
    st.markdown('<div class="section-header-ns" style="margin-top:20px;">📊 Nifty Options Chain Analysis</div>', unsafe_allow_html=True)

    if option_data is None:
        st.warning(
            "⚠️ Unable to fetch Options Chain data. NSE v3 API may be blocked, or add your "
            "**Groww Bearer token** in the sidebar for automatic fallback. "
            "Data is most reliable during market hours (9:15 AM — 3:30 PM IST)."
        )
        return

    source = option_data.get("source", "NSE")
    st.caption(f"Options data source: **{source}**")

    # ── Row 1: Key Metrics ──
    mc1, mc2, mc3, mc4, mc5 = st.columns(5)
    with mc1:
        st.markdown(render_metric_card("Nifty Spot", option_data["underlying"], None, decimals=2), unsafe_allow_html=True)
    with mc2:
        pcr_color = "#10b981" if option_data["pcr_oi"] > 1.0 else "#ef4444" if option_data["pcr_oi"] < 0.7 else "#f59e0b"
        st.markdown(f"""
        <div style="background: #0f1729; border: 1px solid #1e3a5f; border-radius: 12px; padding: 16px 20px;">
            <div style="font-size: 0.72rem; color: #64748b; text-transform: uppercase; font-weight: 500; margin-bottom: 6px;">PCR (OI)</div>
            <div style="font-size: 1.4rem; font-weight: 700; color: {pcr_color}; line-height: 1;">{option_data['pcr_oi']:.4f}</div>
            <div style="font-size: 0.7rem; color: #64748b; margin-top: 4px;">Vol PCR: {option_data['pcr_vol']:.4f}</div>
        </div>""", unsafe_allow_html=True)
    with mc3:
        st.markdown(f"""
        <div style="background: #0f1729; border: 1px solid #1e3a5f; border-radius: 12px; padding: 16px 20px;">
            <div style="font-size: 0.72rem; color: #64748b; text-transform: uppercase; font-weight: 500; margin-bottom: 6px;">MAX PAIN</div>
            <div style="font-size: 1.4rem; font-weight: 700; color: #c084fc; line-height: 1;">{option_data['max_pain']:,.0f}</div>
            <div style="font-size: 0.7rem; color: #64748b; margin-top: 4px;">Expiry: {option_data['current_expiry']}</div>
        </div>""", unsafe_allow_html=True)
    with mc4:
        st.markdown(f"""
        <div style="background: #0f1729; border: 1px solid #1e3a5f; border-radius: 12px; padding: 16px 20px;">
            <div style="font-size: 0.72rem; color: #64748b; text-transform: uppercase; font-weight: 500; margin-bottom: 6px;">TOTAL CALL OI</div>
            <div style="font-size: 1.4rem; font-weight: 700; color: #ef4444; line-height: 1;">{option_data['total_call_oi']:,.0f}</div>
            <div style="font-size: 0.7rem; color: #64748b; margin-top: 4px;">Vol: {option_data['total_call_vol']:,.0f}</div>
        </div>""", unsafe_allow_html=True)
    with mc5:
        st.markdown(f"""
        <div style="background: #0f1729; border: 1px solid #1e3a5f; border-radius: 12px; padding: 16px 20px;">
            <div style="font-size: 0.72rem; color: #64748b; text-transform: uppercase; font-weight: 500; margin-bottom: 6px;">TOTAL PUT OI</div>
            <div style="font-size: 1.4rem; font-weight: 700; color: #10b981; line-height: 1;">{option_data['total_put_oi']:,.0f}</div>
            <div style="font-size: 0.7rem; color: #64748b; margin-top: 4px;">Vol: {option_data['total_put_vol']:,.0f}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)

    # ── Row 2: Directional Verdict + OI Chart ──
    col_verdict, col_chart = st.columns([1, 2])

    with col_verdict:
        vcolor = sentiment["verdict_color"]
        score = sentiment["score"]
        score_bar_width = min(100, max(0, int(50 + score * 0.5)))  # map -100..100 to 0..100
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #0f1729 0%, #0d1f3c 100%); border: 2px solid {vcolor}; border-radius: 16px; padding: 24px; text-align: center;">
            <div style="font-size: 0.72rem; color: #64748b; text-transform: uppercase; font-weight: 600; letter-spacing: 2px; margin-bottom: 12px;">OPTIONS DIRECTIONAL VERDICT</div>
            <div style="font-size: 2rem; font-weight: 800; color: {vcolor}; margin-bottom: 8px;">{sentiment['verdict']}</div>
            <div style="font-size: 0.8rem; color: #94a3b8; margin-bottom: 12px;">Sentiment Score: {score:+d}/100</div>
            <div style="background: #1e293b; border-radius: 8px; height: 8px; overflow: hidden; margin: 0 16px;">
                <div style="width: {score_bar_width}%; height: 100%; background: linear-gradient(90deg, #ef4444, #f59e0b, #10b981); border-radius: 8px;"></div>
            </div>
            <div style="display:flex; justify-content:space-between; margin: 4px 16px 0; font-size:0.6rem; color:#475569;">
                <span>BEARISH</span><span>NEUTRAL</span><span>BULLISH</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Reasoning bullets
        st.markdown("<div style='margin-top:12px;'></div>", unsafe_allow_html=True)
        for reason in sentiment["reasons"]:
            st.markdown(f"""
            <div style="background: #0f1729; border: 1px solid #1e3a5f; border-radius: 8px; padding: 10px 14px; margin-bottom: 6px; font-size: 0.78rem; color: #cbd5e1; line-height: 1.5;">
                {reason}
            </div>""", unsafe_allow_html=True)

    with col_chart:
        # OI Distribution Chart (Call OI vs Put OI by strike)
        strikes = option_data["strikes"]
        underlying = option_data["underlying"]

        if strikes:
            # Filter strikes ±15 around ATM
            atm_strike = min(strikes, key=lambda x: abs(x["strike"] - underlying))["strike"]
            nearby = [s for s in strikes if abs(s["strike"] - atm_strike) <= 15 * 50]  # ±15 strikes with 50pt gap
            if len(nearby) > 30:
                nearby = sorted(nearby, key=lambda x: abs(x["strike"] - atm_strike))[:30]
            nearby = sorted(nearby, key=lambda x: x["strike"])

            strike_labels = [int(s["strike"]) for s in nearby]
            call_ois = [s["ce_oi"] for s in nearby]
            put_ois = [s["pe_oi"] for s in nearby]
            call_chg = [s["ce_chg_oi"] for s in nearby]
            put_chg = [s["pe_chg_oi"] for s in nearby]

            fig = go.Figure()
            fig.add_trace(go.Bar(
                name="Call OI", x=strike_labels, y=call_ois,
                marker_color="rgba(239, 68, 68, 0.7)",
                hovertemplate="Strike: %{x}<br>Call OI: %{y:,.0f}<extra></extra>"
            ))
            fig.add_trace(go.Bar(
                name="Put OI", x=strike_labels, y=put_ois,
                marker_color="rgba(16, 185, 129, 0.7)",
                hovertemplate="Strike: %{x}<br>Put OI: %{y:,.0f}<extra></extra>"
            ))

            # Add ATM and Max Pain reference lines (scatter overlay — no add_vline)
            oi_y_max = max(call_ois + put_ois) if (call_ois or put_ois) else 1
            oi_y_top = oi_y_max * 1.05 if oi_y_max > 0 else 1
            _add_strike_reference_line(
                fig, atm_strike, oi_y_top, line_dash="dash", line_color="#c084fc", line_width=2,
                annotation_text=f"ATM: {int(atm_strike)}", annotation_position="top",
            )
            max_pain = option_data.get("max_pain")
            if max_pain is not None and np.isfinite(float(max_pain)):
                _add_strike_reference_line(
                    fig, max_pain, oi_y_top, line_dash="dot", line_color="#f59e0b", line_width=2,
                    annotation_text=f"Max Pain: {int(max_pain)}", annotation_position="bottom",
                )

            fig.update_layout(
                title=dict(text="Open Interest Distribution by Strike Price", font=dict(size=14, color="#cbd5e1")),
                barmode='group',
                height=400,
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(15, 23, 41, 0.8)',
                font=dict(color="#94a3b8", size=10),
                xaxis=dict(title="Strike Price", gridcolor="#1e3a5f", tickangle=-45),
                yaxis=dict(title="Open Interest", gridcolor="#1e3a5f"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=60, r=20, t=60, b=80),
            )
            st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})

    # ── Row 3: Change in OI Chart ──
    if strikes:
        st.markdown("<div style='margin-top:12px;'></div>", unsafe_allow_html=True)
        fig_chg = go.Figure()
        fig_chg.add_trace(go.Bar(
            name="Call Chg OI", x=strike_labels, y=call_chg,
            marker_color="rgba(239, 68, 68, 0.6)",
            hovertemplate="Strike: %{x}<br>Call Chg OI: %{y:+,.0f}<extra></extra>"
        ))
        fig_chg.add_trace(go.Bar(
            name="Put Chg OI", x=strike_labels, y=put_chg,
            marker_color="rgba(16, 185, 129, 0.6)",
            hovertemplate="Strike: %{x}<br>Put Chg OI: %{y:+,.0f}<extra></extra>"
        ))
        chg_vals = call_chg + put_chg
        chg_y_top = max(chg_vals) if chg_vals else 1
        chg_y_bottom = min(chg_vals) if chg_vals else 0
        chg_pad = max((chg_y_top - chg_y_bottom) * 0.05, 1)
        _add_strike_reference_line(
            fig_chg, atm_strike, chg_y_top + chg_pad, y_bottom=chg_y_bottom - chg_pad,
            line_dash="dash", line_color="#c084fc", line_width=2,
            annotation_text=f"ATM: {int(atm_strike)}", annotation_position="top",
        )
        fig_chg.update_layout(
            title=dict(text="Change in Open Interest (Fresh Writing / Unwinding)", font=dict(size=14, color="#cbd5e1")),
            barmode='group',
            height=300,
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(15, 23, 41, 0.8)',
            font=dict(color="#94a3b8", size=10),
            xaxis=dict(title="Strike Price", gridcolor="#1e3a5f", tickangle=-45),
            yaxis=dict(title="Change in OI", gridcolor="#1e3a5f"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=60, r=20, t=60, b=80),
        )
        st.plotly_chart(fig_chg, width='stretch', config={"displayModeBar": False})

    # ── Row 4: Top OI Strikes Tables ──
    tbl_col1, tbl_col2 = st.columns(2)
    with tbl_col1:
        st.markdown('<div style="font-size:0.85rem; font-weight:600; color:#ef4444; margin-bottom:6px;">🔴 Top Call OI Strikes (Resistance)</div>', unsafe_allow_html=True)
        if option_data["top_call_oi"]:
            call_df = pd.DataFrame([{
                "Strike": int(s["strike"]),
                "Call OI": f"{s['ce_oi']:,.0f}",
                "Chg OI": f"{s['ce_chg_oi']:+,.0f}",
                "IV": f"{s['ce_iv']:.1f}%",
                "LTP": f"₹{s['ce_ltp']:.2f}",
            } for s in option_data["top_call_oi"]])
            st.dataframe(call_df, hide_index=True, width="stretch")
    with tbl_col2:
        st.markdown('<div style="font-size:0.85rem; font-weight:600; color:#10b981; margin-bottom:6px;">🟢 Top Put OI Strikes (Support)</div>', unsafe_allow_html=True)
        if option_data["top_put_oi"]:
            put_df = pd.DataFrame([{
                "Strike": int(s["strike"]),
                "Put OI": f"{s['pe_oi']:,.0f}",
                "Chg OI": f"{s['pe_chg_oi']:+,.0f}",
                "IV": f"{s['pe_iv']:.1f}%",
                "LTP": f"₹{s['pe_ltp']:.2f}",
            } for s in option_data["top_put_oi"]])
            st.dataframe(put_df, hide_index=True, width="stretch")

    st.markdown(f'<div style="font-size:0.7rem; color:#334155; text-align:right; margin-top:6px;">NSE Data Timestamp: {option_data.get("timestamp", "N/A")} · Expiry: {option_data.get("current_expiry", "N/A")}</div>', unsafe_allow_html=True)


# ─── Shared data load ───────────────────────────────────────────────────────

def _clear_news_scanner_caches() -> None:
    fetch_all_market_data.clear()
    fetch_oilprice_energy_quotes.clear()
    fetch_gift_nifty_5paisa.clear()
    fetch_5paisa_global_indices.clear()
    fetch_nse_option_chain.clear()
    fetch_nse_fii_dii.clear()
    fetch_nse_market_breadth.clear()
    fetch_nse_index_stock_movers.clear()
    fetch_index_monthly_stock_movers.clear()
    fetch_nse_turnover_delivery.clear()
    fetch_nse_delivery_turnover_history.clear()
    compute_sector_rotation.clear()
    compute_sector_rotation_intraday.clear()
    fetch_index_sr_levels.clear()
    clear_index_ohlcv_cache()
    try:
        from app.market_pulse.week52_high_low import clear_week52_caches
        clear_week52_caches()
    except ImportError:
        pass
    fetch_news.clear()
    fetch_global_news.clear()
    fetch_analyst_calls.clear()


def _load_news_scanner_payload(
    clear_caches: bool = False,
    *,
    include_index_sr: bool = True,
    include_news: bool = True,
) -> dict:
    """Fetch News Scanner datasets (cached unless clear_caches=True)."""
    if clear_caches:
        _clear_news_scanner_caches()

    with nullcontext():
        market_data = fetch_all_market_data()
        if include_news:
            news_articles = fetch_news()
            global_news_articles = fetch_global_news()
            analyst_calls = fetch_analyst_calls()
            india_events, global_events = get_upcoming_events()
        else:
            news_articles = []
            global_news_articles = []
            analyst_calls = []
            india_events, global_events = [], []

    groww_tok = get_active_groww_token()
    with st.spinner("Fetching NSE market flows (Options · FII/DII · Turnover · Delivery)..."):
        option_data = fetch_nse_option_chain("NIFTY", groww_token=groww_tok)
        fii_dii_data = fetch_nse_fii_dii()
        breadth_data = fetch_nse_market_breadth()
        turnover_delivery_data = fetch_nse_turnover_delivery()

    sentiment = analyze_options_sentiment(option_data)
    market_sentiment = analyze_today_market_sentiment(
        market_data, option_data,
        fii_dii_data=fii_dii_data,
        breadth_data=breadth_data,
        turnover_delivery_data=turnover_delivery_data,
    )
    tomorrow_outlook = analyze_tomorrow_market_outlook(
        market_data, option_data,
        fii_dii_data=fii_dii_data,
        breadth_data=breadth_data,
        turnover_delivery_data=turnover_delivery_data,
    )

    index_sr_map: dict = {}
    if include_index_sr:
        with st.spinner("Computing index support / resistance (S1 · S2 · R1 · R2)..."):
            index_sr_map = fetch_index_sr_levels(_NEWS_SCANNER_SR_INDEX_NAMES)

    return {
        "market_data": market_data,
        "index_sr_map": index_sr_map,
        "news_articles": news_articles,
        "global_news_articles": global_news_articles,
        "analyst_calls": analyst_calls,
        "india_events": india_events,
        "global_events": global_events,
        "option_data": option_data,
        "fii_dii_data": fii_dii_data,
        "breadth_data": breadth_data,
        "turnover_delivery_data": turnover_delivery_data,
        "sentiment": sentiment,
        "market_sentiment": market_sentiment,
        "tomorrow_outlook": tomorrow_outlook,
    }


_NS_HEADER_HTML = """
    <div class="main-header-ns">
        <h1 style="font-size: 2rem; font-weight: 700; color: #e2e8f0; margin: 0;">🌐 Market Intelligence Command Center</h1>
        <div style="color: #64748b; font-size: 0.9rem; margin-top: 6px;">Live global markets · Nifty Options Chain · AI-powered analysis · News & Events</div>
    </div>
    """


def _render_news_scanner_styles() -> None:
    st.markdown("""
    <style>
    .main-header-ns {
        background: linear-gradient(135deg, #0f1729 0%, #1a2744 50%, #0f1729 100%);
        border: 1px solid #1e3a5f;
        border-radius: 16px;
        padding: 28px 36px;
        margin-bottom: 24px;
        position: relative;
        overflow: hidden;
    }
    .main-header-ns::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 2px;
        background: linear-gradient(90deg, #00d4ff, #0088ff, #00ffaa, #00d4ff);
        background-size: 200% 100%;
        animation: shimmer 3s linear infinite;
    }
    @keyframes shimmer {
        0% { background-position: 200% 0; }
        100% { background-position: -200% 0; }
    }
    .section-header-ns {
        font-size: 1.1rem;
        font-weight: 600;
        color: #cbd5e1;
        padding: 12px 0 10px 0;
        border-bottom: 1px solid #1e3a5f;
        margin-bottom: 16px;
    }
    .news-card-ns {
        background: #0f1729;
        border: 1px solid #1e3a5f;
        border-left: 3px solid #2563eb;
        border-radius: 10px;
        padding: 14px 18px;
        margin-bottom: 10px;
    }
    .event-card-ns {
        background: #0f1729;
        border: 1px solid #1e3a5f;
        border-radius: 10px;
        padding: 14px 18px;
        margin-bottom: 10px;
    }
    .ai-summary-box-ns {
        background: linear-gradient(135deg, #0f1729 0%, #0d1f3c 100%);
        border: 1px solid #1e3a5f;
        border-top: 2px solid #2563eb;
        border-radius: 12px;
        padding: 24px 28px;
        font-size: 0.9rem;
        line-height: 1.75;
        color: #cbd5e1;
    }
    </style>
    """, unsafe_allow_html=True)


def render_command_center_outlook():
    """Tomorrow + today outlook banners for Command Center hub."""
    _render_news_scanner_styles()
    ist = pytz.timezone('Asia/Kolkata')
    now_ist = datetime.now(ist)

    col_refresh, _ = st.columns([3, 1])
    with col_refresh:
        run_fetch = st.button("🔄 Refresh Outlook Data", key="cc_outlook_refresh_btn")

    if run_fetch:
        payload = _load_news_scanner_payload(
            clear_caches=True,
            include_index_sr=False,
            include_news=False,
        )
        st.session_state["cc_outlook_payload"] = payload

    payload = st.session_state.get("cc_outlook_payload")

    if not payload:
        st.info(
            "Click **🔄 Refresh Outlook Data** above to load tomorrow & today market outlook. "
            "Data is not fetched automatically on page load."
        )
        st.caption(
            f"IST: {now_ist.strftime('%d %b %Y %H:%M:%S')} · "
            "Open **Market Pulse → News Scanner** for full intelligence, options, and news."
        )
        return

    _render_tomorrow_outlook_banner(payload["tomorrow_outlook"], now_ist)
    _render_today_sentiment_banner(payload["market_sentiment"], now_ist)
    st.caption(
        f"IST: {now_ist.strftime('%d %b %Y %H:%M:%S')} · "
        "Open **Market Pulse → News Scanner** for full intelligence, options, and news."
    )
    from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
    snapshot_section_for_ask_ai("command_outlook")


# ─── Main Render Function ───────────────────────────────────────────────────

def render_news_scanner_tab(show_outlook_banners: bool = True):
    _render_news_scanner_styles()

    ist = pytz.timezone('Asia/Kolkata')
    now_ist = datetime.now(ist)

    st.markdown(_NS_HEADER_HTML, unsafe_allow_html=True)

    provider, model, api_key = render_ai_provider_compact(key_prefix="news_scanner")

    with st.expander("⚙️ Display Settings", expanded=False):
        show_charts = st.checkbox("Show Mini Charts", value=True, key="ns_show_charts")
        news_count = st.slider("News Articles to Show", 5, 60, 24, key="ns_news_count")
        analyst_count = st.slider("Analyst Calls to Show", 5, 30, 15, key="ns_analyst_count")
        auto_refresh = st.checkbox("Auto-refresh (1 min)", value=False, key="ns_auto_refresh")

    col_refresh, col_ai = st.columns([3, 1])
    with col_refresh:
        run_fetch = st.button("🔄 Refresh Market Data", key="ns_refresh_btn")
    with col_ai:
        run_ai_only = st.button("🤖 Regenerate AI Summary", key="ns_ai_btn")

    if run_fetch:
        payload = _load_news_scanner_payload(clear_caches=True)
        st.session_state["ns_scanner_payload"] = payload
        st.session_state.pop("ns_ai_summary_html", None)

    payload = st.session_state.get("ns_scanner_payload")

    if not payload:
        st.info(
            "Click **🔄 Refresh Market Data** to load live markets, "
            "NSE flows, options, news, and events. Data is not fetched automatically on page load."
        )
        st.markdown('<div class="section-header-ns" style="margin-top:20px;">🤖 AI Market Intelligence Summary</div>', unsafe_allow_html=True)
        ai_placeholder = st.empty()
        if run_ai_only:
            ai_placeholder.warning("Load market data first using **🔄 Refresh Market Data**.")
        elif not api_key:
            ai_placeholder.markdown("""
            <div class="ai-summary-box-ns">
                <div style="display: inline-block; background: #1e3a5f; color: #60a5fa; font-size: 0.7rem; font-weight: 600; padding: 3px 10px; border-radius: 20px; margin-bottom: 14px; letter-spacing: 0.05em;">⚙️ SETUP REQUIRED</div>
                <div style="color:#64748b; font-size:0.88rem;">
                Set <code>GEMINI_API_KEY</code> or <code>GROQ_API_KEY</code> in your <code>.env</code> file, then click <strong style="color:#cbd5e1;">🤖 Regenerate AI Summary</strong> after loading market data.
                </div>
            </div>""", unsafe_allow_html=True)
        else:
            ai_placeholder.markdown("""
            <div class="ai-summary-box-ns">
                <div style="display: inline-block; background: #1e3a5f; color: #60a5fa; font-size: 0.7rem; font-weight: 600; padding: 3px 10px; border-radius: 20px; margin-bottom: 14px; letter-spacing: 0.05em;">✅ READY</div>
                <div style="color:#64748b; font-size:0.88rem;">
                API key detected. Click <strong style="color:#cbd5e1;">🔄 Refresh Market Data</strong>, then <strong style="color:#cbd5e1;">🤖 Regenerate AI Summary</strong>.
                </div>
            </div>""", unsafe_allow_html=True)
        st.markdown(f"""
        <div style="margin-top:40px; padding: 20px 0; border-top: 1px solid #1e3a5f; text-align:center;">
            <div style="font-size:0.75rem; color:#334155;">
                🕐 IST: {now_ist.strftime('%d %b %Y %H:%M:%S')}<br>
                Market Data: Yahoo + 5paisa · Options: NSE v3 / Groww · Flows: NSE FII/DII + Bhavcopy Delivery · News: Moneycontrol RSS + Analyst Recos
            </div>
        </div>
        """, unsafe_allow_html=True)
        return

    market_data = payload["market_data"]
    news_articles = payload["news_articles"]
    global_news_articles = payload["global_news_articles"]
    analyst_calls = payload.get("analyst_calls") or []
    india_events = payload["india_events"]
    global_events = payload["global_events"]
    option_data = payload["option_data"]
    fii_dii_data = payload["fii_dii_data"]
    breadth_data = payload["breadth_data"]
    turnover_delivery_data = payload["turnover_delivery_data"]
    sentiment = payload["sentiment"]
    market_sentiment = payload["market_sentiment"]
    tomorrow_outlook = payload["tomorrow_outlook"]
    index_sr_map = payload.get("index_sr_map") or {}

    if show_outlook_banners:
        _render_tomorrow_outlook_banner(tomorrow_outlook, now_ist)
        _render_today_sentiment_banner(market_sentiment, now_ist)

    # ═══════════════════════════════════════════════════════════════════════
    # Section 1: Indian Markets
    # ═══════════════════════════════════════════════════════════════════════
    st.markdown('<div class="section-header-ns">🇮🇳 Indian Markets</div>', unsafe_allow_html=True)
    st.caption(
        "Each card: **last price** · **% change** · **S1/S2** support · **R1/R2** resistance (6M daily swings)."
    )
    ind_cols = st.columns(6)
    india_tickers = ["Nifty 50", "Sensex", "Bank Nifty", "India VIX", "Nifty IT", "Nifty Midcap 150"]
    for i, name in enumerate(india_tickers):
        d = market_data.get(name, {})
        with ind_cols[i]:
            st.markdown(
                render_metric_card(
                    name, d.get("price"), d.get("pct"),
                    decimals=2, sr=index_sr_map.get(name),
                ),
                unsafe_allow_html=True,
            )

    # ═══════════════════════════════════════════════════════════════════════
    # Section 2: Gift Nifty
    # ═══════════════════════════════════════════════════════════════════════
    st.markdown('<div class="section-header-ns" style="margin-top:20px;">🎁 Gift Nifty</div>', unsafe_allow_html=True)
    gift_d = market_data.get("Gift Nifty", {})
    nifty_d = market_data.get("Nifty 50", {})
    gift_cols = st.columns([1, 1, 2])
    with gift_cols[0]:
        st.markdown(
            render_metric_card(
                "Gift Nifty (Live)", gift_d.get("price"), gift_d.get("pct"),
                decimals=2, sr=index_sr_map.get("Gift Nifty"),
            ),
            unsafe_allow_html=True,
        )
        if gift_d.get("as_of"):
            st.caption(f"As of {gift_d['as_of']} · Source: 5paisa.com")
    with gift_cols[1]:
        nifty_price = nifty_d.get('price')
        gift_price = gift_d.get('price')
        if nifty_price and gift_price and nifty_price > 0:
            premium = gift_price - nifty_price
            premium_pct = (premium / nifty_price) * 100
            prem_color = "#10b981" if premium >= 0 else "#ef4444"
            prem_label = "Premium" if premium >= 0 else "Discount"
            st.markdown(f"""
            <div style="background: #0f1729; border: 1px solid #1e3a5f; border-radius: 12px; padding: 16px 20px;">
                <div style="font-size: 0.72rem; color: #64748b; text-transform: uppercase; font-weight: 500; margin-bottom: 8px;">{prem_label} vs Nifty Spot</div>
                <div style="display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:8px;">
                    <div style="font-size: 1.35rem; font-weight: 700; color: {prem_color}; line-height: 1.1;">{premium:+,.2f} pts</div>
                    <div style="font-size: 0.88rem; font-weight: 600; color: {prem_color}; white-space: nowrap;">{premium_pct:+.3f}%</div>
                </div>
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown(render_metric_card("Premium/Discount", None, None), unsafe_allow_html=True)
    with gift_cols[2]:
        day_low = gift_d.get("day_low")
        day_high = gift_d.get("day_high")
        open_px = gift_d.get("open")
        prev_close = gift_d.get("prev_close")
        detail_lines = []
        if open_px is not None:
            detail_lines.append(f"Open: {open_px:,.2f}")
        if prev_close is not None:
            detail_lines.append(f"Prev Close: {prev_close:,.2f}")
        if day_low is not None and day_high is not None:
            detail_lines.append(f"Day Range: {day_low:,.2f} – {day_high:,.2f}")
        details_html = " · ".join(detail_lines) if detail_lines else "Extended-hours NSE IX futures contract"
        st.markdown(f"""
        <div style="background: #0f1729; border: 1px solid #1e3a5f; border-left: 3px solid #10b981; border-radius: 12px; padding: 16px 20px; font-size: 0.8rem; color: #94a3b8; line-height: 1.6;">
            <strong style="color: #10b981;">Live from 5paisa:</strong> Gift Nifty trades on NSE IX with extended hours and often leads Indian cash-market sentiment.<br>
            <span style="color: #cbd5e1;">{details_html}</span><br>
            <a href="https://www.5paisa.com/share-market-today/gift-nifty" target="_blank" style="color: #60a5fa;">View on 5paisa.com</a>
        </div>""", unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════════════════
    # Section 3: US Markets (Live)
    # ═══════════════════════════════════════════════════════════════════════
    _render_market_section(
        "🇺🇸 US Markets (Live)",
        ["Dow Jones", "S&P 500", "Nasdaq Composite", "Russell 2000"],
        market_data,
        cols_count=4,
        sr_map=index_sr_map,
    )

    # ═══════════════════════════════════════════════════════════════════════
    # Section 4: Asia Markets
    # ═══════════════════════════════════════════════════════════════════════
    st.markdown('<div class="section-header-ns" style="margin-top:20px;">🌏 Asia Markets</div>', unsafe_allow_html=True)
    asia_tickers = ["Nikkei 225 (Japan)", "Hang Seng (HK)", "Shanghai (China)", "KOSPI (Korea)", "Straits Times (SG)", "ASX 200 (Australia)", "Taiwan Weighted"]
    asia_cols = st.columns(4)
    for i, name in enumerate(asia_tickers):
        d = market_data.get(name, {})
        with asia_cols[i % 4]:
            st.markdown(
                render_metric_card(
                    name, d.get("price"), d.get("pct"),
                    decimals=2, sr=index_sr_map.get(name),
                ),
                unsafe_allow_html=True,
            )
            if (i + 1) % 4 == 0 and i < len(asia_tickers) - 1:
                st.markdown("<div style='margin-bottom: 10px;'></div>", unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════════════════
    # Section 5: Europe Markets
    # ═══════════════════════════════════════════════════════════════════════
    _render_market_section(
        "🇪🇺 Europe Markets",
        ["FTSE 100 (UK)", "DAX 40 (Germany)", "CAC 40 (France)"],
        market_data,
        cols_count=3,
        sr_map=index_sr_map,
    )

    # ═══════════════════════════════════════════════════════════════════════
    # Section 6: Global Futures
    # ═══════════════════════════════════════════════════════════════════════
    _render_market_section(
        "📡 Global Futures",
        ["Dow Futures", "S&P 500 Futures", "Nasdaq Futures"],
        market_data,
        cols_count=3,
        sr_map=index_sr_map,
    )

    # ═══════════════════════════════════════════════════════════════════════
    # Section 7: Forex & Dollar
    # ═══════════════════════════════════════════════════════════════════════
    _render_market_section(
        "💱 Forex & Dollar",
        ["DXY (Dollar Index)", "USD/INR", "EUR/INR", "Crude Oil (WTI)"],
        market_data,
        cols_count=4,
        prefix_map={"USD/INR": "₹", "EUR/INR": "₹", "Crude Oil (WTI)": "$"},
        decimals_map={"DXY (Dollar Index)": 3, "USD/INR": 2, "EUR/INR": 2, "Crude Oil (WTI)": 2}
    )

    # ═══════════════════════════════════════════════════════════════════════
    # Section 8: Commodities, Crypto & Bond Yields
    # ═══════════════════════════════════════════════════════════════════════
    st.markdown('<div class="section-header-ns" style="margin-top:20px;">🥇 Commodities, Crypto & Bond Yields</div>', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:0.78rem;font-weight:600;color:#94a3b8;margin:8px 0 6px;">'
        "🛢️ Energy — "
        '<a href="https://oilprice.com/oil-price-charts/" target="_blank" rel="noopener" '
        'style="color:#60a5fa;text-decoration:none;">Oilprice.com</a></div>',
        unsafe_allow_html=True,
    )
    energy_cols = st.columns(3)
    for i, name in enumerate(_OILPRICE_ENERGY_SYMBOLS):
        d = market_data.get(name, {})
        dec = 3 if name == "Natural Gas" else 2
        with energy_cols[i]:
            st.markdown(
                render_energy_metric_card(
                    name,
                    d.get("price"),
                    d.get("change_pts"),
                    d.get("pct"),
                    decimals=dec,
                ),
                unsafe_allow_html=True,
            )
    st.caption("WTI · Brent · Natural Gas — delayed quotes per Oilprice.com futures table.")

    commodities = [
        ("Gold", "Gold", "$", "", 2),
        ("Silver", "Silver", "$", "", 2),
        ("US 10Y Bond Yield", "US 10Y Yield", "", "%", 3),
        ("US 2Y Bond Yield", "US 2Y Yield", "", "%", 3),
        ("Bitcoin", "Bitcoin", "$", "", 0),
        ("Ethereum", "Ethereum", "$", "", 2),
        ("Solana", "Solana", "$", "", 2),
    ]
    com_cols = st.columns(4)
    for i, (key, label, pfx, sfx, dec) in enumerate(commodities):
        d = market_data.get(key, {})
        with com_cols[i % 4]:
            st.markdown(render_metric_card(label, d.get('price'), d.get('pct'), prefix=pfx, suffix=sfx, decimals=dec), unsafe_allow_html=True)
            if (i + 1) % 4 == 0 and i < len(commodities) - 1:
                st.markdown("<div style='margin-bottom: 10px;'></div>", unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════════════════
    # Section 9: Cash Market Flows (FII/DII, Breadth, Turnover, Delivery)
    # ═══════════════════════════════════════════════════════════════════════
    _render_market_flows_section(fii_dii_data, breadth_data, turnover_delivery_data)

    # ═══════════════════════════════════════════════════════════════════════
    # Section 10: Nifty Options Chain Analysis
    # ═══════════════════════════════════════════════════════════════════════
    _render_options_section(option_data, sentiment)

    # ═══════════════════════════════════════════════════════════════════════
    # Section 10: Mini Charts
    # ═══════════════════════════════════════════════════════════════════════
    if show_charts:
        st.markdown('<div class="section-header-ns" style="margin-top:20px;">📉 Price Charts (90 Days)</div>', unsafe_allow_html=True)
        chart_items = ["Nifty 50", "Dow Jones", "Nikkei 225 (Japan)", "DXY (Dollar Index)", "Gold", "Bitcoin"]
        chart_cols = st.columns(len(chart_items))
        for i, name in enumerate(chart_items):
            d = market_data.get(name, {})
            hist = d.get('hist')
            with chart_cols[i]:
                if hist is not None and not hist.empty:
                    fig = go.Figure()
                    color = "#10b981" if (d.get('pct') or 0) >= 0 else "#ef4444"
                    fig.add_trace(go.Scatter(
                        y=hist['Close'].values,
                        mode='lines',
                        line=dict(color=color, width=2),
                        fill='tozeroy',
                        fillcolor='rgba(16, 185, 129, 0.1)' if color == "#10b981" else 'rgba(239, 68, 68, 0.1)'
                    ))
                    fig.update_layout(
                        height=100, margin=dict(l=0, r=0, t=4, b=0),
                        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                        showlegend=False, xaxis=dict(visible=False), yaxis=dict(visible=False)
                    )
                    st.markdown(f'<div style="font-size:0.72rem;color:#64748b;text-align:center;margin-bottom:2px;">{name}</div>', unsafe_allow_html=True)
                    st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})
                else:
                    st.markdown(f'<div style="font-size:0.72rem;color:#475569;text-align:center;padding:30px 0;">{name}<br>No data</div>', unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════════════════
    # Section 11: News Feed
    # ═══════════════════════════════════════════════════════════════════════
    st.markdown('<div class="section-header-ns" style="margin-top:20px;">📰 Latest Market News</div>', unsafe_allow_html=True)
    st.caption(
        f"Fresh headlines only (last **96 hours**), sorted newest-first · "
        f"**{sum(1 for a in news_articles if 'Moneycontrol' in a.get('source', ''))}** Moneycontrol · "
        f"**{len(news_articles)}** India/crypto · **{len(global_news_articles)}** global"
    )
    india_display = news_articles[: max(1, news_count // 2)] if news_articles else []
    global_display = global_news_articles[: max(1, news_count // 2)] if global_news_articles else []
    col_india, col_global = st.columns(2)

    with col_india:
        st.markdown('<div style="font-size:0.95rem; font-weight:600; color:#cbd5e1; margin-bottom:10px;">🇮🇳 India & Crypto News</div>', unsafe_allow_html=True)
        if india_display:
            for article in india_display:
                age = article.get("age_hours")
                age_txt = f" · {age:.0f}h ago" if age is not None else ""
                st.markdown(f"""
                <div class="news-card-ns">
                    <div style="font-size: 0.88rem; font-weight: 500; color: #cbd5e1; margin-bottom: 6px;">
                        <a href="{article['link']}" target="_blank" style="color: #cbd5e1; text-decoration: none;">{article['title']}</a>
                    </div>
                    <div style="font-size: 0.72rem; color: #475569;">
                        <span style="color: #2563eb; font-weight: 600;">{article['source']}</span> &nbsp;·&nbsp;{article['published']}{age_txt}
                    </div>
                </div>""", unsafe_allow_html=True)
        else:
            st.info("No fresh India/Crypto news in the last 96 hours. Click **🔄 Refresh Market Data**.")

    with col_global:
        st.markdown('<div style="font-size:0.95rem; font-weight:600; color:#cbd5e1; margin-bottom:10px;">🇺🇸 US Markets & ⚔️ Geopolitics</div>', unsafe_allow_html=True)
        if global_display:
            for article in global_display:
                age = article.get("age_hours")
                age_txt = f" · {age:.0f}h ago" if age is not None else ""
                st.markdown(f"""
                <div class="news-card-ns">
                    <div style="font-size: 0.88rem; font-weight: 500; color: #cbd5e1; margin-bottom: 6px;">
                        <a href="{article['link']}" target="_blank" style="color: #cbd5e1; text-decoration: none;">{article['title']}</a>
                    </div>
                    <div style="font-size: 0.72rem; color: #475569;">
                        <span style="color: #2563eb; font-weight: 600;">{article['source']}</span> &nbsp;·&nbsp;{article['published']}{age_txt}
                    </div>
                </div>""", unsafe_allow_html=True)
        else:
            st.info("No fresh US/geopolitics news in the last 96 hours.")

    if not news_articles and not global_news_articles:
        st.warning("⚠️ Unable to fetch fresh news. Check internet connection or RSS availability.")

    # ═══════════════════════════════════════════════════════════════════════
    # Section 12: Analyst Calls
    # ═══════════════════════════════════════════════════════════════════════
    _render_analyst_calls_section(analyst_calls, limit=analyst_count)

    # ═══════════════════════════════════════════════════════════════════════
    # Section 13: Upcoming Events (future-only)
    # ═══════════════════════════════════════════════════════════════════════
    _render_upcoming_events_section(india_events, global_events, now_ist.date())

    # ═══════════════════════════════════════════════════════════════════════
    # Section 14: AI Market Summary
    # ═══════════════════════════════════════════════════════════════════════
    st.markdown('<div class="section-header-ns" style="margin-top:20px;">🤖 AI Market Intelligence Summary</div>', unsafe_allow_html=True)
    ai_placeholder = st.empty()

    def run_ai_summary():
        if not api_key:
            ai_placeholder.error(f"⚠️ {api_key_env_hint(provider)}")
            return
        if provider == "Custom / Other" and not model:
            ai_placeholder.error("⚠️ Please enter a model name.")
            return
        with nullcontext():
            prompt_data = build_ai_prompt(
                market_data, news_articles, global_news_articles, india_events, global_events,
                option_data, fii_dii_data, breadth_data, turnover_delivery_data,
                analyst_calls=analyst_calls,
            )
            summary = get_ai_summary(prompt_data, provider, model, api_key)
        html = f"""
        <div class="ai-summary-box-ns">
            <div style="display: inline-block; background: #1e3a5f; color: #60a5fa; font-size: 0.7rem; font-weight: 600; padding: 3px 10px; border-radius: 20px; margin-bottom: 14px; letter-spacing: 0.05em;">🤖 {provider} · {model}</div>
            <div style="white-space: pre-wrap; font-size:0.88rem; line-height:1.8;">{summary}</div>
        </div>"""
        st.session_state["ns_ai_summary_html"] = html
        ai_placeholder.markdown(html, unsafe_allow_html=True)

    if run_ai_only:
        run_ai_summary()
    elif st.session_state.get("ns_ai_summary_html"):
        ai_placeholder.markdown(st.session_state["ns_ai_summary_html"], unsafe_allow_html=True)
    elif not api_key:
        ai_placeholder.markdown("""
        <div class="ai-summary-box-ns">
            <div style="display: inline-block; background: #1e3a5f; color: #60a5fa; font-size: 0.7rem; font-weight: 600; padding: 3px 10px; border-radius: 20px; margin-bottom: 14px; letter-spacing: 0.05em;">⚙️ SETUP REQUIRED</div>
            <div style="color:#64748b; font-size:0.88rem;">
            Set <code>GEMINI_API_KEY</code> or <code>GROQ_API_KEY</code> in your <code>.env</code> file, then click <strong style="color:#cbd5e1;">🤖 Regenerate AI Summary</strong>.<br><br>
            Supported providers:<br>
            • <strong style="color:#34d399;">Google Gemini</strong> — <code>GEMINI_API_KEY</code> in <code>.env</code> (gemini-3.1-flash-lite recommended)<br>
            • <strong style="color:#60a5fa;">Groq</strong> — <code>GROQ_API_KEY</code> in <code>.env</code> (LLaMA 3.3 70B)
            </div>
        </div>""", unsafe_allow_html=True)
    else:
        ai_placeholder.markdown("""
        <div class="ai-summary-box-ns">
            <div style="display: inline-block; background: #1e3a5f; color: #60a5fa; font-size: 0.7rem; font-weight: 600; padding: 3px 10px; border-radius: 20px; margin-bottom: 14px; letter-spacing: 0.05em;">✅ READY</div>
            <div style="color:#64748b; font-size:0.88rem;">
            Market data loaded. Click <strong style="color:#cbd5e1;">Regenerate AI Summary</strong> to generate analysis.
            </div>
        </div>""", unsafe_allow_html=True)

    if payload:
        from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
        snapshot_section_for_ask_ai("news_scanner")

    st.markdown(f"""
    <div style="margin-top:40px; padding: 20px 0; border-top: 1px solid #1e3a5f; text-align:center;">
        <div style="font-size:0.75rem; color:#334155;">
            🕐 IST: {now_ist.strftime('%d %b %Y %H:%M:%S')}<br>
            Market Data: Yahoo + 5paisa · Options: NSE v3 / Groww · Flows: NSE FII/DII + Bhavcopy Delivery · News: Moneycontrol RSS + Analyst Recos<br>
            AI: Google Gemini / Groq (LLaMA) · For educational purposes only. Not financial advice.<br>
            ⚠️ Yahoo data may be delayed 15-20 min. Gift Nifty & global indices refreshed from 5paisa. Always verify before trading.
        </div>
    </div>
    """, unsafe_allow_html=True)

    if auto_refresh:
        _clear_news_scanner_caches()
        refreshed = _load_news_scanner_payload(clear_caches=True)
        st.session_state["ns_scanner_payload"] = refreshed
        time.sleep(60)
        st.rerun()
