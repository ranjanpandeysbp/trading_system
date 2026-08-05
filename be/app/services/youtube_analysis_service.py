"""YouTube channel scan — list videos via Data API for all channels/dates, transcripts via Gemini YouTube URL."""

from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

YOUTUBE_AI_VIEW_SOURCE = "youtube_ai_view"

_CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_VIDEO_URL_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?.*?v=|shorts/|embed/|live/)|youtu\.be/)([A-Za-z0-9_-]{11})",
    re.I,
)

TRANSCRIPT_PROMPT = """Act as a precise transcriber for this YouTube video.

Return ONLY the spoken transcript as plain continuous text (no timestamps, no speaker labels unless essential, no markdown headers, no summary).

If the video has no usable speech or cannot be accessed, reply with exactly: NO_TRANSCRIPT
"""

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


def _split_list_items(raw: list[str] | str) -> list[str]:
    if isinstance(raw, str):
        parts = re.split(r"[\n,;]+", raw)
    else:
        parts = []
        for item in raw:
            parts.extend(re.split(r"[\n,;]+", str(item)))
    return [p.strip() for p in parts if p and p.strip()]


def parse_channel_ids(raw: list[str] | str) -> list[str]:
    """Parse every channel ID / @handle the user mentioned (deduped, order preserved)."""
    out: list[str] = []
    seen: set[str] = set()
    for p in _split_list_items(raw):
        nid = _normalize_channel_id(p)
        if not nid or nid in seen:
            continue
        seen.add(nid)
        out.append(nid)
    return out


def parse_video_ids(raw: list[str] | str) -> list[str]:
    """Parse YouTube video URLs or 11-char IDs (comma / newline / semicolon separated)."""
    out: list[str] = []
    seen: set[str] = set()
    for p in _split_list_items(raw):
        vid: str | None = None
        m = _VIDEO_URL_RE.search(p)
        if m:
            vid = m.group(1)
        elif _VIDEO_ID_RE.match(p):
            vid = p
        else:
            # bare watch URL query edge cases
            m2 = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", p)
            if m2:
                vid = m2.group(1)
        if not vid or vid in seen:
            continue
        seen.add(vid)
        out.append(vid)
    return out


def _fetch_videos_by_ids(youtube, video_ids: list[str]) -> list[dict[str, Any]]:
    """Resolve metadata for explicit video IDs via videos.list (chunks of 50)."""
    videos: list[dict[str, Any]] = []
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i : i + 50]
        resp = youtube.videos().list(part="snippet", id=",".join(chunk)).execute()
        found: dict[str, dict[str, Any]] = {}
        for item in resp.get("items") or []:
            vid = item.get("id")
            sn = item.get("snippet") or {}
            if not vid:
                continue
            published = str(sn.get("publishedAt") or "")[:10]
            found[vid] = {
                "video_id": vid,
                "title": sn.get("title") or vid,
                "channel_id": sn.get("channelId") or "unknown",
                "channel_title": sn.get("channelTitle") or sn.get("channelId") or "Unknown",
                "published_at": sn.get("publishedAt"),
                "published_date": published,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "description": (sn.get("description") or "")[:400],
            }
        for vid in chunk:
            if vid in found:
                videos.append(found[vid])
            else:
                videos.append({
                    "video_id": vid,
                    "title": vid,
                    "channel_id": "unknown",
                    "channel_title": "Unknown",
                    "published_at": None,
                    "published_date": "unknown",
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "description": "",
                    "metadata_error": "Video not found or unavailable via Data API",
                })
    return videos


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
    """Fetch all videos for this channel in [published_after, published_before), up to max_results."""
    videos: list[dict[str, Any]] = []
    page_token: str | None = None
    try:
        while len(videos) < max_results:
            batch = min(50, max_results - len(videos))
            kwargs: dict[str, Any] = {
                "part": "snippet",
                "channelId": channel_id,
                "publishedAfter": published_after,
                "publishedBefore": published_before,
                "maxResults": batch,
                "order": "date",
                "type": "video",
            }
            if page_token:
                kwargs["pageToken"] = page_token
            response = youtube.search().list(**kwargs).execute()
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
            page_token = response.get("nextPageToken")
            if not page_token:
                break
    except HttpError as exc:
        logger.warning("YouTube search failed for %s: %s", channel_id, exc)
        raise
    return videos


