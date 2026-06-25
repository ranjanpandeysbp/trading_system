"""India Market Pulse engines (ported from truebacktesting)."""

from app.market_pulse.cache_utils import attach_clear_stubs

try:
    import app.market_pulse.news_scanner as _news_scanner

    attach_clear_stubs(_news_scanner)
except Exception:
    pass
