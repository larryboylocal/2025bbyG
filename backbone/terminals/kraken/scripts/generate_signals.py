"""Kraken-only live signals. Causal: the label column is never read."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_KRAKEN = Path(__file__).resolve().parents[1]
if str(_KRAKEN) not in sys.path:
    sys.path.insert(0, str(_KRAKEN))

from schema import SCHEMA_NAME, validate_signal


def signals_from_features(frame: pd.DataFrame, symbol: str, timeframe: str = "1m") -> list[dict]:
    rows: list[dict] = []
    for record in frame.itertuples(index=False):
        atr = getattr(record, "atr")
        rsi = getattr(record, "rsi")
        ema_diff = getattr(record, "ema_diff")
        close = float(record.close)
        if pd.isna(atr) or pd.isna(rsi) or pd.isna(ema_diff) or close == 0:
            continue
        side = "buy" if float(ema_diff) >= 0 else "sell"
        confidence = min(0.99, max(0.01, abs(float(ema_diff)) / abs(close)))
        body = {
            "schema": SCHEMA_NAME,
            "symbol": symbol,
            "side": side,
            "orderType": "mkt",
            "size_mode": "full_margin",
            "timeframe": timeframe,
            "reduceOnly": False,
            "bar_time": int(record.time),
            "confidence": confidence,
        }
        rows.append(validate_signal(body))
    if not rows:
        raise RuntimeError("no Kraken signals after warmup")
    return rows
