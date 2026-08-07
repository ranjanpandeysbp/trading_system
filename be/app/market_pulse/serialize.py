"""Serialize market pulse payloads for JSON API responses."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd


def json_safe(value: Any, *, _root: bool = True) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return json_safe(value.item(), _root=False)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, dict):
        out = {str(k): json_safe(v, _root=False) for k, v in value.items()}
        if _root:
            from app.market_pulse.data_source_ctx import attach_data_source

            out = attach_data_source(out)
        return out
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v, _root=False) for v in value]
    if isinstance(value, pd.DataFrame):
        return json_safe(value.to_dict(orient="records"), _root=False)
    if isinstance(value, pd.Series):
        return json_safe(value.to_dict(), _root=False)
    return str(value)
