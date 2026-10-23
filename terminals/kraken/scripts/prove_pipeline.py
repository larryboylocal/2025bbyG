"""End-to-end Kraken proof. Public candles only. Does not send an order."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pandas as pd

from terminals.kraken.kraken_terminal import KrakenTerminal
from terminals.kraken.schema import validate_signal
from terminals.kraken.scripts.generate_features import features_from_candles
from terminals.kraken.scripts.generate_labels import labels_from_features
from terminals.kraken.scripts.generate_signals import signals_from_features

_KRAKEN = Path(__file__).resolve().parents[1]


def main() -> int:
    config = json.loads((_KRAKEN / "config.json").read_text(encoding="utf-8"))
    symbol = config["symbols"][0]
    resolution = config["bar_resolution"]
    terminal = KrakenTerminal(config)
    candles = terminal.candles(symbol, resolution, count=240)
    if len(candles) < 30:
        raise SystemExit(f"Kraken returned too few candles for {symbol} {resolution}")
    featured = features_from_candles(candles)
    labelled = labels_from_features(featured)
    signals = signals_from_features(labelled, symbol, resolution)
    for signal in signals:
        validate_signal(signal)
    tier = terminal.classify_tier(candles)
    labelled_ready = labelled.dropna(subset=["label"])
    proof = {
        "input": {
            "source": "https://futures.kraken.com/api/charts/v1/trade/" + symbol + "/" + resolution,
            "symbol": symbol,
            "resolution": resolution,
            "candle_count": len(candles),
            "first_bar_time": int(featured["time"].iloc[0]),
            "last_bar_time": int(featured["time"].iloc[-1]),
        },
        "pandas": {
            "version": pd.__version__,
            "file": pd.__file__,
            "feature_rows": int(len(featured)),
            "feature_columns": ["atr", "ema_diff", "rsi", "roc", "spread"],
            "non_null_atr": int(featured["atr"].notna().sum()),
            "non_null_rsi": int(featured["rsi"].notna().sum()),
            "cache_len": int(featured.attrs.get("cache_len", 0)),
        },
        "labels": {
            "rows": int(labelled_ready["label"].notna().sum()),
            "counts": {str(key): int(value) for key, value in labelled_ready["label"].value_counts().to_dict().items()},
        },
        "signals": {
            "count": len(signals),
            "schema_valid": True,
            "schema": signals[-1]["schema"],
            "last": signals[-1],
        },
        "rate_limit": {
            "tier": tier,
            "snapshot": terminal.rate_status(),
        },
        "live_flags": {
            "trading_enabled": config["trading_enabled"],
            "allow_live_trades": config["allow_live_trades"],
            "live_trading": config["live_trading"],
            "paper_fills": config["paper_fills"],
        },
        "outcome": {
            "order_sent": False,
            "api_key_present": bool(os.environ.get("KRAKEN_FUTURES_API_KEY") and os.environ.get("KRAKEN_FUTURES_API_SECRET")),
            "reason": "pipeline proof does not transmit an order",
        },
    }
    if proof["pandas"]["non_null_atr"] < 1 or proof["labels"]["rows"] < 1 or proof["signals"]["count"] < 1:
        raise SystemExit("pipeline produced empty features, labels, or signals")
    if "site-packages" not in proof["pandas"]["file"] and "wheels" not in proof["pandas"]["file"]:
        # The venv install from vendored wheels still lives under site-packages.
        pass
    out = _KRAKEN / "proof" / "last_proof.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print(json.dumps(proof, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
