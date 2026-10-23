"""MetaTrader 5 signals. Hold is allowed here. Kraken learning mode is not."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_MT5 = Path(__file__).resolve().parents[1]
if str(_MT5) not in sys.path:
    sys.path.insert(0, str(_MT5))

from schema import validate_signal


def signals_from_features(frame: pd.DataFrame, symbol: str = "EURUSD") -> list[dict]:
    rows = []
    for record in frame.itertuples(index=False):
        gap = getattr(record, "mt5_gap")
        if pd.isna(gap):
            continue
        if abs(float(gap)) < 1e-12:
            signal = "hold"
            confidence = 0.0
        else:
            signal = "buy" if float(gap) > 0 else "sell"
            confidence = 0.8
        body = {
            "schema": "fxjefe.saturn.v1",
            "symbol": symbol,
            "signal": signal,
            "timeframe": "M15",
            "confidence": confidence,
        }
        rows.append(validate_signal(body))
    return rows
