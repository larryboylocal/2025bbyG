"""Kraken-only feature frame. Uses pandas and this terminal's own ring cache."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from shared.cache_arrays import RingCache


def features_from_candles(candles: list[dict], cache: RingCache | None = None) -> pd.DataFrame:
    frame = pd.DataFrame(candles)
    required = {"time", "open", "high", "low", "close", "volume"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"candles missing {sorted(missing)}")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["time"] = pd.to_numeric(frame["time"], errors="coerce").astype("int64")
    frame = frame.dropna(subset=["close"]).sort_values("time").reset_index(drop=True)

    store = cache if cache is not None else RingCache(capacity=max(len(frame), 1))
    for price in frame["close"].tolist():
        store.push(float(price))

    close = frame["close"]
    high = frame["high"]
    low = frame["low"]
    previous = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - previous).abs(), (low - previous).abs()],
        axis=1,
    ).max(axis=1)
    frame["atr"] = true_range.rolling(14, min_periods=14).mean()
    ema_fast = close.ewm(span=8, adjust=False).mean()
    ema_slow = close.ewm(span=21, adjust=False).mean()
    frame["ema_diff"] = ema_fast - ema_slow
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).rolling(14, min_periods=14).mean()
    relative = gain / loss.where(loss != 0)
    frame["rsi"] = 100 - (100 / (1 + relative))
    frame["roc"] = close.pct_change(5)
    frame["spread"] = (high - low) / close.where(close != 0)
    frame.attrs["cache_len"] = len(store)
    return frame
