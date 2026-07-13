from dataclasses import dataclass


@dataclass(frozen=True)
class SMCConfig:
    fractal_window: int = 2
    equilibrium_pct: float = 0.50
    ote_shallow_pct: float = 0.618
    ote_deep_pct: float = 0.786
    ote_sweet_spot_pct: float = 0.702
    displacement_atr_window: int = 14
    displacement_multiplier: float = 1.5
    min_fvg_size_pct: float = 0.0
    crt_lookback: int = 1
    htf_rule: str = "4h"
    mtf_rule: str = "1h"
    ltf_rule: str = "5min"
