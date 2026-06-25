"""IST / NY session constants used by intraday and SMC engines."""

from __future__ import annotations

from datetime import time

import pandas as pd
import pytz

NY_TZ = pytz.timezone("America/New_York")
IST_TZ = pytz.timezone("Asia/Kolkata")

INDIA_MARKET_OPEN = time(9, 15)
INDIA_MARKET_CLOSE = time(15, 30)


def _ist_time_on_date(date_val: pd.Timestamp, t: time) -> pd.Timestamp:
    local = date_val.tz_convert(IST_TZ) if date_val.tzinfo else date_val.tz_localize(IST_TZ)
    day = local.normalize()
    return day + pd.Timedelta(hours=t.hour, minutes=t.minute)
