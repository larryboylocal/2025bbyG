"""Binance-only signals."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_BINANCE = Path(__file__).resolve().parents[1]
if str(_BINANCE) not in sys.path:
    sys.path.insert(0, str(_BINANCE))

from schema import validate_signal


def signals_from_features(frame: pd.DataFrame, symbol: str = "BTCUSDT") -> list[dict]:
    rows = []
    for record in frame.itertuples(index=False):
        bias = getattr(record, "binance_bias")
        if pd.isna(bias):
            continue
        body = {
            "schema": "fxjefe.binance.v1",
            "symbol": symbol,
            "side": "BUY" if float(bias) >= 0 else "SELL",
            "orderType": "MARKET",
            "bar_time": int(record.time),
        }
        rows.append(validate_signal(body))
    return rows
