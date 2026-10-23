"""Offline expectations for the Kraken build. No orders are sent."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from terminals.binance.binance_terminal import BinanceTerminal, LiveTradingDisabled as BinanceOff
from terminals.binance.binance_terminal import load_config as load_binance
from terminals.kraken.kraken_terminal import CostBudget, KrakenAPIError, KrakenTerminal, LiveEndpointError
from terminals.kraken.schema import SchemaError, validate_signal
from terminals.mt5.mt5_terminal import LiveTradingDisabled as Mt5Off
from terminals.mt5.mt5_terminal import MetaTrader5Terminal
from terminals.mt5.mt5_terminal import load_config as load_mt5

ROOT = Path(__file__).resolve().parents[1]
KRAKEN_CONFIG = json.loads((ROOT / "terminals" / "kraken" / "config.json").read_text(encoding="utf-8"))


def _candles(span: float, volume: float, count: int = 40) -> list[dict]:
    rows = []
    price = 100.0
    for index in range(count):
        price += span if index % 2 == 0 else -span / 2
        rows.append(
            {
                "time": index,
                "open": price,
                "high": price + span,
                "low": price - span,
                "close": price,
                "volume": volume,
            }
        )
    return rows


class RateTierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.terminal = KrakenTerminal(KRAKEN_CONFIG, state_path=Path(tempfile.mkdtemp()) / "session.json")

    def test_config_fractions_are_loaded(self) -> None:
        tiers = KRAKEN_CONFIG["rate_limit"]["tiers"]
        self.assertEqual(tiers["low_volatility"]["max_fraction_of_system_max"], 0.66)
        self.assertEqual(tiers["high_volatility"]["max_fraction_of_system_max"], 0.8888)
        self.assertEqual(KRAKEN_CONFIG["rate_limit"]["system_max_cost"], 500)

    def test_low_tier_stops_at_66_percent(self) -> None:
        self.terminal.classify_tier(_candles(0.01, 1), now_utc=time.gmtime(12 * 3600))
        budget = self.terminal.budget
        self.assertEqual(budget.tier, "low_volatility")
        self.assertTrue(budget.try_acquire(330))
        self.assertFalse(budget.try_acquire(10))
        self.assertLess(budget.snapshot()["used_cost"], 500)

    def test_high_tier_stops_at_8888_percent(self) -> None:
        self.terminal.classify_tier(_candles(3.0, 1000), now_utc=time.gmtime(12 * 3600))
        budget = self.terminal.budget
        self.assertEqual(budget.tier, "high_volatility")
        self.assertAlmostEqual(budget.snapshot()["ceiling_cost"], 444.4, places=4)
        self.assertTrue(budget.try_acquire(444))
        self.assertFalse(budget.try_acquire(1))
        self.assertLess(budget.snapshot()["used_cost"], budget.system_max)

    def test_bad_fraction_is_rejected(self) -> None:
        with self.assertRaises(LiveEndpointError):
            CostBudget(500, 10, 0.9, 0.8888, 10)

    def test_backoff_drops_to_low_tier(self) -> None:
        self.terminal.budget.set_tier("high_volatility", "high_volatility")
        self.terminal.budget.note_limit_hit()
        snap = self.terminal.budget.snapshot()
        self.assertEqual(snap["tier"], "low_volatility")
        self.assertTrue(snap["backoff_active"])
        self.assertFalse(self.terminal.budget.try_acquire(1))


class LiveFlagTests(unittest.TestCase):
    def test_kraken_flags_on(self) -> None:
        self.assertTrue(KRAKEN_CONFIG["trading_enabled"])
        self.assertTrue(KRAKEN_CONFIG["allow_live_trades"])
        self.assertTrue(KRAKEN_CONFIG["live_trading"])
        self.assertFalse(KRAKEN_CONFIG["paper_fills"])
        self.assertEqual(KRAKEN_CONFIG["rest_base"], "https://futures.kraken.com")
        self.assertTrue(KrakenTerminal.LIVE_TRADING)

    def test_kraken_refuses_demo(self) -> None:
        config = json.loads(json.dumps(KRAKEN_CONFIG))
        config["rest_base"] = "https://demo-futures.kraken.com"
        with self.assertRaises(LiveEndpointError):
            KrakenTerminal(config)

    def test_binance_and_mt5_stay_off(self) -> None:
        binance = BinanceTerminal(load_binance())
        mt5 = MetaTrader5Terminal(load_mt5())
        self.assertFalse(binance.LIVE_TRADING)
        self.assertFalse(mt5.LIVE_TRADING)
        with self.assertRaises(BinanceOff):
            binance.place_order(symbol="BTCUSDT")
        with self.assertRaises(Mt5Off):
            mt5.order_send(symbol="EURUSD")
        flipped = load_binance()
        flipped["live_trading"] = True
        with self.assertRaises(BinanceOff):
            BinanceTerminal(flipped)


class SchemaAndSizeTests(unittest.TestCase):
    def test_signal_schema_round_trip(self) -> None:
        body = validate_signal(
            {
                "schema": "fxjefe.kraken.futures.v1",
                "symbol": "PF_ETHUSD",
                "side": "sell",
                "orderType": "mkt",
                "size_mode": "full_margin",
                "timeframe": "1m",
                "reduceOnly": False,
                "bar_time": 10,
                "confidence": 0.42,
            }
        )
        self.assertEqual(body["orderType"], "mkt")
        with self.assertRaises(SchemaError):
            validate_signal({**body, "schema": "fxjefe.saturn.v1"})

    def test_full_size_uses_margin_and_reduces_only_when_short(self) -> None:
        fitted = KrakenTerminal.full_size(100, 40, 0.05, 1, 1)
        self.assertEqual(fitted, 8)
        terminal = KrakenTerminal(KRAKEN_CONFIG, state_path=Path(tempfile.mkdtemp()) / "s.json")
        self.assertEqual(terminal.size_for_signal(5, 100, 40, 0.05, 1, 1), 5)
        self.assertEqual(terminal.size_for_signal(10, 100, 40, 0.05, 1, 1), 8)
        self.assertEqual(terminal.size_for_signal(None, 100, 40, 0.05, 1, 1), 8)

    def test_drawdown_guard_flattens_at_three_percent(self) -> None:
        path = Path(tempfile.mkdtemp()) / "session.json"
        terminal = KrakenTerminal(KRAKEN_CONFIG, state_path=path)
        terminal.save_state(terminal.load_state(40.0))
        decision = terminal.decide_cycle(38.8, "buy", "long")
        self.assertEqual(decision["action"], "flatten")
        self.assertIn(decision["reason"], {"daily_loss", "drawdown"})
        self.assertTrue(decision["state"]["failed"])

    def test_profit_target_halts_without_flatten(self) -> None:
        path = Path(tempfile.mkdtemp()) / "session.json"
        terminal = KrakenTerminal(KRAKEN_CONFIG, state_path=path)
        terminal.save_state(terminal.load_state(40.0))
        decision = terminal.decide_cycle(43.6, "buy", "long")
        self.assertEqual(decision["action"], "halt")
        self.assertEqual(decision["reason"], "profit_target")


class IsolationTests(unittest.TestCase):
    def test_terminals_do_not_import_each_other(self) -> None:
        kraken = (ROOT / "terminals" / "kraken" / "kraken_terminal.py").read_text(encoding="utf-8")
        binance = (ROOT / "terminals" / "binance" / "binance_terminal.py").read_text(encoding="utf-8")
        mt5 = (ROOT / "terminals" / "mt5" / "mt5_terminal.py").read_text(encoding="utf-8")
        self.assertNotIn("binance_terminal", kraken)
        self.assertNotIn("mt5_terminal", kraken)
        self.assertNotIn("kraken_terminal", binance)
        self.assertNotIn("mt5_terminal", binance)
        self.assertNotIn("kraken_terminal", mt5)
        self.assertNotIn("binance_terminal", mt5)


class RetryTests(unittest.TestCase):
    def test_private_limit_retries_once_then_succeeds(self) -> None:
        calls = {"n": 0}

        def opener(_request, timeout=0):
            calls["n"] += 1

            class Response:
                def read(self) -> bytes:
                    if calls["n"] == 1:
                        return b'{"result":"error","error":"apiLimitExceeded"}'
                    return b'{"result":"success","accounts":{"flex":{"availableMargin":40,"portfolioValue":40}}}'

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

            return Response()

        terminal = KrakenTerminal(
            KRAKEN_CONFIG,
            api_key="public",
            api_secret="c2VjcmV0LXNlY3JldA==",
            state_path=Path(tempfile.mkdtemp()) / "s.json",
            opener=opener,
        )
        terminal.budget.backoff_sec = 0
        terminal.budget._sleeper = lambda _delay: None
        payload = terminal.accounts()
        self.assertEqual(calls["n"], 2)
        self.assertEqual(payload["result"], "success")
        self.assertEqual(terminal.budget.tier, "low_volatility")


if __name__ == "__main__":
    unittest.main()
