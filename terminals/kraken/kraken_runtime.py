"""Kraken futures runtime on 127.0.0.1:8080.

Live flags are on. Orders are sent only when API keys are present and the
eval guard allows the cycle. This process does not paper-fill.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .kraken_terminal import KrakenTerminal
from .schema import validate_signal

ROOT = Path(__file__).resolve().parent


def load_config() -> dict:
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def build_terminal(config: dict | None = None) -> KrakenTerminal:
    config = config or load_config()
    return KrakenTerminal(
        config,
        api_key=os.environ.get("KRAKEN_FUTURES_API_KEY", ""),
        api_secret=os.environ.get("KRAKEN_FUTURES_API_SECRET", ""),
    )


def self_check() -> dict:
    """Offline check: flags, tiers, schema. Does not send an order."""
    config = load_config()
    flags = {
        "trading_enabled": config["trading_enabled"],
        "allow_live_trades": config["allow_live_trades"],
        "live_trading": config["live_trading"],
        "paper_fills": config["paper_fills"],
    }
    if flags["trading_enabled"] is not True or flags["allow_live_trades"] is not True or flags["live_trading"] is not True or flags["paper_fills"] is not False:
        raise SystemExit("Kraken live flags are not aligned")
    terminal = build_terminal(config)
    quiet = [
        {"time": index, "open": 100, "high": 100.01, "low": 99.99, "close": 100, "volume": 1}
        for index in range(40)
    ]
    loud = []
    price = 100.0
    for index in range(40):
        price += 2 if index % 2 == 0 else -1.2
        loud.append(
            {
                "time": index,
                "open": price,
                "high": price + 3,
                "low": price - 3,
                "close": price,
                "volume": 1000,
            }
        )
    low = terminal.classify_tier(quiet, now_utc=_hour(12))
    high = terminal.classify_tier(loud, now_utc=_hour(12))
    if low["tier"] != "low_volatility" or high["tier"] != "high_volatility":
        raise SystemExit(f"tier switch failed: {low} {high}")
    low_ceiling = terminal.rate_status()["ceiling_cost"]
    terminal.classify_tier(quiet, now_utc=_hour(12))
    high_status_ceiling = KrakenTerminal(config).budget
    high_status_ceiling.set_tier("high_volatility", "high_volatility")
    if abs(low_ceiling - 500 * 0.8888) > 1e-6:
        raise SystemExit(f"high tier ceiling drifted: {low_ceiling}")
    if abs(high_status_ceiling._ceiling_unlocked() - 500 * 0.8888) > 1e-6:
        raise SystemExit("high tier fraction drifted")
    terminal.classify_tier(quiet, now_utc=_hour(12))
    if abs(terminal.rate_status()["ceiling_cost"] - 500 * 0.66) > 1e-6:
        raise SystemExit("low tier ceiling drifted")
    signal = validate_signal(
        {
            "schema": "fxjefe.kraken.futures.v1",
            "symbol": "PF_XBTUSD",
            "side": "buy",
            "orderType": "mkt",
            "size_mode": "full_margin",
            "timeframe": "1m",
            "reduceOnly": False,
            "bar_time": 1,
            "confidence": 0.5,
        }
    )
    report = {
        "self_check": "pass",
        "flags": flags,
        "low_tier": low,
        "high_tier": high,
        "schema": signal["schema"],
        "order_sent": False,
    }
    print(json.dumps(report))
    return report


def _hour(hour: int):
    import time

    return time.gmtime(hour * 3600)


def build_handler(terminal: KrakenTerminal) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path.split("?", 1)[0] != "/health":
                self.send_error(404)
                return
            body = json.dumps(
                {
                    "terminal": "kraken",
                    "trading_enabled": True,
                    "allow_live_trades": True,
                    "live_trading": True,
                    "api_key_present": bool(terminal.api_key and terminal.api_secret),
                    "rate_limit": terminal.rate_status(),
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return Handler


def serve() -> None:
    config = load_config()
    terminal = build_terminal(config)
    server = ThreadingHTTPServer(
        (config["runtime_host"], int(config["runtime_port"])),
        build_handler(terminal),
    )
    server.serve_forever()


if __name__ == "__main__":
    import sys

    if "--self-check" in sys.argv:
        self_check()
    else:
        serve()
