"""Kraken futures signal schema. Not used by Binance or MetaTrader 5."""

from __future__ import annotations

SCHEMA_NAME = "fxjefe.kraken.futures.v1"

ORDER_TYPES = (
    "lmt",
    "post",
    "ioc",
    "mkt",
    "stp",
    "take_profit",
    "trailing_stop",
    "fok",
)

SIDES = ("buy", "sell")

REQUIRED = (
    "schema",
    "symbol",
    "side",
    "orderType",
    "size_mode",
    "timeframe",
    "reduceOnly",
    "bar_time",
    "confidence",
)


class SchemaError(ValueError):
    pass


def validate_signal(body: dict) -> dict:
    """Validate a Kraken futures signal. Returns the same mapping on success."""
    if not isinstance(body, dict):
        raise SchemaError("signal must be an object")
    missing = [key for key in REQUIRED if key not in body]
    if missing:
        raise SchemaError(f"missing fields: {', '.join(missing)}")
    if body["schema"] != SCHEMA_NAME:
        raise SchemaError(f"schema must be {SCHEMA_NAME}")
    symbol = str(body["symbol"])
    if not (
        symbol.startswith("PF_")
        or symbol.startswith("PI_")
        or symbol.startswith("FI_")
    ):
        raise SchemaError("symbol must be a Kraken futures instrument (PF_, PI_, FI_)")
    if body["side"] not in SIDES:
        raise SchemaError("side must be buy or sell")
    if body["orderType"] not in ORDER_TYPES:
        raise SchemaError("orderType is not a Kraken futures order type")
    size_mode = body["size_mode"]
    if size_mode != "full_margin":
        if isinstance(size_mode, bool) or not isinstance(size_mode, (int, float)):
            raise SchemaError("size_mode must be full_margin or a positive number")
        if float(size_mode) <= 0:
            raise SchemaError("numeric size_mode must be > 0")
    if not isinstance(body["reduceOnly"], bool):
        raise SchemaError("reduceOnly must be a boolean")
    if not isinstance(body["bar_time"], int):
        raise SchemaError("bar_time must be an integer millisecond timestamp")
    confidence = body["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise SchemaError("confidence must be a number")
    if not 0 < float(confidence) < 1:
        raise SchemaError("confidence must be between 0 and 1 exclusive")
    timeframe = str(body["timeframe"])
    if timeframe not in {"1m", "5m", "15m", "30m", "1h", "4h", "12h", "1d", "1w"}:
        raise SchemaError("timeframe is not a Kraken charts resolution")
    return body