def _extract_transcript_gemini(
    youtube_url: str,
    *,
    gemini_api_key: str,
    gemini_model: str,
) -> tuple[str | None, str | None]:
    """Use Gemini FileData(file_uri=YouTube URL) to obtain a transcript."""
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return None, "google-genai not installed. Run: pip install google-genai"

    model = (gemini_model or "").strip() or "gemini-2.0-flash"
    try:
        client = genai.Client(api_key=gemini_api_key)
        response = client.models.generate_content(
            model=model,
            contents=types.Content(
                parts=[
                    types.Part(text=TRANSCRIPT_PROMPT),
                    types.Part(file_data=types.FileData(file_uri=youtube_url)),
                ]
            ),
        )
        text = (response.text or "").strip()
        if not text or text.upper().startswith("NO_TRANSCRIPT"):
            return None, "Gemini returned no usable transcript (private/unlisted/unavailable?)."
        return text, None
    except Exception as exc:
        logger.info("Gemini YouTube transcript failed for %s: %s", youtube_url, exc)
        err = str(exc)
        if len(err) > 280:
            err = err[:280] + "…"
        return None, f"Gemini transcript error: {err}"


def _enrich_videos_with_transcripts(
    all_videos: list[dict[str, Any]],
    *,
    gemini_api_key: str,
    gemini_model: str,
) -> list[dict[str, Any]]:
    if not all_videos:
        return all_videos

    # Keep concurrency low — Gemini YouTube processing is heavy / rate-limited
    workers = min(2, len(all_videos))

    def _job(v: dict[str, Any]) -> dict[str, Any]:
        text, err = _extract_transcript_gemini(
            v["url"],
            gemini_api_key=gemini_api_key,
            gemini_model=gemini_model,
        )
        out = dict(v)
        out["transcript"] = text
        out["transcript_error"] = err
        out["transcript_chars"] = len(text) if text else 0
        out["transcript_engine"] = "gemini"
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
                base["transcript_engine"] = "gemini"
                enriched.append(base)
    return enriched


def _apply_transcripts(
    all_videos: list[dict[str, Any]],
    *,
    fetch_transcripts: bool,
    gemini_api_key: str | None,
    gemini_model: str | None,
) -> tuple[list[dict[str, Any]], str, str]:
    gkey = (gemini_api_key or os.getenv("GEMINI_API_KEY") or "").strip()
    gmodel = (gemini_model or os.getenv("MODEL_NAME") or "gemini-2.0-flash").strip()
    if fetch_transcripts and all_videos:
        if not gkey:
            for v in all_videos:
                v["transcript"] = None
                v["transcript_error"] = (
                    "Gemini API key required for transcripts. "
                    "Set it under Manage Settings or GEMINI_API_KEY env."
                )
                v["transcript_chars"] = 0
        else:
            all_videos = _enrich_videos_with_transcripts(
                all_videos,
                gemini_api_key=gkey,
                gemini_model=gmodel,
            )
    else:
        for v in all_videos:
            v.setdefault("transcript", None)
            v.setdefault("transcript_error", None if fetch_transcripts else "skipped")
            v.setdefault("transcript_chars", 0)
    return all_videos, gkey, gmodel


