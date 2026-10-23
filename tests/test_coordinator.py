"""Kraken Prop floors and the live/prop gate. No network and no orders."""

from __future__ import annotations

import unittest

from coordinator.coordinator import assess, daily_floor, gate_signal, half_kelly, load_rules


class RuleTests(unittest.TestCase):
    def test_published_floors(self) -> None:
        rules = load_rules()
        self.assertEqual(rules["as_of"], "2026-09-30")
        self.assertEqual(rules["modes"], ["live", "propfirm"])
        self.assertTrue(rules["demo_rejected"])
        self.assertEqual(rules["leverage"]["BTC"], 10)
        self.assertEqual(rules["leverage"]["ETH"], 5)
        self.assertEqual(rules["fees"]["swap_charges_per_day"], 6)
        self.assertEqual(rules["plans"]["starter"]["sizes"]["100000"]["max_drawdown"], 6000)
        self.assertFalse(rules["partial_take_profit"])

    def test_daily_example(self) -> None:
        self.assertEqual(daily_floor(105000, 3), 101850)


class RiskTests(unittest.TestCase):
    def test_starter_25_loss_is_inside_both_budgets(self) -> None:
        decision = assess(
            {
                "task": "risk",
                "mode": "propfirm",
                "plan": "starter",
                "account_size": 5000,
                "loss_usd": 25,
            }
        )
        self.assertEqual(decision["action"], "allow")
        self.assertEqual(decision["daily_floor"], 4850)
        self.assertEqual(decision["static_floor"], 4700)
        self.assertGreater(decision["daily_room"], 0)
        self.assertGreater(decision["drawdown_room"], 0)
        self.assertFalse(decision["order_sent"])

    def test_missing_plan_is_refused(self) -> None:
        decision = assess({"task": "risk", "mode": "propfirm", "loss_usd": 25})
        self.assertEqual(decision["action"], "refuse")

    def test_demo_and_prohibited_are_refused(self) -> None:
        self.assertEqual(assess({"task": "risk", "mode": "demo"})["action"], "refuse")
        self.assertEqual(assess({"task": "copy_signal", "mode": "propfirm"})["action"], "refuse")
        self.assertEqual(assess({"task": "pass_eval", "mode": "live"})["action"], "refuse")

    def test_touching_the_daily_floor_halts(self) -> None:
        decision = assess(
            {
                "task": "risk",
                "mode": "propfirm",
                "plan": "starter",
                "account_size": 100000,
                "balance_0030": 105000,
                "equity": 101850,
            }
        )
        self.assertEqual(decision["action"], "halt")
        self.assertEqual(decision["daily_floor"], 101850)

    def test_signal_stands_down_outside_a_trend(self) -> None:
        quiet = gate_signal(
            {"task": "signal", "mode": "propfirm", "regime": 0, "signal": {"confidence": 0.9}}
        )
        loud = gate_signal(
            {"task": "signal", "mode": "live", "regime": 1, "signal": {"confidence": 0.9}}
        )
        self.assertEqual(quiet["action"], "stand_down")
        self.assertEqual(loud["action"], "signal")
        self.assertFalse(loud["order_sent"])

    def test_half_kelly_is_capped(self) -> None:
        self.assertAlmostEqual(half_kelly(0.6, 2.0, 0.01), 0.01)
        self.assertEqual(half_kelly(0.4, 1.0, 0.02), 0.0)


if __name__ == "__main__":
    unittest.main()
