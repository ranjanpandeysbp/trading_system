"""
chart_image_digitizer.py
------------------------
Turn a candlestick / line chart screenshot into a scale-invariant close path
(``shape_pct``) for Pattern Analogue image mode.

Uses Gemini vision (preferred) when an API key is available. Falls back to a
lightweight OpenCV-free heuristic on the decoded raster (Pillow).
"""

from __future__ import annotations

import base64
import io
import json
import re
from typing import Any

import numpy as np

_MAX_IMAGE_BYTES = 6 * 1024 * 1024  # 6 MB decoded


def _strip_data_url(raw: str) -> tuple[bytes, str]:
    text = (raw or "").strip()
    mime = "image/png"
    if text.startswith("data:"):
        # data:image/png;base64,....
        header, _, b64 = text.partition(",")
        m = re.search(r"data:([^;]+)", header)
        if m:
            mime = m.group(1).strip() or mime
        text = b64
    try:
        data = base64.b64decode(text, validate=False)
    except Exception as exc:
        raise ValueError(f"Invalid base64 image: {exc}") from exc
    if not data:
        raise ValueError("Empty chart image")
    if len(data) > _MAX_IMAGE_BYTES:
        raise ValueError(f"Chart image too large (max {_MAX_IMAGE_BYTES // (1024 * 1024)} MB)")
    return data, mime


def _resample_shape(values: list[float], n: int) -> list[float]:
    """Linearly resample a path to exactly ``n`` points; force first to 0."""
    arr = np.asarray([float(v) for v in values if np.isfinite(float(v))], dtype=float)
    if len(arr) == 0:
        raise ValueError("No usable shape points from chart image")
    n = max(5, int(n))
    if len(arr) == 1:
        out = np.zeros(n, dtype=float)
    elif len(arr) == n:
        out = arr.copy()
    else:
        x_old = np.linspace(0.0, 1.0, len(arr))
        x_new = np.linspace(0.0, 1.0, n)
        out = np.interp(x_new, x_old, arr)
    out = out - out[0]
    return [round(float(v), 4) for v in out]


def _parse_shape_json(text: str) -> list[float]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Vision model returned empty digitization")
    # Prefer fenced JSON
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    # Or first {...} blob
    if not raw.startswith("{"):
        brace = re.search(r"\{[\s\S]*\}", raw)
        if brace:
            raw = brace.group(0)
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        # Last resort: list of numbers
        nums = re.findall(r"-?\d+(?:\.\d+)?", text)
        if len(nums) >= 5:
            return [float(x) for x in nums]
        raise ValueError(f"Could not parse digitization JSON: {exc}") from exc

    if isinstance(obj, list):
        return [float(x) for x in obj]
    if not isinstance(obj, dict):
        raise ValueError("Digitization JSON must be an object or array")

    for key in ("shape_pct", "closes_pct", "relative_closes_pct", "path_pct", "values"):
        v = obj.get(key)
        if isinstance(v, list) and len(v) >= 3:
            return [float(x) for x in v]

    closes = obj.get("closes") or obj.get("close")
    if isinstance(closes, list) and len(closes) >= 3:
        base = float(closes[0])
        if abs(base) < 1e-12:
            raise ValueError("Digitized closes start at zero")
        return [(float(c) / base - 1.0) * 100.0 for c in closes]

    raise ValueError("Digitization JSON missing shape_pct / closes")


def _digitize_with_gemini(
    image_bytes: bytes,
    mime: str,
    *,
    pattern_bars: int,
    api_key: str,
    model: str,
) -> tuple[list[float], str]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    prompt = (
        "You are a precise chart digitizer for financial candlestick or line charts. "
        "Extract the MAIN price series close path visible in the image "
        "(use candle closes if candlesticks; otherwise the plotted line). "
        f"Return exactly about {pattern_bars} evenly spaced samples across the visible chart "
        "(resample/interpolate if needed). "
        "Express each point as percent change from the FIRST sample (first must be 0). "
        "Ignore volume panes, indicators, logos, and UI chrome. "
        "Reply with ONLY valid JSON, no markdown:\n"
        '{"shape_pct":[0, ...], "bars_estimated":N, "notes":"short"}\n'
    )
    parts = [
        types.Part.from_bytes(data=image_bytes, mime_type=mime or "image/png"),
        prompt,
    ]
    resp = client.models.generate_content(
        model=(model or "").strip() or "gemini-2.0-flash",
        contents=parts,
    )
    text = (getattr(resp, "text", None) or "").strip()
    shape = _parse_shape_json(text)
    return shape, "gemini_vision"