def _group_videos_by_channel(all_videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_channel: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for v in all_videos:
        cid = v.get("channel_id") or "unknown"
        if cid not in by_channel:
            order.append(cid)
            by_channel[cid] = {
                "channel_id": cid,
                "channel_title": v.get("channel_title") or cid,
                "dates": {},
                "video_count": 0,
                "transcript_count": 0,
            }
        bucket = by_channel[cid]
        d = v.get("published_date") or "unknown"
        bucket["dates"].setdefault(d, []).append(v)
        bucket["video_count"] += 1
        if v.get("transcript"):
            bucket["transcript_count"] += 1

    channels_out = []
    for cid in order:
        meta = by_channel[cid]
        dates_sorted = sorted(meta["dates"].keys(), reverse=True)
        channels_out.append({
            "channel_id": cid,
            "channel_title": meta["channel_title"],
            "video_count": meta["video_count"],
            "transcript_count": meta["transcript_count"],
            "days": [{"date": d, "videos": meta["dates"][d]} for d in dates_sorted],
        })
    return channels_out


def scan_videos(
    *,
    api_key: str,
    video_urls: list[str],
    from_date: date | None = None,
    to_date: date | None = None,
    fetch_transcripts: bool = True,
    gemini_api_key: str | None = None,
    gemini_model: str | None = None,
) -> dict[str, Any]:
    """
    Take an explicit list of YouTube video URLs/IDs (comma or newline separated upstream),
    optionally keep only those published in from→to, then Gemini-transcribe each.
    """
    if not (api_key or "").strip():
        return {"error": "YouTube Data API key is required."}
    video_ids = parse_video_ids(video_urls)
    if not video_ids:
        return {
            "error": "Provide at least one YouTube video URL or 11-character video ID "
            "(comma-separated or one per line).",
        }

    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date

    try:
        youtube = build("youtube", "v3", developerKey=api_key.strip(), cache_discovery=False)
    except Exception as exc:
        return {"error": f"Failed to init YouTube client: {exc}"}

    resolve_errors: list[str] = []
    try:
        all_videos = _fetch_videos_by_ids(youtube, video_ids)
    except HttpError as exc:
        return {"error": f"YouTube videos.list failed: {exc}"}
    except Exception as exc:
        return {"error": f"Failed to resolve videos: {exc}"}

    for v in all_videos:
        if v.get("metadata_error"):
            resolve_errors.append(f"{v['video_id']}: {v['metadata_error']}")

    skipped_date: list[str] = []
    if from_date and to_date:
        kept: list[dict[str, Any]] = []
        for v in all_videos:
            pd = v.get("published_date")
            if not pd or pd == "unknown":
                kept.append(v)  # still process if publish date unknown
                continue
            try:
                d = date.fromisoformat(pd)
            except ValueError:
                kept.append(v)
                continue
            if from_date <= d <= to_date:
                kept.append(v)
            else:
                skipped_date.append(f"{v.get('title') or v['video_id']} ({pd})")
        all_videos = kept

    all_videos, _gkey, gmodel = _apply_transcripts(
        all_videos,
        fetch_transcripts=fetch_transcripts,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
    )
    all_videos.sort(key=lambda x: str(x.get("published_at") or ""), reverse=True)
    channels_out = _group_videos_by_channel(all_videos)
    with_tx = sum(1 for v in all_videos if v.get("transcript"))

    note_bits = [
        f"{len(all_videos)} listed video(s)",
        f"{len(channels_out)} channel(s)",
        f"{with_tx} transcript(s) via Gemini ({gmodel})",
    ]
    if from_date and to_date:
        note_bits.insert(1, f"in {from_date} → {to_date}")
        if skipped_date:
            note_bits.append(f"{len(skipped_date)} outside date range skipped")

    return {
        "from_date": from_date.isoformat() if from_date else None,
        "to_date": to_date.isoformat() if to_date else None,
        "mode": "videos",
        "videos_requested": video_ids,
        "resolve_errors": resolve_errors,
        "skipped_outside_date_range": skipped_date,
        "channel_errors": [],
        "video_count": len(all_videos),
        "transcript_count": with_tx,
        "transcript_engine": "gemini",
        "gemini_model": gmodel if fetch_transcripts else None,
        "channels": channels_out,
        "videos": all_videos,
        "snapshot_note": "; ".join(note_bits) + ".",
    }


def scan_channels(
    *,
    api_key: str,
    channel_ids: list[str],
    from_date: date,
    to_date: date,
    max_per_channel: int = 25,
    fetch_transcripts: bool = True,
    gemini_api_key: str | None = None,
    gemini_model: str | None = None,
) -> dict[str, Any]:
    """
    Resolve every mentioned channel, list videos in the exact from→to date window,
    then extract transcripts via Gemini YouTube URL for each video found.
    """
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
    seen_ids: set[str] = set()
    for ref in channels:
        cid, title = _resolve_channel_id(youtube, ref)
        if not cid:
            resolve_errors.append(f"Could not resolve channel: {ref}")
            continue
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        resolved.append({"channel_id": cid, "channel_title": title or cid, "input": ref})

    if not resolved:
        return {
            "error": "No valid channels resolved.",
            "resolve_errors": resolve_errors,
        }

    all_videos: list[dict[str, Any]] = []
    channel_errors: list[dict[str, str]] = []
    by_channel: dict[str, dict[str, Any]] = {
        ch["channel_id"]: {
            "channel_id": ch["channel_id"],
            "channel_title": ch["channel_title"],
            "dates": {},
            "video_count": 0,
            "transcript_count": 0,
        }
        for ch in resolved
    }

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

    all_videos, _gkey, gmodel = _apply_transcripts(
        all_videos,
        fetch_transcripts=fetch_transcripts,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
    )
    all_videos.sort(key=lambda x: str(x.get("published_at") or ""), reverse=True)

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
        bucket["dates"].setdefault(d, []).append(v)
        bucket["video_count"] += 1
        if v.get("transcript"):
            bucket["transcript_count"] += 1

    channels_out = []
    for ch in resolved:
        meta = by_channel[ch["channel_id"]]
        dates_sorted = sorted(meta["dates"].keys(), reverse=True)
        channels_out.append({
            "channel_id": ch["channel_id"],
            "channel_title": meta["channel_title"],
            "video_count": meta["video_count"],
            "transcript_count": meta["transcript_count"],
            "days": [{"date": d, "videos": meta["dates"][d]} for d in dates_sorted],
        })

    with_tx = sum(1 for v in all_videos if v.get("transcript"))
    return {
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "published_after": published_after,
        "published_before": published_before,
        "mode": "channels",
        "channels_requested": channels,
        "channels_resolved": resolved,
        "resolve_errors": resolve_errors,
        "channel_errors": channel_errors,
        "video_count": len(all_videos),
        "transcript_count": with_tx,
        "transcript_engine": "gemini",
        "gemini_model": gmodel if fetch_transcripts else None,
        "channels": channels_out,
        "videos": all_videos,
        "snapshot_note": (
            f"{len(all_videos)} video(s) across {len(channels_out)}/{len(resolved)} channel(s) "
            f"from {from_date} → {to_date}; {with_tx} transcript(s) via Gemini ({gmodel})."
        ),
    }


def build_market_ai_context(scan: dict[str, Any], *, max_chars: int = 28000) -> str:
    """Include every channel and date bucket from the scan (truncate only at the end if needed)."""
    lines = [
        "## YouTube Analysis — transcripts for market impact",
        *(
            [f"Date range: {scan.get('from_date')} → {scan.get('to_date')}"]
            if scan.get("from_date") and scan.get("to_date")
            else []
        ),
        f"Mode: {scan.get('mode') or 'channels'}",
        f"Channels: {len(scan.get('channels_resolved') or scan.get('channels') or [])}",
        f"Videos: {scan.get('video_count')} · Transcripts: {scan.get('transcript_count')}",
        "",
    ]
    for ch in scan.get("channels") or []:
        lines.append(f"### Channel: {ch.get('channel_title')} ({ch.get('channel_id')})")
        days = ch.get("days") or []
        if not days:
            lines.append("_No videos in selected date range._")
            lines.append("")
            continue
        for day in days:
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


# ---------------------------------------------------------------------------
# Saved AI Views — persists a generated market-view report (not the raw scan)
# for future reference, reusing the generic SavedBacktestReport table
# (source="youtube_ai_view") plus its own save/list/get/update/delete CRUD.
# ---------------------------------------------------------------------------

def _ai_view_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "verdict": payload.get("verdict"),
        "provider": payload.get("provider"),
        "model": payload.get("model"),
        "video_count": len(payload.get("video_urls") or []),
        "snapshot_note": payload.get("snapshot_note"),
        "report_preview": (payload.get("report") or "")[:240],
    }


