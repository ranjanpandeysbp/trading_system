"""YouTube channel scan — latest videos in a date range + transcripts + market AI view."""

from __future__ import annotations

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Any

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


def _looks_like_proxy_url(value: str) -> bool:
    v = (value or "").strip().lower()
    return v.startswith("http://") or v.startswith("https://") or v.startswith("socks")


def _normalize_proxy_url(raw: str) -> str:
    s = (raw or "").strip().rstrip("/")
    if not s:
        return ""
    if "://" not in s:
        s = "http://" + s
    return s


def build_proxy_config(
    *,
    webshare_username: str | None = None,
    webshare_password: str | None = None,
    http_proxy: str | None = None,
    https_proxy: str | None = None,
) -> WebshareProxyConfig | GenericProxyConfig | None:
    """
    Prefer an explicit HTTP(S) proxy URL (http://user:pass@host:port).
    Otherwise use Webshare rotating gateway username/password (p.webshare.io).
    """
    http_url = _normalize_proxy_url(
        http_proxy or os.getenv("YOUTUBE_HTTP_PROXY") or os.getenv("HTTP_PROXY") or ""
    )
    https_url = _normalize_proxy_url(
        https_proxy or os.getenv("YOUTUBE_HTTPS_PROXY") or os.getenv("HTTPS_PROXY") or ""
    )

    ws_user = (webshare_username or os.getenv("WEBSHARE_PROXY_USERNAME") or "").strip()
    ws_pass = (webshare_password or os.getenv("WEBSHARE_PROXY_PASSWORD") or "").strip()

    if ws_user and _looks_like_proxy_url(ws_user) and not http_url:
        http_url = _normalize_proxy_url(ws_user)

    if http_url or https_url:
        return GenericProxyConfig(
            http_url=http_url or None,
            https_url=https_url or http_url or None,
        )

    if ws_user and ws_pass and not _looks_like_proxy_url(ws_user):
        return WebshareProxyConfig(
            proxy_username=ws_user,
            proxy_password=ws_pass,
            retries_when_blocked=8,
        )
    return None


def _friendly_error(exc: BaseException) -> str:
    msg = str(exc)
    low = msg.lower()
    if (
        isinstance(exc, (IpBlocked, RequestBlocked))
        or "blocking requests from your ip" in low
        or "ipblocked" in low
        or "requestblocked" in low
    ):
        return (
            "YouTube blocked transcript requests. Configure Webshare under Proxy settings: "
            "either rotating username/password, or full HTTP proxy URL "
            "(http://user:pass@host:port)."
        )
    if len(msg) > 280:
        return msg[:280] + "…"
    return msg


def _is_blocked_error(exc: BaseException) -> bool:
    if isinstance(exc, (IpBlocked, RequestBlocked)):
        return True
    msg = str(exc).lower()
    return "blocking requests from your ip" in msg or "ipblocked" in msg or "requestblocked" in msg


def _extract_transcript(video_id: str, *, proxy_config=None) -> tuple[str | None, str | None]:
    """Fetch transcript via youtube-transcript-api only (optionally through Webshare/proxy)."""
    languages = ("en", "en-US", "en-GB", "hi", "en-IN")
    attempts = 4 if proxy_config is not None else 1
    last_exc: BaseException | None = None

    for attempt in range(attempts):
        api = YouTubeTranscriptApi(proxy_config=proxy_config)
        try:
            fetched = api.fetch(video_id, languages=languages)
            text = TextFormatter().format_transcript(fetched).strip()
            if text:
                return text, None
            raise RuntimeError("Empty transcript")
        except Exception as primary:
            last_exc = primary
            if _is_blocked_error(primary):
                if attempt < attempts - 1:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                return None, _friendly_error(primary)
            try:
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
                    return None, _friendly_error(primary)
                fetched = picked.fetch()
                text = TextFormatter().format_transcript(fetched).strip()
                if text:
                    return text, None
                return None, _friendly_error(primary)
            except Exception as secondary:
                last_exc = secondary
                if _is_blocked_error(secondary) and attempt < attempts - 1:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                return None, _friendly_error(secondary)

    return None, _friendly_error(last_exc or RuntimeError("No transcript"))


def _enrich_videos_with_transcripts(
    all_videos: list[dict[str, Any]],
    *,
    proxy_config=None,
) -> list[dict[str, Any]]:
    if not all_videos:
        return all_videos

    workers = min(4, len(all_videos))

    def _job(v: dict[str, Any]) -> dict[str, Any]:
        text, err = _extract_transcript(v["video_id"], proxy_config=proxy_config)
        out = dict(v)
        out["transcript"] = text
        out["transcript_error"] = err
        out["transcript_chars"] = len(text) if text else 0
        return out

    enriched: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_job, v): v for v in all_videos}
        for fut in as_completed(futs):
            try:
                enriched.append(fut.result())
            except Exception as exc:
                base = dict(futs[fut])
                base["transcript"] = None
                base["transcript_error"] = str(exc)
                base["transcript_chars"] = 0
                enriched.append(base)
    return enriched


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

    if fetch_transcripts and all_videos:
        all_videos = _enrich_videos_with_transcripts(all_videos, proxy_config=proxy_config)
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
        "channels": channels_out,
        "videos": all_videos,
        "snapshot_note": (
            f"{len(all_videos)} video(s) across {len(channels_out)} channel(s) "
            f"from {from_date} → {to_date}; {with_tx} transcript(s) retrieved"
            f" (proxy: {proxy_note}"
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
