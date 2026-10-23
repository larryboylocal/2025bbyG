"""Binance signal schema. Separate from Kraken and MetaTrader 5."""

from __future__ import annotations

SCHEMA_NAME = "fxjefe.binance.v1"
REQUIRED = ("schema", "symbol", "side", "orderType", "bar_time")


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
    if body["side"] not in ("BUY", "SELL"):
        raise SchemaError("Binance side must be BUY or SELL")
    if body["orderType"] not in ("LIMIT", "MARKET"):
        raise SchemaError("Binance orderType must be LIMIT or MARKET")
    if not str(body["symbol"]).endswith("USDT"):
        raise SchemaError("Binance symbol must be a USDT pair")
    if not isinstance(body["bar_time"], int):
        raise SchemaError("bar_time must be an integer")
    return body