async def save_youtube_ai_view(
    db: AsyncSession,
    user_id: int | None,
    *,
    name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    from app.models.db_models import SavedBacktestReport

    report = SavedBacktestReport(
        user_id=user_id,
        name=name.strip()[:200] or f"YouTube AI View {datetime.utcnow().isoformat()}",
        asset_class="global",
        tickers=",".join(payload.get("video_urls") or []),
        timeframes=f"{payload.get('from_date') or ''}..{payload.get('to_date') or ''}",
        payload_json=json.dumps(payload),
        source=YOUTUBE_AI_VIEW_SOURCE,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return {"id": report.id, "name": report.name, "created_at": report.created_at.isoformat()}


async def list_youtube_ai_views(db: AsyncSession, *, user_id: int | None) -> dict[str, Any]:
    from app.models.db_models import SavedBacktestReport

    stmt = select(SavedBacktestReport).where(SavedBacktestReport.source == YOUTUBE_AI_VIEW_SOURCE)
    if user_id is not None:
        stmt = stmt.where(SavedBacktestReport.user_id == user_id)
    stmt = stmt.order_by(SavedBacktestReport.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()

    views = []
    for r in rows:
        try:
            payload = json.loads(r.payload_json) if r.payload_json else {}
        except Exception:
            payload = {}
        views.append({
            "id": r.id,
            "name": r.name,
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            "summary": _ai_view_summary(payload if isinstance(payload, dict) else {}),
        })
    return {"ai_views": views}


async def get_youtube_ai_view(db: AsyncSession, view_id: int, *, user_id: int | None) -> dict[str, Any]:
    from app.models.db_models import SavedBacktestReport

    report = await db.get(SavedBacktestReport, view_id)
    if not report or report.source != YOUTUBE_AI_VIEW_SOURCE or (user_id is not None and report.user_id not in (None, user_id)):
        return {"error": "Saved AI View not found."}
    return {
        "id": report.id,
        "name": report.name,
        "created_at": report.created_at.isoformat(),
        "updated_at": report.updated_at.isoformat() if report.updated_at else None,
        "payload": json.loads(report.payload_json),
    }


async def update_youtube_ai_view(
    db: AsyncSession,
    view_id: int,
    *,
    user_id: int | None,
    name: str | None = None,
    report_text: str | None = None,
) -> dict[str, Any]:
    from app.models.db_models import SavedBacktestReport

    report = await db.get(SavedBacktestReport, view_id)
    if not report or report.source != YOUTUBE_AI_VIEW_SOURCE or (user_id is not None and report.user_id not in (None, user_id)):
        return {"error": "Saved AI View not found."}

    if name is not None and name.strip():
        report.name = name.strip()[:200]
    if report_text is not None:
        try:
            payload = json.loads(report.payload_json) if report.payload_json else {}
        except Exception:
            payload = {}
        payload["report"] = report_text
        payload["edited"] = True
        report.payload_json = json.dumps(payload)

    await db.commit()
    await db.refresh(report)
    return {
        "id": report.id,
        "name": report.name,
        "created_at": report.created_at.isoformat(),
        "updated_at": report.updated_at.isoformat() if report.updated_at else None,
    }


async def delete_youtube_ai_view(db: AsyncSession, view_id: int, *, user_id: int | None) -> dict[str, Any]:
    from app.models.db_models import SavedBacktestReport

    report = await db.get(SavedBacktestReport, view_id)
    if not report or report.source != YOUTUBE_AI_VIEW_SOURCE or (user_id is not None and report.user_id not in (None, user_id)):
        return {"error": "Saved AI View not found."}
    await db.delete(report)
    await db.commit()
    return {"deleted": True}