def _digitize_heuristic(image_bytes: bytes, pattern_bars: int) -> tuple[list[float], str]:
    """Rough line/candlestick midline from raster luminance (no OpenCV)."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError(
            "Could not digitize chart image without AI (install Pillow) and Gemini API key failed / missing"
        ) from exc

    img = Image.open(io.BytesIO(image_bytes)).convert("L")
    # Downscale for speed
    max_w = 640
    if img.width > max_w:
        ratio = max_w / float(img.width)
        img = img.resize((max_w, max(40, int(img.height * ratio))), Image.Resampling.BILINEAR)

    arr = np.asarray(img, dtype=np.float64)
    h, w = arr.shape
    # Crop margins (axes / chrome)
    y0, y1 = int(h * 0.08), int(h * 0.78)
    x0, x1 = int(w * 0.08), int(w * 0.96)
    crop = arr[y0:y1, x0:x1]
    ch, cw = crop.shape
    if ch < 20 or cw < 40:
        raise ValueError("Chart image too small after crop")

    # Ink = darker than local background (typical white charts)
    # Also try inverted for dark themes
    def _trace(frame: np.ndarray) -> np.ndarray:
        thr = float(np.percentile(frame, 35))
        ink = frame < thr
        ys = []
        for col in range(frame.shape[1]):
            rows = np.where(ink[:, col])[0]
            if len(rows) == 0:
                ys.append(np.nan)
            else:
                ys.append(float(np.median(rows)))
        return np.asarray(ys, dtype=float)

    path = _trace(crop)
    if np.isnan(path).mean() > 0.55:
        path = _trace(255.0 - crop)
    # Fill gaps
    idx = np.arange(len(path))
    good = np.isfinite(path)
    if good.sum() < max(10, len(path) // 5):
        raise ValueError("Could not trace price path from chart image — try Gemini (set API key) or a cleaner screenshot")
    path = np.interp(idx, idx[good], path[good])
    # Image y grows downward → invert so up moves are positive
    path = -path
    # Convert to % from first
    base = float(path[0])
    # Use relative pixel move scaled — absolute scale does not matter for z-score shape
    rel = path - base
    # Map to a pseudo-% so resampling works; amplitude cancelled by z-score later
    scale = max(1.0, float(np.std(rel)) or 1.0)
    shape = (rel / scale) * 5.0  # arbitrary but stable
    return _resample_shape(shape.tolist(), pattern_bars), "heuristic_raster"


def digitize_chart_image(
    image_b64: str,
    *,
    pattern_bars: int = 20,
    gemini_api_key: str | None = None,
    gemini_model: str | None = None,
) -> dict[str, Any]:
    """
    Digitize a chart screenshot into ``shape_pct`` of length ``pattern_bars``.

    Returns dict with keys: shape_pct, engine, mime, bars, notes/error.
    """
    pb = max(5, min(120, int(pattern_bars)))
    image_bytes, mime = _strip_data_url(image_b64)
    engine = ""
    notes = ""
    shape: list[float] | None = None
    err: str | None = None

    key = (gemini_api_key or "").strip()
    if key:
        try:
            shape, engine = _digitize_with_gemini(
                image_bytes,
                mime,
                pattern_bars=pb,
                api_key=key,
                model=(gemini_model or "gemini-2.0-flash"),
            )
            shape = _resample_shape(shape, pb)
            notes = "Digitized via Gemini vision"
        except Exception as exc:
            err = f"Gemini digitization failed: {exc}"

    if shape is None:
        try:
            shape, engine = _digitize_heuristic(image_bytes, pb)
            notes = (notes + "; " if notes else "") + "Heuristic raster fallback"
            err = None
        except Exception as exc:
            msg = str(exc)
            if err:
                raise ValueError(f"{err}. Fallback also failed: {msg}") from exc
            raise ValueError(msg) from exc

    assert shape is not None
    net = float(shape[-1]) if shape else 0.0
    return {
        "shape_pct": shape,
        "bars": len(shape),
        "net_return_pct": round(net, 3),
        "engine": engine,
        "mime": mime,
        "notes": notes or None,
        "error": err,
    }
