"""YouTube channel scan — latest videos in a date range + transcripts + market AI view."""

from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Any
from xml.etree import ElementTree

import requests
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from youtube_transcript_api import (
    IpBlocked,
    RequestBlocked,
    YouTubeTranscriptApi,
)
from youtube_transcript_api.formatters import TextFormatter
from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig

logger = logging.getLogger(__name__)

_CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")
_CHANNEL_URL_RE = re.compile(
    r"(?:youtube\.com/(?:channel/|c/|@)|youtu\.be/)([A-Za-z0-9_\-@]+)",
    re.I,
)

_LANG_PREF = ("en", "en-US", "en-GB", "en-IN", "hi", "a.en")

YOUTUBE_MARKET_SYSTEM = """You are a markets strategist covering Indian equities, US stocks, crypto, and global macros.
You are given YouTube video transcripts from market/finance channels for a recent date range.

Use ONLY the transcript content provided. Do not invent quotes or claims not present.

Structure your reply as:

## FINAL VERDICT
BULLISH | BEARISH | MIXED | NEUTRAL  (one word on its own line)

## Executive summary
2–4 sentences on the overall narrative across channels.

## Key themes
Bullet list of the main ideas (rates, earnings, geopolitics, sectors, crypto, etc.).

## Stock-market impact — next few days
What could move indices/sectors/tickers in the near term (1–5 sessions). Be concrete but cautious.

## Stock-market impact — next 1–2 weeks
Medium-horizon implications and what to watch.

## Risks / counterpoints
What would invalidate the view.

## Actionable watchlist (optional)
Tickers/sectors/themes mentioned — not a buy/sell order list; research only.

Be concise. Research / education only — NOT FINANCIAL ADVICE."""


def _normalize_channel_id(raw: str) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    if _CHANNEL_ID_RE.match(s):
        return s
    m = re.search(r"youtube\.com/channel/(UC[\w-]{22})", s, re.I)
    if m:
        return m.group(1)
    if s.startswith("UC") and len(s) >= 24:
        return s
    return s


def parse_channel_ids(raw: list[str] | str) -> list[str]:
    if isinstance(raw, str):
        parts = re.split(r"[\n,;]+", raw)
    else:
        parts = []
        for item in raw:
            parts.extend(re.split(r"[\n,;]+", str(item)))
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        nid = _normalize_channel_id(p)
        if not nid or nid in seen:
            continue
        seen.add(nid)
        out.append(nid)
    return out


