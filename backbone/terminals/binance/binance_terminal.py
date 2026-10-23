"""Binance terminal. Its order path cannot go live."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .schema import SCHEMA_NAME


class LiveTradingDisabled(RuntimeError):
    pass


class BinanceTerminal:
    LIVE_TRADING = False

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._reject_live_config()

    def _reject_live_config(self) -> None:
        if any(self.config.get(flag) is True for flag in ("trading_enabled", "allow_live_trades", "live_trading")):
            raise LiveTradingDisabled("Binance live trading stays off")

    @staticmethod
    def sign(secret: str, query: str) -> str:
        """Binance HMAC-SHA256 of the query string. Not the Kraken futures signature."""
        return hmac.new(secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()

    def signed_query(self, secret: str, params: dict[str, Any]) -> str:
        query = urlencode(params)
        return f"{query}&signature={self.sign(secret, query)}"

    def place_order(self, **_kwargs: Any) -> dict[str, Any]:
        raise LiveTradingDisabled("Binance terminal refuses live orders")

    def health(self) -> dict[str, Any]:
        return {
            "terminal": "binance",
            "schema": SCHEMA_NAME,
            "trading_enabled": False,
            "allow_live_trades": False,
            "live_trading": False,
        }


def load_config() -> dict[str, Any]:
    path = Path(__file__).resolve().parent / "config.json"
    return json.loads(path.read_text(encoding="utf-8"))
