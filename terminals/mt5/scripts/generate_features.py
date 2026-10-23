"""MetaTrader 5 feature frame. M15 columns stay in this package."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from shared.cache_arrays import RingCache


def features_from_candles(candles: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(candles)
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["close"]).reset_index(drop=True)
    cache = RingCache(capacity=max(len(frame), 1))
    for price in frame["close"].tolist():
        cache.push(float(price))
    close = frame["close"]
    frame["mt5_sma"] = close.rolling(10, min_periods=10).mean()
    frame["mt5_gap"] = close - frame["mt5_sma"]
    frame.attrs["cache_len"] = len(cache)
    return frame
