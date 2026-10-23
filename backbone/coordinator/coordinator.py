"""Live Kraken and Kraken Prop gate. Demo is refused. No order is sent."""

from __future__ import annotations

import json
from pathlib import Path

RULES_PATH = Path(__file__).with_name("program_rules.json")
MODES = ("live", "propfirm")
PROHIBITED = frozenset(
    {"copy_signal", "pass_eval", "cross_account_hedge", "share_credentials", "demo"}
)


def load_rules(path: Path | None = None) -> dict:
    return json.loads((path or RULES_PATH).read_text(encoding="utf-8"))


def daily_floor(balance_0030: float, daily_loss_pct: float = 3.0) -> float:
    """Equity floor for the next 24h. Balance at 00:30 UTC excludes open positions."""
    return float(balance_0030) * (1.0 - float(daily_loss_pct) / 100.0)


def static_floor(account_size: float, max_drawdown: float) -> float:
    return float(account_size) - float(max_drawdown)


def half_kelly(win_rate: float, payoff_ratio: float, max_risk: float) -> float:
    """Half of the Kelly fraction, capped. Zero when the edge is not positive."""
    if payoff_ratio <= 0 or not 0 <= win_rate <= 1:
        return 0.0
    kelly = win_rate - (1.0 - win_rate) / payoff_ratio
    if kelly <= 0:
        return 0.0
    return min(kelly / 2.0, max_risk)


def assess(task: dict, rules: dict | None = None) -> dict:
    rules = rules or load_rules()
    kind = str(task.get("task") or "")
    mode = str(task.get("mode") or "")
    if kind in PROHIBITED or mode == "demo" or task.get("demo") is True:
        return {"action": "refuse", "reason": kind or "demo", "order_sent": False}
    if mode not in MODES:
        return {"action": "refuse", "reason": "mode must be live or propfirm", "order_sent": False}
    if kind == "signal":
        return gate_signal(task, rules)
    if kind != "risk":
        return {"action": "refuse", "reason": "task must be risk or signal", "order_sent": False}
    if mode == "live":
        return {"action": "allow", "mode": "live", "order_sent": False, "reason": "live has no prop plan"}
    plan = task.get("plan")
    plans = rules["plans"]
    size_key = str(int(task["account_size"])) if task.get("account_size") is not None else ""
    if plan not in plans or size_key not in plans[plan]["sizes"]:
        return {"action": "refuse", "reason": "plan and account_size are required", "order_sent": False}
    spec = plans[plan]["sizes"][size_key]
    account_size = float(size_key)
    balance = float(task.get("balance_0030", account_size))
    if task.get("equity") is not None:
        equity = float(task["equity"])
    else:
        equity = balance - float(task.get("loss_usd") or 0)
    daily = daily_floor(balance, rules["daily_loss_pct"])
    floor = static_floor(account_size, spec["max_drawdown"])
    breach = equity <= daily or equity <= floor
    return {
        "action": "halt" if breach else "allow",
        "mode": "propfirm",
        "plan": plan,
        "account_size": account_size,
        "daily_floor": daily,
        "static_floor": floor,
        "daily_room": equity - daily,
        "drawdown_room": equity - floor,
        "upgrade_target": spec["upgrade_target"],
        "order_sent": False,
    }


def gate_signal(task: dict, rules: dict | None = None) -> dict:
    """Pass a signal only in a trending regime above the confidence floor."""
    rules = rules or load_rules()
    signal = task.get("signal") or {}
    regime = task.get("regime")
    confidence = float(signal.get("confidence") or 0)
    minimum = float(rules["confidence_min"])
    if regime != 1 or confidence <= minimum:
        return {"action": "stand_down", "order_sent": False, "reason": "regime or confidence"}
    return {"action": "signal", "signal": signal, "order_sent": False}