def _rfc3339_day_start(d: date) -> str:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rfc3339_day_end_exclusive(d: date) -> str:
    nxt = d + timedelta(days=1)
    return datetime(nxt.year, nxt.month, nxt.day, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_channel_id(youtube, channel_ref: str) -> tuple[str | None, str | None]:
    ref = channel_ref.strip()
    if _CHANNEL_ID_RE.match(ref):
        try:
            resp = youtube.channels().list(part="snippet", id=ref).execute()
            items = resp.get("items") or []
            if items:
                return ref, items[0]["snippet"].get("title") or ref
            return ref, ref
        except Exception:
            return ref, ref

    handle = ref.lstrip("@")
    try:
        resp = youtube.channels().list(part="snippet", forHandle=handle).execute()
        items = resp.get("items") or []
        if items:
            return items[0]["id"], items[0]["snippet"].get("title") or handle
    except Exception as exc:
        logger.debug("forHandle resolve failed for %s: %s", ref, exc)

    try:
        resp = youtube.channels().list(part="snippet", forUsername=handle).execute()
        items = resp.get("items") or []
        if items:
            return items[0]["id"], items[0]["snippet"].get("title") or handle
    except Exception:
        pass
    return None, None


def _fetch_videos_for_channel(
    youtube,
    channel_id: str,
    *,
    published_after: str,
    published_before: str,
    max_results: int = 25,
) -> list[dict[str, Any]]:
    videos: list[dict[str, Any]] = []
    try:
        request = youtube.search().list(
            part="snippet",
            channelId=channel_id,
            publishedAfter=published_after,
            publishedBefore=published_before,
            maxResults=min(max_results, 50),
            order="date",
            type="video",
        )
        response = request.execute()
        for item in response.get("items") or []:
            vid = (item.get("id") or {}).get("videoId")
            sn = item.get("snippet") or {}
            if not vid:
                continue
            published = str(sn.get("publishedAt") or "")[:10]
            videos.append({
                "video_id": vid,
                "title": sn.get("title") or vid,
                "channel_id": channel_id,
                "channel_title": sn.get("channelTitle") or channel_id,
                "published_at": sn.get("publishedAt"),
                "published_date": published,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "description": (sn.get("description") or "")[:400],
            })
    except HttpError as exc:
        logger.warning("YouTube search failed for %s: %s", channel_id, exc)
        raise
    return videos


def build_proxy_config(
    *,
    webshare_username: str | None = None,
    webshare_password: str | None = None,
    http_proxy: str | None = None,
    https_proxy: str | None = None,
) -> WebshareProxyConfig | GenericProxyConfig | None:
    ws_user = (webshare_username or os.getenv("WEBSHARE_PROXY_USERNAME") or "").strip()
    ws_pass = (webshare_password or os.getenv("WEBSHARE_PROXY_PASSWORD") or "").strip()
    if ws_user and ws_pass:
        return WebshareProxyConfig(
            proxy_username=ws_user,
            proxy_password=ws_pass,
            retries_when_blocked=10,
        )

    http_url = (http_proxy or os.getenv("YOUTUBE_HTTP_PROXY") or os.getenv("HTTP_PROXY") or "").strip()
    https_url = (https_proxy or os.getenv("YOUTUBE_HTTPS_PROXY") or os.getenv("HTTPS_PROXY") or "").strip()
    if http_url or https_url:
        return GenericProxyConfig(http_url=http_url or None, https_url=https_url or None)
    return None


def _friendly_block_error(exc: BaseException) -> str:
    msg = str(exc)
    if (
        isinstance(exc, (IpBlocked, RequestBlocked))
        or "blocking requests from your IP" in msg
        or "IpBlocked" in msg
        or "RequestBlocked" in msg
    ):
        return (
            "YouTube blocked transcript requests from this IP (rate-limit or cloud/datacenter IP). "
            "Retries + yt-dlp fallback were tried. Configure a residential proxy "
            "(Webshare username/password or HTTP(S) proxy) under Youtube Analysis → Proxy settings, "
            "or set WEBSHARE_PROXY_USERNAME / WEBSHARE_PROXY_PASSWORD in the backend .env."
        )
    if len(msg) > 280:
        return msg[:280] + "…"
    return msg


def _is_blocked_error(exc: BaseException) -> bool:
    if isinstance(exc, (IpBlocked, RequestBlocked)):
        return True
    msg = str(exc).lower()
    return "blocking requests from your ip" in msg or "ipblocked" in msg or "requestblocked" in msg


def _extract_via_transcript_api(video_id: str, proxy_config=None) -> str:
    api = YouTubeTranscriptApi(proxy_config=proxy_config)
    languages = ("en", "en-US", "en-GB", "hi", "en-IN")
    try:
        fetched = api.fetch(video_id, languages=languages)
        text = TextFormatter().format_transcript(fetched).strip()
        if text:
            return text
    except Exception as primary:
        if _is_blocked_error(primary):
            raise
        listing = api.list(video_id)
        picked = None
        try:
            picked = listing.find_manually_created_transcript(["en", "en-US", "hi"])
        except Exception:
            try:
                picked = listing.find_generated_transcript(["en", "en-US", "hi"])
            except Exception:
                for t in listing:
                    picked = t
                    break
        if picked is None:
            raise primary
        fetched = picked.fetch()
        text = TextFormatter().format_transcript(fetched).strip()
        if not text:
            raise primary
        return text
    raise RuntimeError("Empty transcript")


def _parse_json3_events(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for ev in payload.get("events") or []:
        for seg in ev.get("segs") or []:
            t = seg.get("utf8")
            if t and t != "\n":
                parts.append(t)
        if ev.get("segs") and parts and not parts[-1].endswith((" ", "\n")):
            parts.append(" ")
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _parse_vtt_or_srv(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if text.startswith("<?xml") or text.startswith("<"):
        try:
            root = ElementTree.fromstring(text)
            bits = []
            for node in root.iter():
                if node.text and node.tag.endswith("text"):
                    bits.append(node.text)
            joined = " ".join(bits).strip()
            if joined:
                return re.sub(r"\s+", " ", joined)
        except Exception:
            pass
    lines: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("WEBVTT") or s.startswith("NOTE") or "-->" in s or s.isdigit():
            continue
        if re.match(r"^\d{2}:\d{2}", s):
            continue
        lines.append(s)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def _download_subtitle_url(url: str, proxies: dict[str, str] | None = None) -> str | None:
    try:
        resp = requests.get(
            url,
            timeout=12,
            proxies=proxies,
            headers={"User-Agent": "Mozilla/5.0 (compatible; TradingSystem/1.0)"},
        )
        if resp.status_code != 200 or not resp.text:
            return None
        ctype = (resp.headers.get("content-type") or "").lower()
        body = resp.text
        if "json" in ctype or body.lstrip().startswith("{"):
            try:
                return _parse_json3_events(json.loads(body)) or None
            except Exception:
                pass
        return _parse_vtt_or_srv(body) or None
    except Exception as exc:
        logger.debug("subtitle download failed: %s", exc)
        return None


def _extract_via_ytdlp(video_id: str, proxy_url: str | None = None) -> str | None:
    """Fallback / primary when transcript API is IP-blocked — uses yt-dlp (android client)."""
    try:
        import yt_dlp
    except ImportError:
        logger.warning("yt-dlp not installed; skipping fallback")
        return None

    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "socket_timeout": 15,
        "retries": 0,
        "fragment_retries": 0,
        # Single fast client — probing multiple clients is very slow
        "extractor_args": {"youtube": {"player_client": ["android"]}},
    }
    if proxy_url:
        ydl_opts["proxy"] = proxy_url

    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        logger.info("yt-dlp extract_info failed for %s: %s", video_id, exc)
        return None

    if not info:
        return None

    tracks: dict[str, Any] = {}
    for bucket in (info.get("subtitles") or {}, info.get("automatic_captions") or {}):
        for lang, formats in bucket.items():
            tracks.setdefault(lang, [])
            tracks[lang].extend(formats or [])

    ordered_langs: list[str] = []
    for pref in _LANG_PREF:
        for lang in tracks:
            if lang == pref or lang.startswith(pref + "-") or lang.startswith(pref + "."):
                if lang not in ordered_langs:
                    ordered_langs.append(lang)
    for lang in tracks:
        if lang not in ordered_langs:
            ordered_langs.append(lang)

    for lang in ordered_langs[:6]:  # don't walk dozens of auto-caption locales
        formats = tracks.get(lang) or []
        ranked = sorted(
            formats,
            key=lambda f: (
                0 if f.get("ext") == "json3" else
                1 if f.get("ext") == "vtt" else
                2 if str(f.get("ext", "")).startswith("srv") else 3
            ),
        )
        for fmt in ranked[:2]:
            sub_url = fmt.get("url")
            if not sub_url:
                continue
            text = _download_subtitle_url(sub_url, proxies=proxies)
            if text:
                return text
    return None


def _proxy_url_for_ytdlp(proxy_config) -> str | None:
    if proxy_config is None:
        return None
    try:
        d = proxy_config.to_requests_dict()
        return d.get("https") or d.get("http")
    except Exception:
        return None


def _extract_transcript(
    video_id: str,
    *,
    proxy_config=None,
    engine: str = "auto",
) -> tuple[str | None, str | None, str]:
    """
    Return (transcript_text, error, engine_used).
    engine: "api" | "ytdlp" | "auto"
      - api: youtube-transcript-api only (1 attempt)
      - ytdlp: yt-dlp only
      - auto: api once, then yt-dlp on failure/block
    """
    proxy_url = _proxy_url_for_ytdlp(proxy_config)
    last_err: BaseException | None = None

    if engine in ("api", "auto"):
        try:
            text = _extract_via_transcript_api(video_id, proxy_config=proxy_config)
            return text, None, "api"
        except Exception as exc:
            last_err = exc
            if engine == "api":
                return None, _friendly_block_error(exc), "api"
            # blocked / missing → fall through to yt-dlp

    if engine in ("ytdlp", "auto"):
        try:
            text = _extract_via_ytdlp(video_id, proxy_url=proxy_url)
            if text:
                return text, None, "ytdlp"
        except Exception as exc:
            last_err = last_err or exc
            logger.info("yt-dlp error for %s: %s", video_id, exc)

    return None, _friendly_block_error(last_err or RuntimeError("No transcript")), engine


def _enrich_videos_with_transcripts(
    all_videos: list[dict[str, Any]],
    *,
    proxy_config=None,
) -> tuple[list[dict[str, Any]], str]:
    """
    Fast path:
      1) Probe first video with transcript API (single attempt).
      2) If IP-blocked → use yt-dlp for ALL videos in parallel.
      3) Else → transcript API in parallel, yt-dlp only as per-video fallback.
    """
    if not all_videos:
        return all_videos, "none"

    # Probe
    probe_text, probe_err, _ = _extract_transcript(
        all_videos[0]["video_id"],
        proxy_config=proxy_config,
        engine="api",
    )
    blocked = bool(probe_err and "blocked" in probe_err.lower())
    engine = "ytdlp" if blocked else "auto"
    workers = min(4, len(all_videos))

    enriched: list[dict[str, Any]] = []
    # Keep first result if probe succeeded
    first = dict(all_videos[0])
    if probe_text:
        first["transcript"] = probe_text
        first["transcript_error"] = None
        first["transcript_chars"] = len(probe_text)
        first["transcript_engine"] = "api"
        enriched.append(first)
        rest = all_videos[1:]
    elif blocked:
        # Don't waste time retrying API on the first video either
        t2, e2, eng = _extract_transcript(
            all_videos[0]["video_id"], proxy_config=proxy_config, engine="ytdlp",
        )
        first["transcript"] = t2
        first["transcript_error"] = e2
        first["transcript_chars"] = len(t2) if t2 else 0
        first["transcript_engine"] = eng
        enriched.append(first)
        rest = all_videos[1:]
    else:
        first["transcript"] = None
        first["transcript_error"] = probe_err
        first["transcript_chars"] = 0
        first["transcript_engine"] = "api"
        enriched.append(first)
        rest = all_videos[1:]

    if not rest:
        return enriched, engine

    def _job(v: dict[str, Any]) -> dict[str, Any]:
        text, err, eng = _extract_transcript(
            v["video_id"], proxy_config=proxy_config, engine=engine,
        )
        out = dict(v)
        out["transcript"] = text
        out["transcript_error"] = err
        out["transcript_chars"] = len(text) if text else 0
        out["transcript_engine"] = eng
        return out

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_job, v): v for v in rest}
        for fut in as_completed(futs):
            try:
                enriched.append(fut.result())
            except Exception as exc:
                base = dict(futs[fut])
                base["transcript"] = None
                base["transcript_error"] = str(exc)
                base["transcript_chars"] = 0
                base["transcript_engine"] = engine
                enriched.append(base)

    return enriched, engine


