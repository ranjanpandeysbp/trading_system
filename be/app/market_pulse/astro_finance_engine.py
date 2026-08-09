"""
astro_finance_engine.py
-----------------------
Financial Astrology desks for Prediction → Astro Finance.

Implements research/education scanners inspired by:
- Harshubh Shah · Vijay Thakkar — https://www.youtube.com/watch?v=xP-rt9tU79U
- Harshubh Shah · Vikas Gupta Show — https://www.youtube.com/watch?v=xZ84XDFInEI
- Astrologer Rahul Bhatnagar — https://www.youtube.com/watch?v=G1WYa0VgA7A

Strategies
1. lunar_cycle — Amavasya / Poornima windows + historical forward stats
2. amavasya_sr — Permanent S/R from New-Moon session highs/lows
3. bhadra_timing — Vishti/Bhadra Karana windows overlapping market hours
4. transit_gaps — Mars/Venus sign-ingress proximity vs overnight gaps
5. trading_calendar — Moon-sign favorable days + Muhurat + commodity planet map
6. mercury_retrograde — Mercury stations / Rx noise + range stats
7. nakshatra_timing — 27 lunar mansions (favorable vs volatile)
8. tithi_panchang — Tithi + weekday ruler + date vibration numerology
9. gann_numerology — Square-of-9 price magnets + day number
10. eclipse_nodes — Eclipse-season proxy near Rahu–Ketu axis

Disclaimer: astrology is a timing overlay — always double-confirm with technical analysis.
Not financial advice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv

YOUTUBE_HARSHUBH_VIJAY = "https://www.youtube.com/watch?v=xP-rt9tU79U"
YOUTUBE_HARSHUBH_VIKAS = "https://www.youtube.com/watch?v=xZ84XDFInEI"
YOUTUBE_RAHUL_BHATNAGAR = "https://www.youtube.com/watch?v=G1WYa0VgA7A"

ASTRO_FINANCE_AI_SYSTEM = (
    "You are an Astro Finance desk analyst. Use lunar cycle, Amavasya S/R, Bhadra timing, "
    "transit-gap bias, trading-calendar, Mercury retrograde, Nakshatra, Tithi/Panchang, "
    "Gann Square-of-9 numerology, and Eclipse/Rahu–Ketu node overlays only as timing / "
    "confirmation — never as a standalone reason to buy or sell. Prefer the structured "
    "layman block (what it means, how it relates to trading/investing, what action to take) "
    "when explaining outcomes. Cite dates, levels, and historical hit-rates from the payload. "
    "Research/education only — not financial advice. Harshubh Shah: time is powerful "
    "(Samay Balwan Che); always pair with technical analysis."
)

ZODIAC = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

COMMODITY_PLANET_MAP = [
    {"commodity": "Gold", "planets": "Sun / Jupiter", "symbols": ["GC=F", "GLD", "GOLDBEES"]},
    {"commodity": "Copper", "planets": "Sun", "symbols": ["HG=F", "CPER"]},
    {"commodity": "Crude Oil", "planets": "Saturn", "symbols": ["CL=F", "USO"]},
    {"commodity": "Silver", "planets": "Moon", "symbols": ["SI=F", "SLV", "SILVERBEES"]},
]

DEFAULT_TICKERS: dict[str, list[str]] = {
    "india": ["^NSEI", "RELIANCE", "TCS", "HDFCBANK"],
    "us": ["SPY", "QQQ", "AAPL", "TSLA"],
    "crypto": ["BTC-USD", "ETH-USD"],
    "commodity": ["GC=F", "SI=F", "CL=F", "HG=F"],
}

MARKET_TZ: dict[str, str] = {
    "india": "Asia/Kolkata",
    "us": "America/New_York",
    "crypto": "UTC",
    "commodity": "America/New_York",
}

MARKET_COORDS: dict[str, tuple[float, float]] = {
    # lat, lon — for sunrise / muhurat
    "india": (19.0760, 72.8777),       # Mumbai
    "us": (40.7128, -74.0060),         # New York
    "crypto": (0.0, 0.0),              # UTC solar day
    "commodity": (40.7128, -74.0060),
}

MUHURAT_NAMES = [
    "Amrit", "Shubh", "Labh", "Char",
    "Kaal", "Rog", "Udveg", "Shubh",
]
# Prefer these for execution (Rahul Bhatnagar: Char, Shubh, Amrit, Labh)
FAVORABLE_MUHURAT = {"Amrit", "Shubh", "Labh", "Char"}


GUIDE_OVERVIEW = f"""
### Astro Finance — How to use
Financial astrology is a **timing & confirmation** layer on top of technical analysis
(Harshubh Shah: master TA first; astrology doubles confidence when both agree).

| Source | Concepts |
|--------|----------|
| [Harshubh × Vijay Thakkar]({YOUTUBE_HARSHUBH_VIJAY}) | Lunar tides · Amavasya S/R · Bhadra timing · Mars/Venus gaps |
| [Harshubh × Vikas Gupta]({YOUTUBE_HARSHUBH_VIKAS}) | Time > price (Samay Balwan Che) · intraday timing vs positional direction · not a TA replacement |
| [Rahul Bhatnagar]({YOUTUBE_RAHUL_BHATNAGAR}) | 5th-house / Ashtakvarga-lite favorable Moon days · Muhurat · commodity↔planet map |

**Advanced desks (this app):** Mercury Retrograde · Nakshatra (27 mansions) · Tithi + weekday
ruler · Gann Square-of-9 + date vibration · Eclipse / Rahu–Ketu axis windows.

