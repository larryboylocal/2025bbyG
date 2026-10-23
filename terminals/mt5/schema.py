"""MetaTrader 5 signal schema. Separate from Kraken and Binance."""

from __future__ import annotations

SCHEMA_NAME = "fxjefe.saturn.v1"
REQUIRED = ("schema", "symbol", "signal", "timeframe", "confidence")


class SchemaError(ValueError):
    pass


def validate_signal(body: dict) -> dict:
    if not isinstance(body, dict):
        raise SchemaError("signal must be an object")
    missing = [key for key in REQUIRED if key not in body]
    if missing:
        raise SchemaError(f"missing fields: {', '.join(missing)}")
    if body["schema"] != SCHEMA_NAME:
        raise SchemaError(f"schema must be {SCHEMA_NAME}")
    if body["signal"] not in ("buy", "sell", "hold"):
        raise SchemaError("MT5 signal must be buy, sell, or hold")
    if body["timeframe"] != "M15":
        raise SchemaError("MT5 timeframe must be M15")
    confidence = body["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise SchemaError("confidence must be a number")
    if not 0 <= float(confidence) <= 1:
        raise SchemaError("confidence out of range")
    return body
