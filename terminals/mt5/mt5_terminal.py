"""MetaTrader 5 terminal. Order entry stays off in this build."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import SCHEMA_NAME


class LiveTradingDisabled(RuntimeError):
    pass


class MetaTrader5Terminal:
    LIVE_TRADING = False

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        if any(config.get(flag) is True for flag in ("trading_enabled", "allow_live_trades", "live_trading")):
            raise LiveTradingDisabled("MetaTrader 5 live trading stays off")

    def order_send(self, **_kwargs: Any) -> dict[str, Any]:
        raise LiveTradingDisabled("MetaTrader 5 terminal refuses live orders")

    def health(self) -> dict[str, Any]:
        return {
            "terminal": "mt5",
            "schema": SCHEMA_NAME,
            "trading_enabled": False,
            "allow_live_trades": False,
            "live_trading": False,
            "timeframe": self.config.get("timeframe"),
        }


def load_config() -> dict[str, Any]:
    path = Path(__file__).resolve().parent / "config.json"
    return json.loads(path.read_text(encoding="utf-8"))