**Mindset:** Markets express human emotion; lunar/planetary cycles modulate emotion → volatility.
Do **not** quit your job to trade full-time — treat this as part-time until income consistently beats salary for years.
"""


# ---------------------------------------------------------------------------
# Astronomy helpers (no external ephemeris dependency)
# ---------------------------------------------------------------------------

def _julian_day(dt: datetime) -> float:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    y, m, d = dt.year, dt.month, dt.day + (dt.hour + dt.minute / 60 + dt.second / 3600) / 24
    if m <= 2:
        y -= 1
        m += 12
    A = y // 100
    B = 2 - A + A // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + B - 1524.5


def _norm360(x: float) -> float:
    return x % 360.0


def _moon_sun_elongation_deg(dt: datetime) -> float:
    """Approximate Moon−Sun elongation (deg). 0≈New, 180≈Full."""
    jd = _julian_day(dt)
    T = (jd - 2451545.0) / 36525.0
    # Mean longitudes (deg) — Meeus-lite
    L_sun = _norm360(280.46646 + 36000.76983 * T + 0.0003032 * T * T)
    M_sun = math.radians(_norm360(357.52911 + 35999.05029 * T))
    C = (1.914602 - 0.004817 * T) * math.sin(M_sun) + 0.019993 * math.sin(2 * M_sun)
    sun = _norm360(L_sun + C)

    Lp = _norm360(218.3164477 + 481267.88123421 * T)
    D = math.radians(_norm360(297.8501921 + 445267.1114034 * T))
    M = math.radians(_norm360(357.5291092 + 35999.0502909 * T))
    Mp = math.radians(_norm360(134.9633964 + 477198.8675055 * T))
    F = math.radians(_norm360(93.2720950 + 483202.0175233 * T))
    # Main lunar longitude terms
    lon = (
        Lp
        + 6.289 * math.sin(Mp)
        + 1.274 * math.sin(2 * D - Mp)
        + 0.658 * math.sin(2 * D)
        + 0.214 * math.sin(2 * Mp)
        - 0.186 * math.sin(M)
        - 0.114 * math.sin(2 * F)
    )
    moon = _norm360(lon)
    return _norm360(moon - sun)


def moon_phase_name(elong: float) -> str:
    if elong < 20 or elong >= 340:
        return "Amavasya (New Moon)"
    if 160 <= elong <= 200:
        return "Poornima (Full Moon)"
    if 20 <= elong < 90:
        return "Waxing Crescent → First Quarter"
    if 90 <= elong < 160:
        return "Waxing Gibbous"
    if 200 < elong < 270:
        return "Waning Gibbous → Last Quarter"
    return "Waning Crescent"


def moon_illumination(elong: float) -> float:
    return round((1 - math.cos(math.radians(elong))) / 2 * 100, 1)


def moon_zodiac_sign(dt: datetime) -> str:
    """Sidereal-ish tropical moon sign from approximate ecliptic longitude."""
    jd = _julian_day(dt)
    T = (jd - 2451545.0) / 36525.0
    Lp = _norm360(218.3164477 + 481267.88123421 * T)
    D = math.radians(_norm360(297.8501921 + 445267.1114034 * T))
    Mp = math.radians(_norm360(134.9633964 + 477198.8675055 * T))
    F = math.radians(_norm360(93.2720950 + 483202.0175233 * T))
    M = math.radians(_norm360(357.5291092 + 35999.0502909 * T))
    lon = _norm360(
        Lp
        + 6.289 * math.sin(Mp)
        + 1.274 * math.sin(2 * D - Mp)
        + 0.658 * math.sin(2 * D)
        + 0.214 * math.sin(2 * Mp)
        - 0.186 * math.sin(M)
        - 0.114 * math.sin(2 * F)
    )
    # Lahiri ayanamsa ~24° — convert tropical → approx sidereal for Vedic feel
    sidereal = _norm360(lon - 24.0)
    return ZODIAC[int(sidereal // 30) % 12]


def find_lunar_events(start: date, end: date) -> list[dict[str, Any]]:
    """Scan daily for New/Full moon crossings."""
    events: list[dict[str, Any]] = []
    d = start
    prev_e = _moon_sun_elongation_deg(datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc))
    d += timedelta(days=1)
    while d <= end:
        e = _moon_sun_elongation_deg(datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc))
        # New moon: elongation wraps near 0
        if prev_e > 300 and e < 60:
            events.append({"date": d.isoformat(), "type": "Amavasya", "elongation_deg": round(e, 1)})
        # Full moon: crosses 180
        if prev_e < 180 <= e or (prev_e > 170 and e < 20 and prev_e < 200):
            if abs(e - 180) < 40 or (prev_e < 180 <= e):
                events.append({"date": d.isoformat(), "type": "Poornima", "elongation_deg": round(e, 1)})
        # cleaner full detection
        if prev_e < 180 <= e:
            # replace duplicate if same day already
            if not events or events[-1]["date"] != d.isoformat() or events[-1]["type"] != "Poornima":
                if events and events[-1]["date"] == d.isoformat() and events[-1]["type"] == "Poornima":
                    pass
                elif not (events and events[-1]["date"] == d.isoformat()):
                    events.append({"date": d.isoformat(), "type": "Poornima", "elongation_deg": round(e, 1)})
        prev_e = e
        d += timedelta(days=1)
    # Deduplicate by date+type
    seen = set()
    out = []
    for ev in events:
        key = (ev["date"], ev["type"])
        if key in seen:
            continue
        seen.add(key)
        out.append(ev)
    return out


def _planet_longitude(name: str, dt: datetime) -> float:
    """Very rough mean ecliptic longitude for Mars/Venus/Mercury/Jupiter/Saturn."""
    jd = _julian_day(dt)
    T = (jd - 2451545.0) / 36525.0
    if name == "mars":
        return _norm360(355.433 + 19140.3023 * T)
    if name == "venus":
        return _norm360(181.9798 + 58517.8156 * T)
    if name == "mercury":
        return _norm360(252.2509 + 149472.6746 * T)
    if name == "jupiter":
        return _norm360(34.3515 + 3034.9057 * T)
    if name == "saturn":
        return _norm360(50.0774 + 1222.1138 * T)
    if name == "sun":
        L = _norm360(280.46646 + 36000.76983 * T + 0.0003032 * T * T)
        M = math.radians(_norm360(357.52911 + 35999.05029 * T))
        C = (1.914602 - 0.004817 * T) * math.sin(M) + 0.019993 * math.sin(2 * M)
        return _norm360(L + C)
    return 0.0


def _mercury_geo_longitude(dt: datetime) -> float:
    """Approx geocentric Mercury longitude (vector Earth–Mercury) for Rx detection."""
    jd = _julian_day(dt)
    T = (jd - 2451545.0) / 36525.0
    # Mercury heliocentric mean anomaly + equation of center (rough)
    M_m = math.radians(_norm360(174.7948 + 149472.5154296 * T))
    L_m = _norm360(
        252.2509055 + 149472.6746358 * T
        + (23.4400 + 0.0026 * T) * math.sin(M_m)
        + 2.9818 * math.sin(2 * M_m)
    )
    r_m = 0.387098 + 0.078 * math.cos(M_m)  # AU, ecc-lite
    # Earth heliocentric ≈ opposite geocentric Sun
    L_sun = _planet_longitude("sun", dt)
    L_e = _norm360(L_sun + 180.0)
    r_e = 1.0
    xm = r_m * math.cos(math.radians(L_m))
    ym = r_m * math.sin(math.radians(L_m))
    xe = r_e * math.cos(math.radians(L_e))
    ye = r_e * math.sin(math.radians(L_e))
    return _norm360(math.degrees(math.atan2(ym - ye, xm - xe)))


def _moon_ecliptic_longitude(dt: datetime, *, sidereal: bool = True) -> float:
    jd = _julian_day(dt)
    T = (jd - 2451545.0) / 36525.0
    Lp = _norm360(218.3164477 + 481267.88123421 * T)
    D = math.radians(_norm360(297.8501921 + 445267.1114034 * T))
    Mp = math.radians(_norm360(134.9633964 + 477198.8675055 * T))
    F = math.radians(_norm360(93.2720950 + 483202.0175233 * T))
    M = math.radians(_norm360(357.5291092 + 35999.0502909 * T))
    lon = _norm360(
        Lp
        + 6.289 * math.sin(Mp)
        + 1.274 * math.sin(2 * D - Mp)
        + 0.658 * math.sin(2 * D)
        + 0.214 * math.sin(2 * Mp)
        - 0.186 * math.sin(M)
        - 0.114 * math.sin(2 * F)
    )
    if sidereal:
        lon = _norm360(lon - 24.0)  # Lahiri-ish
    return lon


def _mean_lunar_node_longitude(dt: datetime, *, sidereal: bool = True) -> float:
    """Mean ascending node (Rahu) longitude — approximate."""
    jd = _julian_day(dt)
    T = (jd - 2451545.0) / 36525.0
    # Meeus mean longitude of ascending node
    lon = _norm360(125.0445479 - 1934.136261 * T + 0.0020708 * T * T)
    if sidereal:
        lon = _norm360(lon - 24.0)
    return lon


def find_mercury_stations(start: date, end: date) -> list[dict[str, Any]]:
    """Detect Mercury retrograde station days (geo lon turns)."""
    events: list[dict[str, Any]] = []
    d = start
    prev = _mercury_geo_longitude(datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc))
    prev_delta = 0.0
    d += timedelta(days=1)
    while d <= end:
        lon = _mercury_geo_longitude(datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc))
        # unwrap delta near 0/360
        raw = lon - prev
        if raw > 180:
            raw -= 360
        if raw < -180:
            raw += 360
        if prev_delta > 0 and raw < 0:
            events.append({
                "date": d.isoformat(),
                "type": "Station Retrograde",
                "longitude_deg": round(lon, 1),
            })
        elif prev_delta < 0 and raw > 0:
            events.append({
                "date": d.isoformat(),
                "type": "Station Direct",
                "longitude_deg": round(lon, 1),
            })
        prev_delta = raw
        prev = lon
        d += timedelta(days=1)
    return events


def mercury_is_retrograde(dt: datetime) -> bool:
    a = _mercury_geo_longitude(dt - timedelta(days=1))
    b = _mercury_geo_longitude(dt)
    raw = b - a
    if raw > 180:
        raw -= 360
    if raw < -180:
        raw += 360
    return raw < 0


NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra", "Punarvasu",
    "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni", "Hasta",
    "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha", "Mula", "Purva Ashadha",
    "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha", "Purva Bhadrapada",
    "Uttara Bhadrapada", "Revati",
]

# Traditional market lore (simplified): favorable vs volatile Moon mansions
NAKSHATRA_FAVORABLE = {
    "Rohini", "Mrigashira", "Punarvasu", "Pushya", "Hasta", "Uttara Phalguni",
    "Anuradha", "Uttara Ashadha", "Shravana", "Uttara Bhadrapada", "Revati",
}
NAKSHATRA_VOLATILE = {
    "Ardra", "Ashlesha", "Magha", "Jyeshtha", "Mula", "Purva Ashadha",
    "Purva Bhadrapada", "Bharani", "Krittika",
}

TITHI_NAMES = [
    "Pratipada", "Dwitiya", "Tritiya", "Chaturthi", "Panchami", "Shashthi", "Saptami",
    "Ashtami", "Navami", "Dashami", "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi",
    "Purnima/Amavasya",
]

WEEKDAY_PLANET = {
    0: ("Monday", "Moon"),
    1: ("Tuesday", "Mars"),
    2: ("Wednesday", "Mercury"),
    3: ("Thursday", "Jupiter"),
    4: ("Friday", "Venus"),
    5: ("Saturday", "Saturn"),
    6: ("Sunday", "Sun"),
}

# Tithis often treated as calmer for fresh risk (Dashami–Dwadashi); avoid Amavasya/Chaturdashi for new entries
TITHI_FAVORABLE = {9, 10, 11}  # Dashami, Ekadashi, Dwadashi (0-based within paksha half)
TITHI_CAUTION = {13, 14}  # Chaturdashi, Purnima/Amavasya slot


def nakshatra_at(dt: datetime) -> dict[str, Any]:
    lon = _moon_ecliptic_longitude(dt, sidereal=True)
    span = 360.0 / 27.0
    idx = int(lon // span) % 27
    name = NAKSHATRAS[idx]
    return {
        "nakshatra": name,
        "index": idx + 1,
        "longitude_deg": round(lon, 2),
        "pada": int((lon % span) // (span / 4)) + 1,
        "tone": (
            "favorable" if name in NAKSHATRA_FAVORABLE
            else ("volatile" if name in NAKSHATRA_VOLATILE else "neutral")
        ),
    }


def tithi_detail(dt: datetime) -> dict[str, Any]:
    elong = _moon_sun_elongation_deg(dt)
    idx = int(elong // 12) % 30
    paksha = "Shukla (Waxing)" if idx < 15 else "Krishna (Waning)"
    within = idx % 15
    name = TITHI_NAMES[within]
    if idx == 14:
        name = "Poornima"
    elif idx == 29:
        name = "Amavasya"
    tone = "favorable" if within in TITHI_FAVORABLE else ("caution" if within in TITHI_CAUTION else "neutral")
    return {
        "tithi_index": idx + 1,
        "tithi_name": name,
        "paksha": paksha,
        "elongation_deg": round(elong, 1),
        "tone": tone,
    }


def digital_root(n: int) -> int:
    n = abs(int(n))
    while n > 9:
        n = sum(int(c) for c in str(n))
    return n


def date_vibration(d: date) -> dict[str, Any]:
    """Pythagorean-style date number used in market numerology overlays."""
    raw = d.year * 10000 + d.month * 100 + d.day
    digits = [int(c) for c in f"{d.year:04d}{d.month:02d}{d.day:02d}"]
    total = sum(digits)
    root = digital_root(total)
    return {
        "date": d.isoformat(),
        "digit_sum": total,
        "vibration": root,
        "compound": total if total > 9 else root,
        "note": {
            1: "Initiation / breakouts",
            2: "Patience / pairs & hedges",
            3: "Expansion / communication names",
            4: "Structure / accumulate",
            5: "Change / volatile tape",
            6: "Balance / mean-reversion",
            7: "Analysis / wait for clarity",
            8: "Power / large-cap leadership",
            9: "Completion / book profits",
        }.get(root, ""),
    }


def gann_square9_levels(price: float, rings: int = 3) -> list[dict[str, Any]]:
    """Cardinal / ordinal Gann Square-of-9 style levels around LTP."""
    if price <= 0:
        return []
    root = math.sqrt(price)
    levels: list[dict[str, Any]] = []
    for i in range(1, rings + 1):
        for label, step in (
            ("up_cardinal", i),
            ("down_cardinal", -i),
            ("up_45", i * 0.5),
            ("down_45", -i * 0.5),
        ):
            lvl = round((root + step) ** 2, 4)
            if lvl <= 0:
                continue
            levels.append({
                "label": label,
                "ring": i,
                "price": lvl,
                "distance_pct": round((lvl / price - 1) * 100, 3),
            })
    levels.sort(key=lambda x: abs(x["distance_pct"]))
    return levels[:12]


def find_eclipse_proxies(start: date, end: date, *, orb_deg: float = 18.0) -> list[dict[str, Any]]:
    """New/Full Moon near lunar node ≈ eclipse season proxy (educational approx)."""
    events: list[dict[str, Any]] = []
    for ev in find_lunar_events(start, end):
        d = date.fromisoformat(ev["date"])
        noon = datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc)
        moon = _moon_ecliptic_longitude(noon, sidereal=True)
        node = _mean_lunar_node_longitude(noon, sidereal=True)
        # distance to Rahu or Ketu (node+180)
        d1 = abs(((moon - node + 180) % 360) - 180)
        d2 = abs(((moon - _norm360(node + 180) + 180) % 360) - 180)
        dist = min(d1, d2)
        if dist <= orb_deg:
            kind = "Solar eclipse proxy" if ev["type"] == "Amavasya" else "Lunar eclipse proxy"
            events.append({
                "date": ev["date"],
                "type": kind,
                "lunar_event": ev["type"],
                "node_orb_deg": round(dist, 1),
                "rahu_lon": round(node, 1),
            })
    return events


def find_sign_ingresses(planet: str, start: date, end: date) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    d = start
    prev = _planet_longitude(planet, datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc))
    prev_sign = int(prev // 30)
    d += timedelta(days=1)
    while d <= end:
        lon = _planet_longitude(planet, datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc))
        sign = int(lon // 30)
        if sign != prev_sign:
            events.append({
                "date": d.isoformat(),
                "planet": planet.title(),
                "from_sign": ZODIAC[prev_sign % 12],
                "to_sign": ZODIAC[sign % 12],
                "longitude_deg": round(lon, 1),
            })
        prev_sign = sign
        d += timedelta(days=1)
    return events


def _solar_noon_offset_hours(lon: float) -> float:
    return lon / 15.0


def approx_sunrise_sunset(d: date, lat: float, lon: float) -> tuple[datetime, datetime]:
    """Rough sunrise/sunset UTC then caller converts to local."""
    # Day of year
    n = d.timetuple().tm_yday
    decl = 23.44 * math.sin(math.radians(360 / 365 * (n - 81)))
    lat_r, decl_r = math.radians(lat), math.radians(decl)
    cos_h = -math.tan(lat_r) * math.tan(decl_r)
    cos_h = max(-1.0, min(1.0, cos_h))
    H = math.degrees(math.acos(cos_h)) / 15.0  # hours from noon
    noon_utc = 12.0 - _solar_noon_offset_hours(lon)
    rise = noon_utc - H
    set_ = noon_utc + H

    def _at(hours: float) -> datetime:
        base = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        return base + timedelta(hours=hours)

    return _at(rise), _at(set_)


def tithi_index(dt: datetime) -> int:
    """Lunar day 0–29 from elongation."""
    elong = _moon_sun_elongation_deg(dt)
    return int(elong // 12) % 30


def is_bhadra_karana(dt: datetime) -> bool:
    """
    Vishti (Bhadra) karana occupies specific half-tithis.
    Simplified: karana index from elongation; Vishti is karana #7 in the rotating list
    for movable karanas (approx every 8th half-tithi after the fixed ones).
    """
    elong = _moon_sun_elongation_deg(dt)
    half = int(elong // 6) % 60  # 60 half-tithis per synodic month
    # Movable karanas cycle: Bava, Balava, Kaulava, Taitila, Gara, Vanija, Vishti (7)
    if half < 1 or half >= 59:
        return False  # Kimstughna / fixed edges — skip
    movable = (half - 1) % 7
    return movable == 6  # Vishti / Bhadra


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _fetch_daily(
    ticker: str,
    market: str,
    *,
    limit: int,
    groww_token: str,
    exchange: str,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market or "crypto" in market.lower()
    df = normalize_ohlcv(
        fetch_data_for_gap_scan(ticker, "1d", market, groww_token, exchange, limit=limit)
    )
    if df is None or df.empty or len(df) < 40:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, "1d", is_crypto=is_crypto, limit=limit, market=market)
        )
    return df if df is not None else pd.DataFrame()


def _session_row(df: pd.DataFrame, day: date) -> pd.Series | None:
    if df.empty:
        return None
    # match date on index
    for i in range(len(df)):
        ts = pd.Timestamp(df.index[i])
        if ts.date() == day:
            return df.iloc[i]
    # nearest prior session
    prior = df[df.index.date <= day] if hasattr(df.index, "date") else df
    try:
        mask = pd.to_datetime(df.index).date <= day
        prior = df.loc[mask]
    except Exception:
        prior = df
    if prior.empty:
        return None
    return prior.iloc[-1]


@dataclass
class AstroFinanceConfig:
    strategy: str = "lunar_cycle"
    lookback_days: int = 730
    forward_days: int = 3
    event_window_days: int = 1
    strong_moon_signs: list[str] = field(default_factory=list)  # Ashtakvarga-lite
    timezone_name: str = ""


# ---------------------------------------------------------------------------
# Trade setup helper
# ---------------------------------------------------------------------------

def _build_trade_suggestion(
    *,
    action: str,
    confidence_pct: float,
    plain_english: str,
    reasons: list[str],
    entry: float | None = None,
    sl_pct: float | None = None,
    tp_pct: float | None = None,
    action_label: str | None = None,
) -> dict[str, Any]:
    """BUY / SELL / WAIT with confidence · SL% · TP% · explanation."""
    act = (action or "WAIT").upper()
    if act not in ("BUY", "SELL", "WAIT"):
        act = "WAIT"
    side = "LONG" if act == "BUY" else ("SHORT" if act == "SELL" else "WAIT")
    label = action_label or (
        "BUY — astro timing" if act == "BUY" else ("SELL — astro timing" if act == "SELL" else "WAIT — timing overlay")
    )
    sl = tp = None
    if act in ("BUY", "SELL"):
        if sl_pct is not None:
            sl = round(max(0.15, float(sl_pct)), 2)
        if tp_pct is not None:
            tp = round(max(0.20, float(tp_pct)), 2)
    stop_price = target_price = None
    entry_f = float(entry) if entry and entry > 0 else None
    if entry_f and sl is not None:
        if act == "BUY":
            stop_price = round(entry_f * (1 - sl / 100), 6)
            if tp is not None:
                target_price = round(entry_f * (1 + tp / 100), 6)
        else:
            stop_price = round(entry_f * (1 + sl / 100), 6)
            if tp is not None:
                target_price = round(entry_f * (1 - tp / 100), 6)
    rr = round(tp / sl, 2) if sl and tp and sl > 0 else None
    return {
        "action": act,
        "action_label": label,
        "side": side,
        "confidence_pct": round(float(confidence_pct), 1),
        "sl_pct": sl,
        "tp_pct": tp,
        "rr": rr,
        "entry_price": round(entry_f, 6) if entry_f else None,
        "stop_price": stop_price,
        "target_price": target_price,
        "plain_english": plain_english,
        "advice": plain_english,
        "reasons": [r for r in reasons if r][:6],
    }


# ---------------------------------------------------------------------------
# Strategy: Lunar Cycle
# ---------------------------------------------------------------------------

def analyze_lunar_cycle(
    ticker: str,
    market: str,
    *,
    cfg: AstroFinanceConfig,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    df = _fetch_daily(ticker, market, limit=min(1200, cfg.lookback_days + 50), groww_token=groww_token, exchange=exchange)
    if df.empty or len(df) < 60:
        return {"ticker": ticker, "error": "Insufficient daily data"}

    end = pd.Timestamp(df.index[-1]).date()
    start = end - timedelta(days=cfg.lookback_days)
    events = find_lunar_events(start, end + timedelta(days=40))

    now = datetime.now(timezone.utc)
    elong = _moon_sun_elongation_deg(now)
    upcoming = [e for e in events if date.fromisoformat(e["date"]) >= date.today()][:6]
    past = [e for e in events if date.fromisoformat(e["date"]) < date.today()]

    samples = []
    for ev in past[-80:]:
        d0 = date.fromisoformat(ev["date"])
        row = _session_row(df, d0)
        if row is None:
            continue
        # forward return
        idx = df.index.get_indexer([row.name], method="nearest")[0]
        j = idx + cfg.forward_days
        if j >= len(df):
            continue
        entry = float(row["close"])
        fwd = float(df["close"].iloc[j])
        next_ = float(df["close"].iloc[min(idx + 1, len(df) - 1)])
        hi = float(df["high"].iloc[idx : j + 1].max())
        lo = float(df["low"].iloc[idx : j + 1].min())
        samples.append({
            "date": d0.isoformat(),
            "type": ev["type"],
            "close": round(entry, 4),
            "next_day_return_pct": round((next_ / entry - 1) * 100, 3),
            "forward_return_pct": round((fwd / entry - 1) * 100, 3),
            "range_pct": round((hi - lo) / entry * 100, 3),
        })

    def _summ(kind: str) -> dict[str, Any]:
        rows = [s for s in samples if s["type"] == kind]
        if not rows:
            return {"samples": 0}
        fwd = [r["forward_return_pct"] for r in rows]
        rng = [r["range_pct"] for r in rows]
        up = sum(1 for x in fwd if x > 0)
        return {
            "samples": len(rows),
            "avg_forward_return_pct": round(float(np.mean(fwd)), 3),
            "median_forward_return_pct": round(float(np.median(fwd)), 3),
            "avg_range_pct": round(float(np.mean(rng)), 3),
            "up_rate_pct": round(100.0 * up / len(rows), 1),
        }

    ama = _summ("Amavasya")
    poor = _summ("Poornima")
    # Bias: higher historical range near events → expect volatility; direction from avg fwd
    vol_note = "elevated" if max(ama.get("avg_range_pct") or 0, poor.get("avg_range_pct") or 0) > 0 else "—"
    nearest = upcoming[0] if upcoming else None
    bias = "WAIT"
    conf = 40.0
    active_stats: dict[str, Any] = {}
    if nearest:
        days_to = (date.fromisoformat(nearest["date"]) - date.today()).days
        if days_to <= cfg.event_window_days + 1:
            kind = nearest["type"]
            stats = ama if kind == "Amavasya" else poor
            active_stats = stats
            avg = stats.get("avg_forward_return_pct") or 0
            if avg > 0.15:
                bias = "BUY"
            elif avg < -0.15:
                bias = "SELL"
            conf = min(78.0, 45 + abs(avg) * 8 + (stats.get("samples") or 0) * 0.3)

    ltp = float(df["close"].iloc[-1])
    plain = (
        f"Moon phase now: {moon_phase_name(elong)} ({moon_illumination(elong)}% illum). "
        f"Next event: {nearest['type'] if nearest else '—'} on {nearest['date'] if nearest else '—'}. "
        f"Historical {cfg.forward_days}d fwd after Amavasya avg {ama.get('avg_forward_return_pct', '—')}% "
        f"(n={ama.get('samples', 0)}); Poornima avg {poor.get('avg_forward_return_pct', '—')}% "
        f"(n={poor.get('samples', 0)}). Volatility near lunations tends to be {vol_note}. "
        "Use as timing overlay with TA (Harshubh)."
    )
    avg_fwd = float(active_stats.get("avg_forward_return_pct") or 0)
    avg_rng = float(active_stats.get("avg_range_pct") or 0)
    sl_pct = tp_pct = None
    if bias in ("BUY", "SELL"):
        sl_pct = max(0.35, avg_rng * 0.45) if avg_rng > 0 else max(0.4, abs(avg_fwd) * 0.7)
        tp_pct = max(0.45, abs(avg_fwd) * 1.15 if abs(avg_fwd) > 0 else avg_rng * 0.55)
    reasons = [
        f"Next: {nearest['type'] if nearest else '—'} {nearest['date'] if nearest else ''}".strip(),
        f"Active-event fwd avg {avg_fwd:+.2f}% · range {avg_rng:.2f}%" if active_stats else "No event in window",
        f"Amavasya n={ama.get('samples', 0)} · Poornima n={poor.get('samples', 0)}",
        "Confirm with price structure — lunar bias is timing only",
    ]
    trade = _build_trade_suggestion(
        action=bias,
        confidence_pct=conf,
        plain_english=plain,
        reasons=reasons,
        entry=ltp,
        sl_pct=sl_pct,
        tp_pct=tp_pct,
        action_label="BUY — lunar window" if bias == "BUY" else ("SELL — lunar window" if bias == "SELL" else "WAIT — lunar overlay"),
    )
    take = bias in ("BUY", "SELL") and conf >= 55

    return {
        "ticker": ticker,
        "strategy": "lunar_cycle",
        "ltp": round(ltp, 4),
        "now": {
            "utc": now.isoformat(),
            "elongation_deg": round(elong, 1),
            "illumination_pct": moon_illumination(elong),
            "phase": moon_phase_name(elong),
            "moon_sign_sidereal_approx": moon_zodiac_sign(now),
        },
        "upcoming_events": upcoming,
        "stats_amavasya": ama,
        "stats_poornima": poor,
        "sample_events": samples[-12:],
        "prediction": {
            "bias": bias,
            "confidence_pct": round(conf, 1),
            "plain_english": plain,
        },
        "live": {
            "take_trade": take,
            "direction": "LONG" if bias == "BUY" else ("SHORT" if bias == "SELL" else None),
            "verdict": f"WATCH {bias}" if bias != "WAIT" else "WAIT",
            "confidence_pct": round(conf, 1),
            "signal": bias if bias != "WAIT" else "NONE",
            "trade_suggestion": trade,
            "sl_pct": trade.get("sl_pct"),
            "tp_pct": trade.get("tp_pct"),
        },
        "trade_suggestion": trade,
        "references": [YOUTUBE_HARSHUBH_VIJAY, YOUTUBE_HARSHUBH_VIKAS],
    }


# ---------------------------------------------------------------------------
# Strategy: Amavasya S/R
# ---------------------------------------------------------------------------

def analyze_amavasya_sr(
    ticker: str,
    market: str,
    *,
    cfg: AstroFinanceConfig,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    df = _fetch_daily(ticker, market, limit=min(1200, cfg.lookback_days + 50), groww_token=groww_token, exchange=exchange)
    if df.empty:
        return {"ticker": ticker, "error": "Insufficient daily data"}

    end = pd.Timestamp(df.index[-1]).date()
    start = end - timedelta(days=cfg.lookback_days)
    events = [e for e in find_lunar_events(start, end) if e["type"] == "Amavasya"]

    levels: list[dict[str, Any]] = []
    for ev in events:
        d0 = date.fromisoformat(ev["date"])
        row = _session_row(df, d0)
        if row is None:
            continue
        levels.append({
            "amavasya_date": d0.isoformat(),
            "high": round(float(row["high"]), 4),
            "low": round(float(row["low"]), 4),
            "close": round(float(row["close"]), 4),
        })

    # Cluster: keep unbroken (still relevant) levels — high above price = resistance, low below = support
    ltp = float(df["close"].iloc[-1])
    supports, resistances = [], []
    for lv in levels:
        # Update rule: if later close broke the level, demote
        broken_high = bool((df["close"] > lv["high"]).any()) and lv["high"] < ltp * 1.15
        broken_low = bool((df["close"] < lv["low"]).any()) and lv["low"] > ltp * 0.85
        # Respect check: how often price wick-tagged within 0.4%
        tol = ltp * 0.004
        touch_h = int(((df["high"] >= lv["high"] - tol) & (df["low"] <= lv["high"] + tol)).sum())
        touch_l = int(((df["high"] >= lv["low"] - tol) & (df["low"] <= lv["low"] + tol)).sum())
        if lv["low"] <= ltp:
            supports.append({**lv, "side": "support", "touches": touch_l, "broken": broken_low and lv["low"] > float(df["close"].min())})
        if lv["high"] >= ltp:
            resistances.append({**lv, "side": "resistance", "touches": touch_h, "broken": broken_high})

    supports.sort(key=lambda x: -x["low"])
    resistances.sort(key=lambda x: x["high"])
    nearest_s = supports[:5]
    nearest_r = resistances[:5]

    dist_s = (ltp - nearest_s[0]["low"]) / ltp * 100 if nearest_s else None
    dist_r = (nearest_r[0]["high"] - ltp) / ltp * 100 if nearest_r else None
    bias = "WAIT"
    conf = 42.0
    if dist_s is not None and dist_s <= 0.6:
        bias = "BUY"
        conf = 62.0
    elif dist_r is not None and dist_r <= 0.6:
        bias = "SELL"
        conf = 62.0

    bits = [f"Amavasya S/R map from {len(levels)} New-Moon sessions."]
    if nearest_s and dist_s is not None:
        bits.append(f"Nearest support {nearest_s[0]['low']} ({dist_s:.2f}% away)")
    if nearest_r and dist_r is not None:
        bits.append(f"Nearest resistance {nearest_r[0]['high']} ({dist_r:.2f}% away)")
    bits.append("Mark highs/lows on Amavasya days; update when broken (Harshubh). Pair with TA confluence.")
    plain = " ".join(bits)

    sl_pct = tp_pct = None
    if bias == "BUY" and nearest_s:
        # Stop under support; target toward resistance (or 1.2× dist to support as fallback)
        cushion = max(0.2, (dist_s or 0) + 0.25)
        sl_pct = cushion
        if nearest_r and dist_r is not None:
            tp_pct = max(0.35, dist_r)
        else:
            tp_pct = max(0.5, cushion * 1.5)
    elif bias == "SELL" and nearest_r:
        cushion = max(0.2, (dist_r or 0) + 0.25)
        sl_pct = cushion
        if nearest_s and dist_s is not None:
            tp_pct = max(0.35, dist_s)
        else:
            tp_pct = max(0.5, cushion * 1.5)

    reasons = [
        f"LTP {ltp:,.2f}",
        f"Support {nearest_s[0]['low'] if nearest_s else '—'} ({dist_s:.2f}% away)" if nearest_s and dist_s is not None else "No nearby Amavasya support",
        f"Resistance {nearest_r[0]['high'] if nearest_r else '—'} ({dist_r:.2f}% away)" if nearest_r and dist_r is not None else "No nearby Amavasya resistance",
        f"{len(levels)} Amavasya sessions mapped",
    ]
    trade = _build_trade_suggestion(
        action=bias,
        confidence_pct=conf,
        plain_english=plain,
        reasons=reasons,
        entry=ltp,
        sl_pct=sl_pct,
        tp_pct=tp_pct,
        action_label="BUY — Amavasya support" if bias == "BUY" else ("SELL — Amavasya resistance" if bias == "SELL" else "WAIT — Amavasya S/R"),
    )

    return {
        "ticker": ticker,
        "strategy": "amavasya_sr",
        "ltp": round(ltp, 4),
        "amavasya_count": len(levels),
        "supports": nearest_s,
        "resistances": nearest_r,
        "all_levels_tail": levels[-10:],
        "prediction": {
            "bias": bias,
            "confidence_pct": conf,
            "plain_english": plain,
        },
        "live": {
            "take_trade": bias in ("BUY", "SELL"),
            "direction": "LONG" if bias == "BUY" else ("SHORT" if bias == "SELL" else None),
            "verdict": f"WATCH {bias}" if bias != "WAIT" else "WAIT",
            "confidence_pct": conf,
            "signal": bias if bias != "WAIT" else "NONE",
            "support_level": nearest_s[0]["low"] if nearest_s else None,
            "resistance_level": nearest_r[0]["high"] if nearest_r else None,
            "trade_suggestion": trade,
            "sl_pct": trade.get("sl_pct"),
            "tp_pct": trade.get("tp_pct"),
            "entry_price": trade.get("entry_price"),
            "stop_price": trade.get("stop_price"),
            "target_price": trade.get("target_price"),
        },
        "trade_suggestion": trade,
        "references": [YOUTUBE_HARSHUBH_VIJAY],
    }


# ---------------------------------------------------------------------------
# Strategy: Bhadra timing
# ---------------------------------------------------------------------------

def analyze_bhadra_timing(
    ticker: str,
    asset_class: str,
    market: str,
    *,
    cfg: AstroFinanceConfig,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    tz_name = cfg.timezone_name or MARKET_TZ.get(asset_class, "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
        tz_name = "UTC"

    today = datetime.now(tz).date()
    windows = []
    # Scan today + next 2 days hourly for Bhadra overlap with typical cash session
    session = {
        "india": (9, 15, 15, 30),
        "us": (9, 30, 16, 0),
        "crypto": (0, 0, 23, 59),
        "commodity": (9, 0, 17, 0),
    }.get(asset_class, (9, 0, 16, 0))

    for day_off in range(0, 3):
        d = today + timedelta(days=day_off)
        for hour in range(0, 24):
            for minute in (0, 30):
                local = datetime(d.year, d.month, d.day, hour, minute, tzinfo=tz)
                if not is_bhadra_karana(local.astimezone(timezone.utc)):
                    continue
                # session filter
                sh, sm, eh, em = session
                start_m = sh * 60 + sm
                end_m = eh * 60 + em
                cur_m = hour * 60 + minute
                in_session = start_m <= cur_m <= end_m if asset_class != "crypto" else True
                if in_session:
                    windows.append({
                        "local_time": local.isoformat(),
                        "timezone": tz_name,
                        "karana": "Vishti (Bhadra)",
                        "note": "Reversal / daily top-bottom timing window (approx)",
                    })

    # Collapse contiguous
    collapsed = []
    for w in windows:
        if collapsed:
            prev = datetime.fromisoformat(collapsed[-1]["end"])
            cur = datetime.fromisoformat(w["local_time"])
            if (cur - prev) <= timedelta(minutes=35):
                collapsed[-1]["end"] = w["local_time"]
                continue
        collapsed.append({"start": w["local_time"], "end": w["local_time"], "karana": w["karana"], "timezone": tz_name})

    # Optional: fetch LTP context
    df = _fetch_daily(ticker, market, limit=30, groww_token=groww_token, exchange=exchange)
    ltp = float(df["close"].iloc[-1]) if not df.empty else None

    now_local = datetime.now(tz)
    active = any(
        datetime.fromisoformat(c["start"]) <= now_local <= datetime.fromisoformat(c["end"]) + timedelta(minutes=30)
        for c in collapsed
    )

    plain = (
        f"Bhadra (Vishti Karana) windows overlapping {asset_class} session in {tz_name}. "
        f"{'ACTIVE now — watch for intraday reversal / swing extreme.' if active else 'No Bhadra overlap right now.'} "
        f"{len(collapsed)} window(s) in next ~3 sessions. "
        "Harshubh: time is the catalyst — wait for Bhadra + price reaction, not Bhadra alone."
    )
    conf = 55.0 if active else 40.0
    # Timing overlay: no directional SL/TP until price reacts — still emit WAIT setup with conf + explanation.
    trade = _build_trade_suggestion(
        action="WAIT",
        confidence_pct=conf,
        plain_english=plain,
        reasons=[
            "Bhadra ACTIVE — wait for reversal candle / liquidity sweep" if active else "No Bhadra in session now",
            f"{len(collapsed)} Bhadra window(s) next ~3 sessions",
            "Do not size a directional trade on Karana alone",
        ],
        entry=ltp,
        action_label="WAIT — Bhadra timing",
    )

    return {
        "ticker": ticker,
        "strategy": "bhadra_timing",
        "timezone": tz_name,
        "ltp": ltp,
        "bhadra_windows": collapsed[:20],
        "bhadra_active_now": active,
        "prediction": {
            "bias": "WAIT",
            "confidence_pct": conf,
            "plain_english": plain,
        },
        "live": {
            "take_trade": False,
            "verdict": "WATCH REVERSAL" if active else "WAIT",
            "confidence_pct": conf,
            "signal": "NONE",
            "phase": "BHADRA_ACTIVE" if active else "NO_BHADRA",
            "trade_suggestion": trade,
        },
        "trade_suggestion": trade,
        "references": [YOUTUBE_HARSHUBH_VIJAY],
    }


# ---------------------------------------------------------------------------
# Strategy: Transit gaps (Mars / Venus)
# ---------------------------------------------------------------------------

def analyze_transit_gaps(
    ticker: str,
    market: str,
    *,
    cfg: AstroFinanceConfig,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    df = _fetch_daily(ticker, market, limit=min(1200, cfg.lookback_days + 50), groww_token=groww_token, exchange=exchange)
    if df.empty or len(df) < 80:
        return {"ticker": ticker, "error": "Insufficient daily data"}

    end = pd.Timestamp(df.index[-1]).date()
    start = end - timedelta(days=cfg.lookback_days)
    ingresses = find_sign_ingresses("mars", start, end + timedelta(days=60))
    ingresses += find_sign_ingresses("venus", start, end + timedelta(days=60))
    ingresses.sort(key=lambda x: x["date"])

    gap_samples = []
    for ev in ingresses:
        d0 = date.fromisoformat(ev["date"])
        for off in (-1, 0, 1):
            day = d0 + timedelta(days=off)
            row = _session_row(df, day)
            if row is None:
                continue
            # previous close
            idx = df.index.get_indexer([row.name], method="nearest")[0]
            if idx <= 0:
                continue
            prev_c = float(df["close"].iloc[idx - 1])
            open_ = float(row["open"])
            gap_pct = (open_ / prev_c - 1) * 100
            gap_samples.append({
                "date": day.isoformat(),
                "planet": ev["planet"],
                "ingress_date": ev["date"],
                "offset_days": off,
                "to_sign": ev["to_sign"],
                "gap_pct": round(gap_pct, 3),
                "gap_dir": "UP" if gap_pct > 0.15 else ("DOWN" if gap_pct < -0.15 else "FLAT"),
            })

    def _planet_stats(planet: str) -> dict[str, Any]:
        rows = [g for g in gap_samples if g["planet"].lower() == planet.lower()]
        if not rows:
            return {"samples": 0}
        ups = sum(1 for r in rows if r["gap_dir"] == "UP")
        downs = sum(1 for r in rows if r["gap_dir"] == "DOWN")
        return {
            "samples": len(rows),
            "gap_up_pct": round(100.0 * ups / len(rows), 1),
            "gap_down_pct": round(100.0 * downs / len(rows), 1),
            "avg_gap_pct": round(float(np.mean([r["gap_pct"] for r in rows])), 3),
            "avg_abs_gap_pct": round(float(np.mean([abs(r["gap_pct"]) for r in rows])), 3),
        }

    upcoming = [e for e in ingresses if date.fromisoformat(e["date"]) >= date.today()][:8]
    mars_s = _planet_stats("Mars")
    venus_s = _planet_stats("Venus")

    bias = "WAIT"
    conf = 38.0
    active_st: dict[str, Any] = {}
    if upcoming:
        nxt = upcoming[0]
        days = (date.fromisoformat(nxt["date"]) - date.today()).days
        if days <= 2:
            st = mars_s if nxt["planet"] == "Mars" else venus_s
            active_st = st
            if (st.get("gap_up_pct") or 0) >= 55:
                bias = "BUY"
                conf = 58.0
            elif (st.get("gap_down_pct") or 0) >= 55:
                bias = "SELL"
                conf = 58.0
            else:
                conf = 50.0
                bias = "WAIT"

    ltp = float(df["close"].iloc[-1])
    plain = (
        "Mars/Venus sign ingresses (approx Gochar) vs overnight gaps ±1 day. "
        f"Mars: up-rate {mars_s.get('gap_up_pct', '—')}% / down {mars_s.get('gap_down_pct', '—')}% "
        f"(avg |gap| {mars_s.get('avg_abs_gap_pct', '—')}%). "
        f"Venus: up {venus_s.get('gap_up_pct', '—')}% / down {venus_s.get('gap_down_pct', '—')}%. "
        f"Next ingress: {upcoming[0] if upcoming else '—'}. "
        "Harshubh: gaps often align with transits more than 'news' alone — still confirm with TA."
    )
    abs_gap = float(active_st.get("avg_abs_gap_pct") or mars_s.get("avg_abs_gap_pct") or venus_s.get("avg_abs_gap_pct") or 0)
    sl_pct = tp_pct = None
    if bias in ("BUY", "SELL"):
        sl_pct = max(0.3, abs_gap * 0.9) if abs_gap > 0 else 0.45
        tp_pct = max(0.4, abs_gap * 1.4) if abs_gap > 0 else 0.7
    take = bias in ("BUY", "SELL") and conf >= 55
    trade = _build_trade_suggestion(
        action=bias,
        confidence_pct=conf,
        plain_english=plain,
        reasons=[
            f"Next ingress {upcoming[0]['planet']} → {upcoming[0]['to_sign']} on {upcoming[0]['date']}" if upcoming else "No upcoming ingress",
            f"Avg |gap| near transit {abs_gap:.2f}%" if abs_gap else "Gap sample thin",
            f"Mars up {mars_s.get('gap_up_pct', '—')}% · Venus up {venus_s.get('gap_up_pct', '—')}%",
            "Fade/follow only with gap + TA confirmation",
        ],
        entry=ltp,
        sl_pct=sl_pct,
        tp_pct=tp_pct,
        action_label="BUY — transit gap bias" if bias == "BUY" else ("SELL — transit gap bias" if bias == "SELL" else "WAIT — transit overlay"),
    )

    return {
        "ticker": ticker,
        "strategy": "transit_gaps",
        "ltp": round(ltp, 4),
        "stats_mars": mars_s,
        "stats_venus": venus_s,
        "upcoming_ingresses": upcoming,
        "recent_gap_samples": gap_samples[-15:],
        "prediction": {
            "bias": bias,
            "confidence_pct": conf,
            "plain_english": plain,
        },
        "live": {
            "take_trade": take,
            "verdict": f"WATCH GAP {bias}" if bias != "WAIT" else "WAIT",
            "confidence_pct": conf,
            "signal": bias if take else "NONE",
            "direction": "LONG" if bias == "BUY" else ("SHORT" if bias == "SELL" else None),
            "trade_suggestion": trade,
            "sl_pct": trade.get("sl_pct"),
            "tp_pct": trade.get("tp_pct"),
        },
        "trade_suggestion": trade,
        "references": [YOUTUBE_HARSHUBH_VIJAY],
    }


# ---------------------------------------------------------------------------
# Strategy: Trading calendar (Muhurat + Ashtakvarga-lite + commodity map)
# ---------------------------------------------------------------------------

def analyze_trading_calendar(
    asset_class: str,
    *,
    cfg: AstroFinanceConfig,
) -> dict[str, Any]:
    tz_name = cfg.timezone_name or MARKET_TZ.get(asset_class, "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
        tz_name = "UTC"
    lat, lon = MARKET_COORDS.get(asset_class, (0.0, 0.0))

    strong = [s.title() for s in (cfg.strong_moon_signs or []) if s]
    # Default: if none provided, highlight Cancer/Taurus/Pisces as example "liquid" moon signs — user should set from Ashtakvarga
    if not strong:
        strong_note = "No personal Ashtakvarga signs set — showing all Moon signs; configure strong signs (4+ bindus) for ~12–13 favorable days/month."
    else:
        strong_note = f"Favorable when Moon transits: {', '.join(strong)} (Ashtakvarga-lite)."

    today = datetime.now(tz).date()
    calendar = []
    for i in range(0, 35):
        d = today + timedelta(days=i)
        noon = datetime(d.year, d.month, d.day, 12, tzinfo=tz).astimezone(timezone.utc)
        sign = moon_zodiac_sign(noon)
        elong = _moon_sun_elongation_deg(noon)
        phase = moon_phase_name(elong)
        favorable = (not strong) or (sign in strong)
        calendar.append({
            "date": d.isoformat(),
            "moon_sign": sign,
            "phase": phase,
            "illumination_pct": moon_illumination(elong),
            "favorable_trade_day": favorable and "Amavasya" not in phase,  # optional caution on exact new moon
            "is_amavasya": "Amavasya" in phase,
            "is_poornima": "Poornima" in phase,
        })

    # Today's muhurat blocks from sunrise→sunset
    rise_utc, set_utc = approx_sunrise_sunset(today, lat, lon)
    rise_l = rise_utc.astimezone(tz)
    set_l = set_utc.astimezone(tz)
    day_len = (set_l - rise_l).total_seconds()
    muhurats = []
    if day_len > 0:
        slot = day_len / 8.0
        for i, name in enumerate(MUHURAT_NAMES):
            st = rise_l + timedelta(seconds=slot * i)
            en = rise_l + timedelta(seconds=slot * (i + 1))
            muhurats.append({
                "name": name,
                "start_local": st.isoformat(),
                "end_local": en.isoformat(),
                "favorable_execution": name in FAVORABLE_MUHURAT,
            })

    fav_days = [c for c in calendar if c["favorable_trade_day"]]
    plain = (
        f"{strong_note} Today’s favorable Muhurat slots: "
        + ", ".join(m["name"] for m in muhurats if m["favorable_execution"])
        + ". Use Char/Shubh/Amrit/Labh for entries on favorable Moon-sign days. "
        "Astrology times the trade — technicals choose the trade."
    )
    trade = _build_trade_suggestion(
        action="WAIT",
        confidence_pct=45.0,
        plain_english=plain,
        reasons=[
            f"Strong Moon signs: {', '.join(strong) if strong else 'configure Ashtakvarga'}",
            f"{len(fav_days)} favorable Moon-sign days in next ~35",
            "Muhurat times execution — pick direction from TA",
        ],
        action_label="WAIT — calendar / Muhurat",
    )
    return {
        "strategy": "trading_calendar",
        "asset_class": asset_class,
        "timezone": tz_name,
        "strong_moon_signs": strong,
        "note": strong_note,
        "fifth_house_note": (
            "Rahul Bhatnagar: 5th house rules speculation. If personal 5th-house Ashtakvarga < 28 bindus, "
            "trade cautiously (or via family member with stronger 5th). Pillars: Moon, Rahu, Jupiter, Mercury."
        ),
        "upcoming_calendar": calendar,
        "favorable_days_next_35": fav_days[:15],
        "muhurat_today": muhurats,
        "commodity_planet_map": COMMODITY_PLANET_MAP,
        "prediction": {
            "bias": "WAIT",
            "confidence_pct": 45.0,
            "plain_english": plain,
        },
        "live": {
            "take_trade": False,
            "verdict": "CALENDAR",
            "confidence_pct": 45.0,
            "signal": "NONE",
            "trade_suggestion": trade,
        },
        "trade_suggestion": trade,
        "references": [YOUTUBE_RAHUL_BHATNAGAR, YOUTUBE_HARSHUBH_VIKAS],
        "remedies_note": (
            "Optional upay from the video (cultural/spiritual — not trading advice): "
            "green moong to birds (Mercury), serve elders (Moon), turmeric/saffron tilak (Jupiter)."
        ),
    }


# ---------------------------------------------------------------------------
# Strategy: Mercury Retrograde (communications / gaps / false breaks)
# ---------------------------------------------------------------------------

def analyze_mercury_retrograde(
    ticker: str,
    market: str,
    *,
    cfg: AstroFinanceConfig,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    df = _fetch_daily(ticker, market, limit=min(1200, cfg.lookback_days + 50), groww_token=groww_token, exchange=exchange)
    if df.empty or len(df) < 60:
        return {"ticker": ticker, "strategy": "mercury_retrograde", "error": "Insufficient daily data"}

    end = pd.Timestamp(df.index[-1]).date()
    start = end - timedelta(days=cfg.lookback_days)
    stations = find_mercury_stations(start, end + timedelta(days=90))
    now = datetime.now(timezone.utc)
    retro_now = mercury_is_retrograde(now)

    samples = []
    for st in stations:
        if "Retrograde" not in st["type"] and "Direct" not in st["type"]:
            continue
        d0 = date.fromisoformat(st["date"])
        for off in range(-2, cfg.forward_days + 1):
            day = d0 + timedelta(days=off)
            row = _session_row(df, day)
            if row is None:
                continue
            idx = df.index.get_indexer([row.name], method="nearest")[0]
            if idx <= 0 or idx + 1 >= len(df):
                continue
            prev_c = float(df["close"].iloc[idx - 1])
            c = float(row["close"])
            h, l_ = float(row["high"]), float(row["low"])
            fwd = float(df["close"].iloc[min(idx + cfg.forward_days, len(df) - 1)])
            samples.append({
                "date": day.isoformat(),
                "station_type": st["type"],
                "offset_days": off,
                "range_pct": round((h / l_ - 1) * 100, 3) if l_ > 0 else None,
                "ret_pct": round((c / prev_c - 1) * 100, 3) if prev_c > 0 else None,
                "fwd_ret_pct": round((fwd / c - 1) * 100, 3) if c > 0 else None,
            })

    ranges = [s["range_pct"] for s in samples if s.get("range_pct") is not None]
    fwds = [s["fwd_ret_pct"] for s in samples if s.get("fwd_ret_pct") is not None]
    avg_range = round(float(np.mean(ranges)), 3) if ranges else None
    avg_fwd = round(float(np.mean(fwds)), 3) if fwds else None
    up_rate = round(100.0 * sum(1 for x in fwds if x > 0) / len(fwds), 1) if fwds else None

    upcoming = [s for s in stations if date.fromisoformat(s["date"]) >= date.today()][:6]
    ltp = float(df["close"].iloc[-1])
    base_range = float(((df["high"] - df["low"]) / df["close"]).tail(20).mean() * 100) if len(df) >= 20 else 1.0

    if retro_now:
        plain = (
            f"Mercury is retrograde (approx). Near stations, {ticker} historically showed "
            f"avg range {avg_range if avg_range is not None else '—'}% and forward {cfg.forward_days}d "
            f"return {avg_fwd if avg_fwd is not None else '—'}% (up-rate {up_rate if up_rate is not None else '—'}%). "
            "Classic lore: expect misquotes, gap fills, and false breaks — shrink size, demand confirmation."
        )
        bias = "WAIT"
        conf = 58.0
    else:
        nxt = upcoming[0] if upcoming else None
        plain = (
            f"Mercury is direct. Next station ≈ {(nxt or {}).get('type', '—')} on {(nxt or {}).get('date', '—')}. "
            "Use calm tape for clearer entries; diary the station window for volatility."
        )
        bias = "WAIT"
        conf = 42.0

    trade = _build_trade_suggestion(
        action=bias,
        confidence_pct=conf,
        plain_english=plain,
        reasons=[
            "Mercury RETROGRADE — prefer mean-reversion / wait for reclaim" if retro_now else "Mercury direct",
            f"Station samples n={len(samples)}",
            f"Avg |range| near stations {avg_range}% · fwd {avg_fwd}%",
        ],
        entry=ltp,
        sl_pct=round(max(0.4, base_range * 0.8), 2) if retro_now else None,
        tp_pct=round(max(0.6, base_range * 1.2), 2) if retro_now else None,
        action_label="WAIT — Mercury overlay",
    )
    return {
        "ticker": ticker,
        "strategy": "mercury_retrograde",
        "now": {
            "mercury_retrograde": retro_now,
            "geo_longitude_deg": round(_mercury_geo_longitude(now), 1),
        },
        "upcoming_stations": upcoming,
        "stats_near_stations": {
            "samples": len(samples),
            "avg_range_pct": avg_range,
            "avg_forward_return_pct": avg_fwd,
            "up_rate_pct": up_rate,
        },
        "prediction": {"bias": bias, "confidence_pct": conf, "plain_english": plain},
        "live": {
            "take_trade": False,
            "verdict": "MERCURY_RX" if retro_now else "MERCURY_DIRECT",
            "confidence_pct": conf,
            "signal": "NONE",
            "trade_suggestion": trade,
        },
        "trade_suggestion": trade,
        "references": [YOUTUBE_HARSHUBH_VIJAY],
    }


# ---------------------------------------------------------------------------
# Strategy: Nakshatra timing (27 lunar mansions)
# ---------------------------------------------------------------------------

def analyze_nakshatra_timing(
    asset_class: str,
    *,
    cfg: AstroFinanceConfig,
    ticker: str | None = None,
    market: str = "",
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    tz_name = cfg.timezone_name or MARKET_TZ.get(asset_class, "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
        tz_name = "UTC"

    today = datetime.now(tz).date()
    calendar = []
    for i in range(0, 21):
        d = today + timedelta(days=i)
        noon = datetime(d.year, d.month, d.day, 12, tzinfo=tz).astimezone(timezone.utc)
        nk = nakshatra_at(noon)
        calendar.append({"date": d.isoformat(), **nk})

    now_nk = nakshatra_at(datetime.now(timezone.utc))
    tone = now_nk["tone"]
    if tone == "favorable":
        bias, conf = "BUY", 52.0
        plain = (
            f"Moon in {now_nk['nakshatra']} (pada {now_nk['pada']}) — traditionally a smoother "
            "execution mansion. Prefer initiating planned longs/shorts that already have TA confluence."
        )
    elif tone == "volatile":
        bias, conf = "WAIT", 55.0
        plain = (
            f"Moon in {now_nk['nakshatra']} — classed as a sharper / more emotional mansion. "
            "Expect wider ranges; fade chasey breakouts or stand aside until a clean reclaim."
        )
    else:
        bias, conf = "WAIT", 45.0
        plain = (
            f"Moon in {now_nk['nakshatra']} (neutral). Use your normal playbook — nakshatra is a soft timer only."
        )

    ltp = None
    if ticker:
        df = _fetch_daily(ticker, market, limit=40, groww_token=groww_token, exchange=exchange)
        if not df.empty:
            ltp = float(df["close"].iloc[-1])

    trade = _build_trade_suggestion(
        action="WAIT" if bias == "WAIT" else bias,
        confidence_pct=conf,
        plain_english=plain,
        reasons=[
            f"Nakshatra {now_nk['nakshatra']} · tone {tone}",
            f"Pada {now_nk['pada']}",
            "Always confirm with TA",
        ],
        entry=ltp,
        action_label=f"{'BUY lean' if bias == 'BUY' else 'WAIT'} — Nakshatra",
    )
    # Soft lean only — never take_trade from nakshatra alone
    return {
        "ticker": ticker or "CALENDAR",
        "strategy": "nakshatra_timing",
        "timezone": tz_name,
        "now": now_nk,
        "upcoming_nakshatras": calendar,
        "favorable_list": sorted(NAKSHATRA_FAVORABLE),
        "volatile_list": sorted(NAKSHATRA_VOLATILE),
        "prediction": {"bias": "WAIT", "confidence_pct": conf, "plain_english": plain, "soft_lean": bias},
        "live": {
            "take_trade": False,
            "verdict": tone.upper(),
            "confidence_pct": conf,
            "signal": "NONE",
            "trade_suggestion": trade,
        },
        "trade_suggestion": trade,
        "references": [YOUTUBE_RAHUL_BHATNAGAR],
    }


# ---------------------------------------------------------------------------
# Strategy: Tithi + weekday planetary ruler (Panchang overlay)
# ---------------------------------------------------------------------------

def analyze_tithi_panchang(
    asset_class: str,
    *,
    cfg: AstroFinanceConfig,
) -> dict[str, Any]:
    tz_name = cfg.timezone_name or MARKET_TZ.get(asset_class, "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
        tz_name = "UTC"

    now_local = datetime.now(tz)
    td = tithi_detail(now_local.astimezone(timezone.utc))
    wd_name, wd_planet = WEEKDAY_PLANET[now_local.weekday()]
    vib = date_vibration(now_local.date())

    calendar = []
    for i in range(0, 21):
        d = now_local.date() + timedelta(days=i)
        noon = datetime(d.year, d.month, d.day, 12, tzinfo=tz).astimezone(timezone.utc)
        t = tithi_detail(noon)
        wname, wplanet = WEEKDAY_PLANET[d.weekday()]
        calendar.append({
            "date": d.isoformat(),
            **t,
            "weekday": wname,
            "weekday_planet": wplanet,
            "date_vibration": date_vibration(d)["vibration"],
        })

    tone = td["tone"]
    conf = 54.0 if tone == "favorable" else (56.0 if tone == "caution" else 44.0)
    plain = (
        f"Today: {td['tithi_name']} ({td['paksha']}) · {wd_name} ruled by {wd_planet} · "
        f"date vibration {vib['vibration']} ({vib['note']}). "
        f"Tithi tone={tone}. Use favorable tithis for fresh risk; caution days for management / hedges only."
    )
    trade = _build_trade_suggestion(
        action="WAIT",
        confidence_pct=conf,
        plain_english=plain,
        reasons=[
            f"Tithi {td['tithi_name']} · {tone}",
            f"Weekday planet {wd_planet}",
            f"Date vibration {vib['vibration']}: {vib['note']}",
        ],
        action_label="WAIT — Panchang / numerology clock",
    )
    return {
        "strategy": "tithi_panchang",
        "asset_class": asset_class,
        "timezone": tz_name,
        "now": {**td, "weekday": wd_name, "weekday_planet": wd_planet, "date_vibration": vib},
        "upcoming_panchang": calendar,
        "prediction": {"bias": "WAIT", "confidence_pct": conf, "plain_english": plain},
        "live": {
            "take_trade": False,
            "verdict": tone.upper(),
            "confidence_pct": conf,
            "signal": "NONE",
            "trade_suggestion": trade,
        },
        "trade_suggestion": trade,
        "references": [YOUTUBE_RAHUL_BHATNAGAR, YOUTUBE_HARSHUBH_VIKAS],
    }


# ---------------------------------------------------------------------------
# Strategy: Gann Square-of-9 + date numerology
# ---------------------------------------------------------------------------

def analyze_gann_numerology(
    ticker: str,
    market: str,
    *,
    cfg: AstroFinanceConfig,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    df = _fetch_daily(ticker, market, limit=min(400, cfg.lookback_days), groww_token=groww_token, exchange=exchange)
    if df.empty or len(df) < 30:
        return {"ticker": ticker, "strategy": "gann_numerology", "error": "Insufficient daily data"}

    ltp = float(df["close"].iloc[-1])
    levels = gann_square9_levels(ltp, rings=4)
    vib = date_vibration(date.today())
    # Nearest support / resistance from square-9
    below = [x for x in levels if x["distance_pct"] < -0.05]
    above = [x for x in levels if x["distance_pct"] > 0.05]
    nearest_s = min(below, key=lambda x: abs(x["distance_pct"])) if below else None
    nearest_r = min(above, key=lambda x: abs(x["distance_pct"])) if above else None

    atr_pct = float(((df["high"] - df["low"]) / df["close"]).tail(14).mean() * 100)

    # Soft bias: if vibration 5/9 and near resistance → caution; 1/8 near support → long lean
    bias = "WAIT"
    conf = 48.0
    if nearest_s and abs(nearest_s["distance_pct"]) < max(0.35, atr_pct * 0.4) and vib["vibration"] in (1, 4, 8):
        bias, conf = "BUY", 56.0
    elif nearest_r and abs(nearest_r["distance_pct"]) < max(0.35, atr_pct * 0.4) and vib["vibration"] in (5, 7, 9):
        bias, conf = "SELL", 55.0

    plain = (
        f"Gann Square-of-9 around {ltp:g}: nearest support "
        f"{nearest_s['price'] if nearest_s else '—'} · resistance {nearest_r['price'] if nearest_r else '—'}. "
        f"Today’s date vibration {vib['vibration']} — {vib['note']}. "
        "Use levels as magnets; numerology only times attention, not the fill."
    )
    sl = round(max(0.3, atr_pct * 0.7), 2)
    tp = round(max(0.5, atr_pct * 1.3), 2)
    trade = _build_trade_suggestion(
        action=bias if bias in ("BUY", "SELL") else "WAIT",
        confidence_pct=conf,
        plain_english=plain,
        reasons=[
            f"Date vibration {vib['vibration']}",
            f"Nearest S {nearest_s['price'] if nearest_s else '—'}",
            f"Nearest R {nearest_r['price'] if nearest_r else '—'}",
        ],
        entry=ltp,
        sl_pct=sl if bias in ("BUY", "SELL") else None,
        tp_pct=tp if bias in ("BUY", "SELL") else None,
        action_label=f"{bias} — Gann / numerology" if bias != "WAIT" else "WAIT — Gann levels",
    )
    return {
        "ticker": ticker,
        "strategy": "gann_numerology",
        "ltp": ltp,
        "date_vibration": vib,
        "square9_levels": levels,
        "nearest_support": nearest_s,
        "nearest_resistance": nearest_r,
        "prediction": {"bias": bias, "confidence_pct": conf, "plain_english": plain},
        "live": {
            "take_trade": bias in ("BUY", "SELL") and conf >= 54,
            "direction": "LONG" if bias == "BUY" else ("SHORT" if bias == "SELL" else None),
            "verdict": bias,
            "confidence_pct": conf,
            "signal": bias if bias != "WAIT" else "NONE",
            "trade_suggestion": trade,
            "sl_pct": trade.get("sl_pct"),
            "tp_pct": trade.get("tp_pct"),
        },
        "trade_suggestion": trade,
        "references": [YOUTUBE_HARSHUBH_VIJAY],
    }


# ---------------------------------------------------------------------------
# Strategy: Eclipse / Rahu–Ketu node windows
# ---------------------------------------------------------------------------

def analyze_eclipse_nodes(
    ticker: str,
    market: str,
    *,
    cfg: AstroFinanceConfig,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    df = _fetch_daily(ticker, market, limit=min(1200, cfg.lookback_days + 50), groww_token=groww_token, exchange=exchange)
    if df.empty or len(df) < 80:
        return {"ticker": ticker, "strategy": "eclipse_nodes", "error": "Insufficient daily data"}

    end = pd.Timestamp(df.index[-1]).date()
    start = end - timedelta(days=cfg.lookback_days)
    eclipses = find_eclipse_proxies(start, end + timedelta(days=120), orb_deg=18.0)

    samples = []
    for ev in eclipses:
        d0 = date.fromisoformat(ev["date"])
        row = _session_row(df, d0)
        if row is None:
            continue
        idx = df.index.get_indexer([row.name], method="nearest")[0]
        if idx < 0 or idx + cfg.forward_days >= len(df):
            continue
        c = float(row["close"])
        h, l_ = float(row["high"]), float(row["low"])
        fwd = float(df["close"].iloc[idx + cfg.forward_days])
        samples.append({
            "date": ev["date"],
            "type": ev["type"],
            "range_pct": round((h / l_ - 1) * 100, 3) if l_ > 0 else None,
            "fwd_ret_pct": round((fwd / c - 1) * 100, 3) if c > 0 else None,
            "node_orb_deg": ev.get("node_orb_deg"),
        })

    ranges = [s["range_pct"] for s in samples if s.get("range_pct") is not None]
    fwds = [s["fwd_ret_pct"] for s in samples if s.get("fwd_ret_pct") is not None]
    avg_range = round(float(np.mean(ranges)), 3) if ranges else None
    avg_fwd = round(float(np.mean(fwds)), 3) if fwds else None

    upcoming = [e for e in eclipses if date.fromisoformat(e["date"]) >= date.today()][:6]
    now = datetime.now(timezone.utc)
    rahu = _mean_lunar_node_longitude(now, sidereal=True)
    moon = _moon_ecliptic_longitude(now, sidereal=True)
    orb = min(
        abs(((moon - rahu + 180) % 360) - 180),
        abs(((moon - _norm360(rahu + 180) + 180) % 360) - 180),
    )
    near_axis = orb <= 12.0
    ltp = float(df["close"].iloc[-1])

    if near_axis or (upcoming and date.fromisoformat(upcoming[0]["date"]) <= date.today() + timedelta(days=5)):
        plain = (
            f"Near Rahu–Ketu axis (Moon–node orb {orb:.1f}°) or inside an eclipse-proxy window. "
            f"Historically {ticker} avg range {avg_range if avg_range is not None else '—'}% around proxies; "
            f"fwd {cfg.forward_days}d {avg_fwd if avg_fwd is not None else '—'}%. "
            "Institutions treat eclipse seasons as regime-noise weeks — size down, favor hedges / wait."
        )
        conf = 60.0
    else:
        nxt = upcoming[0] if upcoming else None
        plain = (
            f"Outside eclipse season. Next proxy: {(nxt or {}).get('type', '—')} on {(nxt or {}).get('date', '—')} "
            f"(orb {(nxt or {}).get('node_orb_deg', '—')}°). Rahu≈{rahu:.0f}°."
        )
        conf = 40.0

    trade = _build_trade_suggestion(
        action="WAIT",
        confidence_pct=conf,
        plain_english=plain,
        reasons=[
            f"Moon–node orb {orb:.1f}°",
            f"Eclipse-proxy samples n={len(samples)}",
            f"Avg range {avg_range}% · fwd {avg_fwd}%",
        ],
        entry=ltp,
        action_label="WAIT — Eclipse / node axis",
    )
    return {
        "ticker": ticker,
        "strategy": "eclipse_nodes",
        "now": {
            "rahu_longitude_deg": round(rahu, 1),
            "ketu_longitude_deg": round(_norm360(rahu + 180), 1),
            "moon_longitude_deg": round(moon, 1),
            "moon_node_orb_deg": round(orb, 1),
            "near_rahu_ketu_axis": near_axis,
        },
        "upcoming_eclipse_proxies": upcoming,
        "stats_eclipse_windows": {
            "samples": len(samples),
            "avg_range_pct": avg_range,
            "avg_forward_return_pct": avg_fwd,
        },
        "prediction": {"bias": "WAIT", "confidence_pct": conf, "plain_english": plain},
        "live": {
            "take_trade": False,
            "verdict": "ECLIPSE_WATCH" if near_axis else "CLEAR",
            "confidence_pct": conf,
            "signal": "NONE",
            "trade_suggestion": trade,
        },
        "trade_suggestion": trade,
        "references": [YOUTUBE_HARSHUBH_VIJAY, YOUTUBE_RAHUL_BHATNAGAR],
    }


# ---------------------------------------------------------------------------
# Universe scan wrappers
# ---------------------------------------------------------------------------

STRATEGY_IDS = [
    "lunar_cycle",
    "amavasya_sr",
    "bhadra_timing",
    "transit_gaps",
    "trading_calendar",
    "mercury_retrograde",
    "nakshatra_timing",
    "tithi_panchang",
    "gann_numerology",
    "eclipse_nodes",
]

STRATEGY_LABELS = {
    "lunar_cycle": "Lunar Cycle (Amavasya / Poornima)",
    "amavasya_sr": "Amavasya Support & Resistance",
    "bhadra_timing": "Bhadra Reversal Timing",
    "transit_gaps": "Transit Gap Bias (Mars / Venus)",
    "trading_calendar": "Trading Calendar · Muhurat · Commodity Map",
    "mercury_retrograde": "Mercury Retrograde (stations / noise)",
    "nakshatra_timing": "Nakshatra Timing (27 lunar mansions)",
    "tithi_panchang": "Tithi · Weekday · Date Numerology",
    "gann_numerology": "Gann Square-of-9 · Date Vibration",
    "eclipse_nodes": "Eclipse / Rahu–Ketu Axis",
}

# Desks that run without ticker selection (calendar / clock)
CALENDAR_STRATEGY_IDS = {"trading_calendar", "nakshatra_timing", "tithi_panchang"}

# Plain-language desk intros — what the desk is about for non-experts
STRATEGY_LAYMAN_INTRO = {
    "lunar_cycle": (
        "New Moon (Amavasya) and Full Moon (Poornima) often coincide with emotional "
        "swings in markets — swings in mood can show up as bigger moves or reversals."
    ),
    "amavasya_sr": (
        "Prices on New-Moon sessions leave footprints: that day’s high/low often act "
        "later as floors (support) or ceilings (resistance) traders watch for bounces or stalls."
    ),
    "bhadra_timing": (
        "Bhadra (Vishti Karana) is a traditional ‘awkward’ time window. During market hours "
        "it is used as a clock for possible intraday tops/bottoms — not a buy/sell by itself."
    ),
    "transit_gaps": (
        "When Mars or Venus change zodiac signs, overnight gaps (open vs prior close) have "
        "historically clustered. This desk checks if a gap bias shows up near those dates."
    ),
    "trading_calendar": (
        "A date planner: which Moon-sign days and Muhurat time slots are traditionally "
        "favored for placing trades. It times *when* to act — technicals still decide *what*."
    ),
    "mercury_retrograde": (
        "Mercury retrograde periods are linked to miscommunication, gap fills, and false "
        "breakouts. The desk flags stations and measures historical range/forward returns nearby."
    ),
    "nakshatra_timing": (
        "The Moon moves through 27 Nakshatras (lunar mansions). Some are treated as smoother "
        "for execution; others as sharper / more emotional — a soft timing filter."
    ),
    "tithi_panchang": (
        "Vedic lunar day (Tithi) plus weekday planetary ruler and a simple date vibration "
        "number — a Panchang-style clock for when to add risk vs manage only."
    ),
    "gann_numerology": (
        "W.D. Gann’s Square of 9 turns the last price into a spiral of support/resistance, "
        "paired with the day’s numerology vibration for attention timing."
    ),
    "eclipse_nodes": (
        "When New/Full Moon sits near the Rahu–Ketu (lunar node) axis, markets often print "
        "noisier ‘eclipse season’ weeks — size down and demand confirmation."
    ),
}


def _action_verb(bias: str) -> str:
    b = (bias or "WAIT").upper()
    if b in ("BUY", "LONG"):
        return "BUY / look for longs"
    if b in ("SELL", "SHORT"):
        return "SELL / look for shorts"
    return "WAIT / stay flat"


def enrich_with_layman(row: dict[str, Any]) -> dict[str, Any]:
    """Attach strategy_label + layman explanation (what / trading link / action)."""
    if not isinstance(row, dict):
        return row
    sid = str(row.get("strategy") or "")
    label = STRATEGY_LABELS.get(sid, sid.replace("_", " ").title() or "Astro desk")
    row["strategy_label"] = label
    if row.get("error"):
        row["layman"] = {
            "what_this_means": STRATEGY_LAYMAN_INTRO.get(sid, "Astro Finance timing desk."),
            "how_it_relates_to_trading": (
                "We could not finish this desk for this symbol (data or calculation issue)."
            ),
            "what_action_to_take": "Skip this symbol for now, or retry later. Do not trade on a failed scan.",
            "summary": f"{label}: scan failed — {str(row.get('error'))[:160]}",
        }
        return row

    pred = row.get("prediction") if isinstance(row.get("prediction"), dict) else {}
    live = row.get("live") if isinstance(row.get("live"), dict) else {}
    trade = row.get("trade_suggestion") if isinstance(row.get("trade_suggestion"), dict) else {}
    bias = str(pred.get("bias") or live.get("signal") or trade.get("action") or "WAIT").upper()
    if bias in ("NONE", ""):
        bias = "WAIT"
    conf = pred.get("confidence_pct") or live.get("confidence_pct") or trade.get("confidence_pct")
    try:
        conf_s = f"{float(conf):.0f}%" if conf is not None else "—"
    except (TypeError, ValueError):
        conf_s = "—"

    intro = STRATEGY_LAYMAN_INTRO.get(sid, "Astro Finance timing overlay.")
    plain = str(pred.get("plain_english") or trade.get("plain_english") or "").strip()

    # Desk-specific “how it relates”
    if sid == "lunar_cycle":
        nearest = None
        upcoming = row.get("upcoming_events") or []
        if isinstance(upcoming, list) and upcoming:
            nearest = upcoming[0] if isinstance(upcoming[0], dict) else None
        phase = (row.get("now") or {}).get("phase") if isinstance(row.get("now"), dict) else None
        relate = (
            f"Right now the Moon looks like “{phase or '—'}”. "
            f"Next big lunar checkpoint: "
            f"{(nearest or {}).get('type', '—')} on {(nearest or {}).get('date', '—')}. "
            "Traders use that window to expect more volatility or a turn — then confirm with chart structure."
        )
        if bias == "BUY":
            action = (
                f"Lean long into/near the lunar window only if price already looks constructive "
                f"(higher lows / support hold). Confidence ~{conf_s}. Use the suggested SL%/TP% and "
                "skip if the chart disagrees."
            )
        elif bias == "SELL":
            action = (
                f"Lean short / reduce longs near the lunar window only if price is weak "
                f"(lower highs / resistance rejection). Confidence ~{conf_s}. Honor SL%/TP%; "
                "do not sell solely because of the Moon."
            )
        else:
            action = (
                "No clear lunar edge right now — wait for the next Amavasya/Poornima window "
                "or a clean TA setup. Treat this as a calendar reminder, not a signal."
            )
    elif sid == "amavasya_sr":
        supports = row.get("supports") or []
        resists = row.get("resistances") or []
        s0 = supports[0] if supports and isinstance(supports[0], dict) else None
        r0 = resists[0] if resists and isinstance(resists[0], dict) else None
        relate = (
            "New-Moon highs/lows are marked like sticky price magnets. "
            f"Nearest support ≈ {s0.get('low') if s0 else '—'}; "
            f"nearest resistance ≈ {r0.get('high') if r0 else '—'}. "
            "Investors use them as levels to watch for bounce / stall; day traders fade or break them with confirmation."
        )
        if bias == "BUY":
            action = (
                f"Watch for a hold/bounce at Amavasya support — buy dips only with candle confirmation. "
                f"Confidence ~{conf_s}. Stop under the support; target toward resistance / prior structure."
            )
        elif bias == "SELL":
            action = (
                f"Watch for rejection at Amavasya resistance — sell strength only with confirmation. "
                f"Confidence ~{conf_s}. Stop above the ceiling; target toward support."
            )
        else:
            action = (
                "Price is not hugging a New-Moon level closely enough — mark the levels on your chart "
                "and wait. No forced trade from Amavasya S/R alone."
            )
    elif sid == "bhadra_timing":
        active = bool(row.get("bhadra_active_now"))
        n_win = len(row.get("bhadra_windows") or [])
        relate = (
            f"{'Bhadra is ACTIVE in the cash session now' if active else 'No Bhadra overlap in session right now'}. "
            f"{n_win} window(s) mapped over the next ~3 sessions. "
            "Think of it as a ‘watch the clock’ alert for possible turning points — not a direction call."
        )
        action = (
            "If Bhadra is active: do not chase; wait for a clear reversal candle / sweep, then trade "
            "in the direction of that reaction with tight risk. If inactive: note upcoming windows and "
            "plan alerts — stay flat until price reacts."
        )
    elif sid == "transit_gaps":
        upcoming = row.get("upcoming_ingresses") or []
        nxt = upcoming[0] if upcoming and isinstance(upcoming[0], dict) else None
        relate = (
            "Planet sign-changes can line up with gap opens. "
            f"Next ingress: {(nxt or {}).get('planet', '—')} into {(nxt or {}).get('to_sign', '—')} "
            f"on {(nxt or {}).get('date', '—')}. "
            "Traders prepare for a gap day; investors treat it as a volatility heads-up, not a thesis by itself."
        )
        if bias == "BUY":
            action = (
                f"Historical tilt favors gap-up / long bias near this transit (conf ~{conf_s}). "
                "Only act if the open gaps with your bias and TA agrees; use SL%/TP%. Fade fake gaps."
            )
        elif bias == "SELL":
            action = (
                f"Historical tilt favors gap-down / short bias near this transit (conf ~{conf_s}). "
                "Only act with a confirming open + structure; use SL%/TP%."
            )
        else:
            action = (
                "No strong gap edge yet — diary the next Mars/Venus ingress and watch the open that day. "
                "Stay flat until the gap and chart agree."
            )
    elif sid == "trading_calendar":
        fav = row.get("favorable_days_next_35") or []
        muh = [m for m in (row.get("muhurat_today") or []) if isinstance(m, dict) and m.get("favorable_execution")]
        relate = (
            f"{len(fav)} Moon-sign ‘favorable’ day(s) in the next ~35. "
            f"Today’s preferred Muhurat slots: {', '.join(m.get('name', '') for m in muh) or 'none marked'}. "
            "Use the calendar to schedule entries; still pick direction and size from technicals / risk rules."
        )
        action = (
            "Prefer placing new trades on favorable Moon-sign days during Char / Shubh / Amrit / Labh slots "
            "when your TA setup is ready. Avoid forcing trades on off days just because the calendar is empty — "
            "skipping is a valid action."
        )
    elif sid == "mercury_retrograde":
        now = row.get("now") if isinstance(row.get("now"), dict) else {}
        rx = bool(now.get("mercury_retrograde"))
        st = row.get("stats_near_stations") if isinstance(row.get("stats_near_stations"), dict) else {}
        relate = (
            f"Mercury is {'RETROGRADE' if rx else 'direct'} right now. "
            f"Near past stations, avg range {st.get('avg_range_pct', '—')}% · "
            f"forward return {st.get('avg_forward_return_pct', '—')}% (n={st.get('samples', 0)}). "
            "Traders treat Rx as a noise filter; investors avoid chasing headlines during the window."
        )
        action = (
            "During Rx: cut size, wait for reclaim of broken levels, and double-check order tickets. "
            "Outside Rx: note the next station date and plan alerts — do not invent a direction from Mercury alone."
        )
    elif sid == "nakshatra_timing":
        now = row.get("now") if isinstance(row.get("now"), dict) else {}
        relate = (
            f"Moon in {now.get('nakshatra', '—')} (pada {now.get('pada', '—')}, tone {now.get('tone', '—')}). "
            "Favorable mansions = smoother to execute planned setups; volatile mansions = wider ranges / fakeouts."
        )
        action = (
            "If tone is favorable and your chart already has a setup, you may initiate with normal risk. "
            "If volatile: wait for a confirmed candle / volume spike before entry, or stand aside."
        )
    elif sid == "tithi_panchang":
        now = row.get("now") if isinstance(row.get("now"), dict) else {}
        vib = now.get("date_vibration") if isinstance(now.get("date_vibration"), dict) else {}
        relate = (
            f"Tithi {now.get('tithi_name', '—')} ({now.get('paksha', '—')}) · "
            f"{now.get('weekday', '—')} / {now.get('weekday_planet', '—')} · "
            f"date vibration {vib.get('vibration', '—')} ({vib.get('note', '')}). "
            "Panchang times risk appetite; charts still pick the trade."
        )
        action = (
            "On favorable tithis: ok to add fresh risk when TA agrees. On caution tithis (Chaturdashi / "
            "Amavasya/Poornima slot): prefer managing open trades / hedges only."
        )
    elif sid == "gann_numerology":
        ns = row.get("nearest_support") if isinstance(row.get("nearest_support"), dict) else {}
        nr = row.get("nearest_resistance") if isinstance(row.get("nearest_resistance"), dict) else {}
        vib = row.get("date_vibration") if isinstance(row.get("date_vibration"), dict) else {}
        relate = (
            f"Square-of-9 magnets: support {ns.get('price', '—')} · resistance {nr.get('price', '—')}. "
            f"Date vibration {vib.get('vibration', '—')} — {vib.get('note', '')}. "
            "Use levels like VP nodes; vibration only nudges attention."
        )
        if bias == "BUY":
            action = (
                f"Price is hugging Square-of-9 support with a constructive day number (conf ~{conf_s}). "
                "Buy only on bounce confirmation; SL under the Gann level."
            )
        elif bias == "SELL":
            action = (
                f"Price is hugging Square-of-9 resistance with a caution day number (conf ~{conf_s}). "
                "Sell strength only with rejection; SL above the level."
            )
        else:
            action = (
                "Mark the Square-of-9 levels on the chart and wait for a touch + reaction. "
                "No forced trade from numerology alone."
            )
    elif sid == "eclipse_nodes":
        now = row.get("now") if isinstance(row.get("now"), dict) else {}
        st = row.get("stats_eclipse_windows") if isinstance(row.get("stats_eclipse_windows"), dict) else {}
        relate = (
            f"Moon–node orb {now.get('moon_node_orb_deg', '—')}° "
            f"({'near Rahu–Ketu axis' if now.get('near_rahu_ketu_axis') else 'clear of axis'}). "
            f"Around eclipse proxies: avg range {st.get('avg_range_pct', '—')}% "
            f"(n={st.get('samples', 0)}). Eclipse season = regime noise for many desks."
        )
        action = (
            "Inside an eclipse / node window: shrink size, avoid new breakout chases, favor hedges or waits. "
            "Outside: diary the next proxy date — no trade from the axis alone."
        )
    else:
        relate = plain or "Timing overlay for markets — confirm with charts."
        action = f"Suggested stance: {_action_verb(bias)} (confidence {conf_s}). Always confirm with TA."

    if plain and sid not in ("bhadra_timing",):  # keep relate primary; append brief desk note
        relate = f"{relate} Desk note: {plain[:280]}{'…' if len(plain) > 280 else ''}"

    sl = trade.get("sl_pct")
    tp = trade.get("tp_pct")
    risk_note = ""
    if sl is not None or tp is not None:
        risk_note = f" Suggested risk map: SL {sl if sl is not None else '—'}% · TP {tp if tp is not None else '—'}%."

    summary = (
        f"{label}: {_action_verb(bias)} (conf {conf_s}). "
        f"{action.split('.')[0].strip()}."
        f"{risk_note}"
    )

    layman = {
        "what_this_means": intro,
        "how_it_relates_to_trading": relate,
        "what_action_to_take": action + risk_note,
        "suggested_stance": _action_verb(bias),
        "confidence_pct": conf,
        "summary": summary,
    }
    row["layman"] = layman
    # Keep prediction.plain_english readable; also mirror a short trader action line
    if isinstance(pred, dict):
        pred = dict(pred)
        pred["layman_summary"] = summary
        pred["action_for_trader"] = action + risk_note
        row["prediction"] = pred
    return row


def _run_one_strategy(
    strategy: str,
    tickers: list[str],
    *,
    asset_class: str,
    market: str,
    cfg: AstroFinanceConfig,
    groww_token: str,
    exchange: str,
) -> list[dict[str, Any]]:
    if strategy == "trading_calendar":
        return [enrich_with_layman(analyze_trading_calendar(asset_class, cfg=cfg))]
    if strategy == "tithi_panchang":
        return [enrich_with_layman(analyze_tithi_panchang(asset_class, cfg=cfg))]
    if strategy == "nakshatra_timing":
        # Calendar always; optionally enrich first ticker for LTP context
        t0 = next((t for t in tickers if t), None)
        return [enrich_with_layman(analyze_nakshatra_timing(
            asset_class,
            cfg=cfg,
            ticker=t0,
            market=market,
            groww_token=groww_token,
            exchange=exchange,
        ))]

    use = [t for t in tickers if t] or list(DEFAULT_TICKERS.get(asset_class, ["SPY"]))
    results: list[dict[str, Any]] = []
    for t in use:
        try:
            if strategy == "lunar_cycle":
                row = analyze_lunar_cycle(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange)
            elif strategy == "amavasya_sr":
                row = analyze_amavasya_sr(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange)
            elif strategy == "bhadra_timing":
                row = analyze_bhadra_timing(
                    t, asset_class, market, cfg=cfg, groww_token=groww_token, exchange=exchange,
                )
            elif strategy == "transit_gaps":
                row = analyze_transit_gaps(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange)
            elif strategy == "mercury_retrograde":
                row = analyze_mercury_retrograde(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange)
            elif strategy == "gann_numerology":
                row = analyze_gann_numerology(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange)
            elif strategy == "eclipse_nodes":
                row = analyze_eclipse_nodes(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange)
            else:
                row = {"ticker": t, "strategy": strategy, "error": f"Unknown strategy {strategy}"}
        except Exception as exc:
            row = {"ticker": t, "strategy": strategy, "error": str(exc)[:240]}
        results.append(enrich_with_layman(row))
    return results


def scan_astro_finance(
    strategy: str | None = None,
    tickers: list[str] | None = None,
    *,
    strategies: list[str] | None = None,
    asset_class: str = "india",
    market: str = "Groww (India Stocks)",
    cfg: AstroFinanceConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    """Run one or many Astro desks. Pass ``strategies`` (preferred) or legacy ``strategy``."""
    tickers = list(tickers or [])
    selected: list[str] = []
    if strategies:
        for s in strategies:
            sid = str(s or "").strip()
            if sid in STRATEGY_IDS and sid not in selected:
                selected.append(sid)
    if strategy:
        sid = str(strategy).strip()
        if sid in STRATEGY_IDS and sid not in selected:
            selected.append(sid)
    if not selected:
        selected = list(STRATEGY_IDS)

    cfg = cfg or AstroFinanceConfig()
    needs_tickers = any(s not in CALENDAR_STRATEGY_IDS for s in selected)
    use = [t for t in tickers if t]
    if needs_tickers and not use:
        use = list(DEFAULT_TICKERS.get(asset_class, ["SPY"]))

    results: list[dict[str, Any]] = []
    for sid in selected:
        cfg.strategy = sid
        results.extend(
            _run_one_strategy(
                sid,
                use,
                asset_class=asset_class,
                market=market,
                cfg=cfg,
                groww_token=groww_token,
                exchange=exchange,
            )
        )

    actionable = [r for r in results if (r.get("live") or {}).get("take_trade")]
    labels = [STRATEGY_LABELS.get(s, s) for s in selected]
    primary = selected[0] if len(selected) == 1 else "multi"
    return {
        "strategy": primary,
        "strategies": selected,
        "strategy_label": " · ".join(labels) if len(labels) > 1 else labels[0],
        "asset_class": asset_class,
        "market": market,
        "guide": GUIDE_OVERVIEW,
        "config": {
            "lookback_days": cfg.lookback_days,
            "forward_days": cfg.forward_days,
            "strong_moon_signs": cfg.strong_moon_signs,
            "strategies": selected,
        },
        "results": results,
        "entry_count": len(actionable),
        "scanned": len(use) if needs_tickers else 1,
        "default_tickers": DEFAULT_TICKERS.get(asset_class, []),
        "ai_system_prompt": ASTRO_FINANCE_AI_SYSTEM,
        "references": [
            YOUTUBE_HARSHUBH_VIJAY,
            YOUTUBE_HARSHUBH_VIKAS,
            YOUTUBE_RAHUL_BHATNAGAR,
        ],
        "disclaimer": (
            "Research / education only — not financial advice. Astrology is a timing overlay; "
            "confirm with technical analysis."
        ),
    }


def build_astro_ai_prompt(row: dict[str, Any]) -> str:
    lay = row.get("layman") if isinstance(row.get("layman"), dict) else {}
    return (
        f"Strategy={row.get('strategy')} ({row.get('strategy_label')}) Ticker={row.get('ticker')}\n"
        f"Prediction={row.get('prediction')}\n"
        f"Live={row.get('live')}\n"
        f"Layman={lay}\n"
    )
