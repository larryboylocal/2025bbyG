"""Kraken-only labels. Next-bar direction is an offline label, not a live input."""

from __future__ import annotations

import pandas as pd


def labels_from_features(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    future = out["close"].shift(-1)
    change = future - out["close"]
    out["future_return"] = change / out["close"].where(out["close"] != 0)
    out["label"] = pd.Series(pd.NA, index=out.index, dtype="object")
    out.loc[change > 0, "label"] = "buy"
    out.loc[change < 0, "label"] = "sell"
    out.loc[change == 0, "label"] = "buy"
    return out