def scan_channels(
    *,
    api_key: str,
    channel_ids: list[str],
    from_date: date,
    to_date: date,
    max_per_channel: int = 25,
    fetch_transcripts: bool = True,
    webshare_username: str | None = None,
    webshare_password: str | None = None,
    http_proxy: str | None = None,
    https_proxy: str | None = None,
) -> dict[str, Any]:
    if not (api_key or "").strip():
        return {"error": "YouTube Data API key is required."}
    channels = parse_channel_ids(channel_ids)
    if not channels:
        return {"error": "Provide at least one YouTube channel ID (UC…) or @handle."}
    if from_date > to_date:
        from_date, to_date = to_date, from_date

    published_after = _rfc3339_day_start(from_date)
    published_before = _rfc3339_day_end_exclusive(to_date)

    try:
        youtube = build("youtube", "v3", developerKey=api_key.strip(), cache_discovery=False)
    except Exception as exc:
        return {"error": f"Failed to init YouTube client: {exc}"}

    resolved: list[dict[str, str]] = []
    resolve_errors: list[str] = []
    for ref in channels:
        cid, title = _resolve_channel_id(youtube, ref)
        if not cid:
            resolve_errors.append(f"Could not resolve channel: {ref}")
            continue
        resolved.append({"channel_id": cid, "channel_title": title or cid, "input": ref})

    if not resolved:
        return {
            "error": "No valid channels resolved.",
            "resolve_errors": resolve_errors,
        }

    all_videos: list[dict[str, Any]] = []
    channel_errors: list[dict[str, str]] = []
    for ch in resolved:
        try:
            vids = _fetch_videos_for_channel(
                youtube,
                ch["channel_id"],
                published_after=published_after,
                published_before=published_before,
                max_results=max_per_channel,
            )
            for v in vids:
                v["channel_title"] = ch["channel_title"]
            all_videos.extend(vids)
        except HttpError as exc:
            channel_errors.append({
                "channel_id": ch["channel_id"],
                "channel_title": ch["channel_title"],
                "error": str(exc),
            })
        except Exception as exc:
            channel_errors.append({
                "channel_id": ch["channel_id"],
                "channel_title": ch["channel_title"],
                "error": str(exc),
            })

    proxy_config = build_proxy_config(
        webshare_username=webshare_username,
        webshare_password=webshare_password,
        http_proxy=http_proxy,
        https_proxy=https_proxy,
    )
    if isinstance(proxy_config, WebshareProxyConfig):
        proxy_note = "webshare"
    elif isinstance(proxy_config, GenericProxyConfig):
        proxy_note = "http(s) proxy"
    else:
        proxy_note = "none"

    # Fast transcript fetch: probe once, then parallel (switch to yt-dlp if IP-blocked)
    transcript_engine = "none"
    if fetch_transcripts and all_videos:
        all_videos, transcript_engine = _enrich_videos_with_transcripts(
            all_videos, proxy_config=proxy_config,
        )
    else:
        for v in all_videos:
            v.setdefault("transcript", None)
            v.setdefault("transcript_error", None if fetch_transcripts else "skipped")
            v.setdefault("transcript_chars", 0)

    all_videos.sort(key=lambda x: str(x.get("published_at") or ""), reverse=True)

    by_channel: dict[str, dict[str, Any]] = {}
    for v in all_videos:
        cid = v["channel_id"]
        bucket = by_channel.setdefault(cid, {
            "channel_id": cid,
            "channel_title": v.get("channel_title") or cid,
            "dates": {},
            "video_count": 0,
            "transcript_count": 0,
        })
        d = v.get("published_date") or "unknown"
        day_list = bucket["dates"].setdefault(d, [])
        day_list.append(v)
        bucket["video_count"] += 1
        if v.get("transcript"):
            bucket["transcript_count"] += 1

    channels_out = []
    for cid, meta in by_channel.items():
        dates_sorted = sorted(meta["dates"].keys(), reverse=True)
        channels_out.append({
            "channel_id": cid,
            "channel_title": meta["channel_title"],
            "video_count": meta["video_count"],
            "transcript_count": meta["transcript_count"],
            "days": [{"date": d, "videos": meta["dates"][d]} for d in dates_sorted],
        })
    channels_out.sort(key=lambda c: c["channel_title"].lower())

    with_tx = sum(1 for v in all_videos if v.get("transcript"))
    blocked = sum(
        1 for v in all_videos
        if not v.get("transcript") and v.get("transcript_error")
        and "blocked" in str(v.get("transcript_error")).lower()
    )
    return {
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "published_after": published_after,
        "published_before": published_before,
        "channels_requested": channels,
        "channels_resolved": resolved,
        "resolve_errors": resolve_errors,
        "channel_errors": channel_errors,
        "video_count": len(all_videos),
        "transcript_count": with_tx,
        "transcript_blocked_count": blocked,
        "proxy_mode": proxy_note,
        "transcript_engine": transcript_engine,
        "channels": channels_out,
        "videos": all_videos,
        "snapshot_note": (
            f"{len(all_videos)} video(s) across {len(channels_out)} channel(s) "
            f"from {from_date} → {to_date}; {with_tx} transcript(s) retrieved"
            f" (engine: {transcript_engine}, proxy: {proxy_note}"
            + (f"; {blocked} IP-blocked" if blocked else "")
            + ")."
        ),
    }


def build_market_ai_context(scan: dict[str, Any], *, max_chars: int = 13000) -> str:
    lines = [
        "## YouTube Analysis — transcripts for market impact",
        f"Date range: {scan.get('from_date')} → {scan.get('to_date')}",
        f"Videos: {scan.get('video_count')} · Transcripts: {scan.get('transcript_count')}",
        "",
    ]
    for ch in scan.get("channels") or []:
        lines.append(f"### Channel: {ch.get('channel_title')} ({ch.get('channel_id')})")
        for day in ch.get("days") or []:
            lines.append(f"#### Date: {day.get('date')}")
            for v in day.get("videos") or []:
                lines.append(f"- **{v.get('title')}** — {v.get('url')}")
                tx = (v.get("transcript") or "").strip()
                if tx:
                    chunk = tx if len(tx) <= 2500 else tx[:2500] + "…[truncated]"
                    lines.append(chunk)
                else:
                    lines.append(f"  [No transcript: {v.get('transcript_error') or 'n/a'}]")
                lines.append("")
        lines.append("")
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n…[context truncated]"
    return text
