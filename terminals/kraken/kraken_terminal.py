"""Kraken futures terminal.

All Kraken request signing, rate limiting, instrument naming, order entry,
position reads, and the funded-eval guard live in this class. Binance and
MetaTrader 5 do not import it.

Official sources used for the wire format:
- REST auth: https://docs.kraken.com/exchange/guides/futures/rest
- Rate limits: https://docs.kraken.com/exchange/guides/futures/ratelimits
- Environments: https://docs.kraken.com/exchange/guides/futures/introduction
- sendorder: https://docs.kraken.com/api/docs/futures-api/trading/send-order
- openpositions: https://docs.kraken.com/api-reference/account-information/get-open-positions
- Candles: https://docs.kraken.com/api-reference/candles/market-candles
- WebSocket: https://docs.kraken.com/exchange/api-reference/futures-websocket
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any

from .schema import ORDER_TYPES, SCHEMA_NAME

LIVE_REST = "https://futures.kraken.com"
DEMO_REST = "https://demo-futures.kraken.com"
LIVE_WS = "wss://futures.kraken.com/ws/v1"

# Cost table published for /derivatives endpoints. Public chart calls are not
# on that budget. Unknown private endpoints use the sendorder cost so a new
# call cannot skip the limiter.
ENDPOINT_COSTS = {
    "sendorder": 10,
    "editorder": 10,
    "cancelorder": 10,
    "cancelallorders": 25,
    "cancelallordersafter": 25,
    "accounts": 2,
    "openpositions": 2,
    "openorders": 2,
    "orders/status": 1,
    "fills": 2,
    "batchorder": 9,
}

# Kraken signs the /api/v3 path, not the /derivatives prefix on the URL.
SIGN_PREFIX = "/api/v3"


class LiveEndpointError(RuntimeError):
    pass


class KrakenAPIError(RuntimeError):
    pass


class CostBudget:
    """Tiered Kraken /derivatives cost budget.

    Low volatility stays at 66% of the published system max.
    High volatility may use 88.88% and no more.
    A call that would touch the exchange cap is not sent.
    """

    LOW_FRACTION = 0.66
    HIGH_FRACTION = 0.8888

    def __init__(
        self,
        system_max: int,
        window_sec: float,
        low_fraction: float,
        high_fraction: float,
        backoff_sec: float,
        sleeper: Any = None,
        clock: Any = None,
    ) -> None:
        if system_max <= 0 or window_sec <= 0:
            raise LiveEndpointError("rate limit system max and window must be positive")
        if abs(low_fraction - self.LOW_FRACTION) > 1e-9:
            raise LiveEndpointError("low volatility tier must be 0.66 of system max")
        if abs(high_fraction - self.HIGH_FRACTION) > 1e-9:
            raise LiveEndpointError("high volatility tier must be 0.8888 of system max")
        if not low_fraction < high_fraction < 1:
            raise LiveEndpointError("tier fractions must stay under the exchange cap")
        self.system_max = int(system_max)
        self.window_sec = float(window_sec)
        self.low_fraction = float(low_fraction)
        self.high_fraction = float(high_fraction)
        self.backoff_sec = float(backoff_sec)
        self._sleeper = sleeper or time.sleep
        self._clock = clock or time.monotonic
        self.tier = "low_volatility"
        self.tier_reason = "default_low"
        self._events: deque[tuple[float, int]] = deque()
        self._lock = threading.Lock()
        self._backoff_until = 0.0
        self.public_calls = 0
        self.blocked_calls = 0

    def _ceiling_unlocked(self) -> float:
        fraction = self.high_fraction if self.tier == "high_volatility" else self.low_fraction
        return self.system_max * fraction

    def set_tier(self, tier: str, reason: str) -> None:
        if tier not in ("low_volatility", "high_volatility"):
            raise LiveEndpointError(f"unknown rate tier {tier}")
        with self._lock:
            self.tier = tier
            self.tier_reason = reason

    def note_public_call(self) -> None:
        with self._lock:
            self.public_calls += 1

    def note_limit_hit(self) -> None:
        with self._lock:
            self._backoff_until = self._clock() + self.backoff_sec
            self.tier = "low_volatility"
            self.tier_reason = "backoff_after_api_limit"

    def wait_backoff(self) -> None:
        with self._lock:
            delay = self._backoff_until - self._clock()
        if delay > 0:
            self._sleeper(delay)

    def _used_unlocked(self, now: float) -> int:
        while self._events and now - self._events[0][0] >= self.window_sec:
            self._events.popleft()
        return sum(item[1] for item in self._events)

    def try_acquire(self, cost: int) -> bool:
        """Reserve cost if it fits the active tier. False means do not send."""
        if cost <= 0:
            return True
        if cost >= self.system_max:
            return False
        with self._lock:
            now = self._clock()
            if now < self._backoff_until:
                self.blocked_calls += 1
                return False
            used = self._used_unlocked(now)
            ceiling = self._ceiling_unlocked()
            if used + cost <= ceiling and used + cost < self.system_max:
                self._events.append((now, cost))
                return True
            self.blocked_calls += 1
            return False

    def acquire(self, cost: int) -> None:
        if cost <= 0:
            return
        if cost >= self.system_max:
            raise LiveEndpointError("single call cost would consume the exchange cap")
        while not self.try_acquire(cost):
            with self._lock:
                now = self._clock()
                if now < self._backoff_until:
                    wait = self._backoff_until - now
                elif self._events:
                    wait = self.window_sec - (now - self._events[0][0])
                else:
                    wait = self.window_sec
            self._sleeper(max(wait, 0.01))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = self._clock()
            used = self._used_unlocked(now)
            ceiling = self._ceiling_unlocked()
            return {
                "tier": self.tier,
                "tier_reason": self.tier_reason,
                "system_max_cost": self.system_max,
                "window_sec": self.window_sec,
                "ceiling_cost": ceiling,
                "used_cost": used,
                "remaining_cost": max(0.0, ceiling - used),
                "fraction_of_system_max": used / self.system_max,
                "fraction_of_tier_ceiling": (used / ceiling) if ceiling else 1.0,
                "backoff_active": now < self._backoff_until,
                "public_calls": self.public_calls,
                "blocked_calls": self.blocked_calls,
                "low_fraction": self.low_fraction,
                "high_fraction": self.high_fraction,
            }


class KrakenTerminal:
    """Live Kraken futures/perps terminal. Demo endpoints are rejected."""

    LIVE_TRADING = True

    def __init__(
        self,
        config: dict[str, Any],
        api_key: str = "",
        api_secret: str = "",
        state_path: Path | None = None,
        opener: Any = None,
    ) -> None:
        self.config = config
        self.api_key = api_key
        self.api_secret = api_secret
        self._opener = opener or urllib.request.urlopen
        self._nonce_lock = threading.Lock()
        self._last_nonce = 0
        self.budget = self._build_budget(config)
        self.rest_base = str(config.get("rest_base") or LIVE_REST).rstrip("/")
        self.websocket_url = str(config.get("websocket_url") or LIVE_WS)
        self._require_live_endpoint()
        self._require_live_flags()
        root = Path(__file__).resolve().parent
        self.state_path = state_path or (root / "state" / "session.json")

    @staticmethod
    def _build_budget(config: dict[str, Any]) -> CostBudget:
        rate = config.get("rate_limit")
        if not isinstance(rate, dict):
            raise LiveEndpointError("rate_limit config is required")
        tiers = rate.get("tiers")
        volatility = rate.get("volatility")
        backoff = rate.get("backoff")
        if not isinstance(tiers, dict) or not isinstance(volatility, dict) or not isinstance(backoff, dict):
            raise LiveEndpointError("rate_limit tiers, volatility, and backoff are required")
        try:
            low = float(tiers["low_volatility"]["max_fraction_of_system_max"])
            high = float(tiers["high_volatility"]["max_fraction_of_system_max"])
            system_max = int(rate["system_max_cost"])
            window = float(rate["window_sec"])
            backoff_sec = float(backoff["api_limit_exceeded_sec"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LiveEndpointError("rate_limit config is missing a required key") from exc
        if backoff.get("retry_once") is not True:
            raise LiveEndpointError("rate_limit backoff retry_once must be true")
        return CostBudget(system_max, window, low, high, backoff_sec)

    def _require_live_flags(self) -> None:
        flags = ("trading_enabled", "allow_live_trades", "live_trading")
        missing = [name for name in flags if self.config.get(name) is not True]
        if missing or self.config.get("paper_fills") is True:
            raise LiveEndpointError(
                "Kraken terminal requires trading_enabled, allow_live_trades, "
                "and live_trading, with paper fills off"
            )
        if self.config.get("environment") != "live":
            raise LiveEndpointError("Kraken environment must be live")

    def _require_live_endpoint(self) -> None:
        if self.rest_base != LIVE_REST or "demo-futures" in self.rest_base:
            raise LiveEndpointError(
                f"Kraken live trading refuses non-production REST base {self.rest_base}"
            )
        if self.websocket_url != LIVE_WS or "demo-futures" in self.websocket_url:
            raise LiveEndpointError(
                f"Kraken live trading refuses non-production WebSocket {self.websocket_url}"
            )

    def next_nonce(self) -> str:
        with self._nonce_lock:
            nonce = max(int(time.time() * 1000), self._last_nonce + 1)
            self._last_nonce = nonce
            return str(nonce)

    @staticmethod
    def sign(secret: str, post_data: str, nonce: str, endpoint_path: str) -> str:
        """Authent header: SHA256(postData + nonce + endpointPath), HMAC-SHA512, base64.

        postData is the url-encoded body exactly as sent. endpoint_path is
        /api/v3/<name> (Kraken's documented URL extension).
        """
        message = (post_data + nonce + endpoint_path).encode("utf-8")
        digest = hashlib.sha256(message).digest()
        key = base64.b64decode(secret)
        mac = hmac.new(key, digest, hashlib.sha512).digest()
        return base64.b64encode(mac).decode("ascii")

    @staticmethod
    def sign_ws_challenge(secret: str, challenge: str) -> str:
        """Private-feed signature: HMAC-SHA512(secret, SHA256(challenge)), base64."""
        digest = hashlib.sha256(challenge.encode("utf-8")).digest()
        key = base64.b64decode(secret)
        mac = hmac.new(key, digest, hashlib.sha512).digest()
        return base64.b64encode(mac).decode("ascii")

    def ws_challenge_request(self) -> dict[str, str]:
        if not self.api_key:
            raise KrakenAPIError("missing Kraken futures API key")
        return {"event": "challenge", "api_key": self.api_key}

    def ws_private_subscribe(self, feed: str, challenge: str) -> dict[str, str]:
        if not self.api_secret:
            raise KrakenAPIError("missing Kraken futures API secret")
        return {
            "event": "subscribe",
            "feed": feed,
            "api_key": self.api_key,
            "original_challenge": challenge,
            "signed_challenge": self.sign_ws_challenge(self.api_secret, challenge),
        }

    @staticmethod
    def ws_public_subscribe(feed: str, product_ids: list[str]) -> dict[str, Any]:
        return {"event": "subscribe", "feed": feed, "product_ids": list(product_ids)}

    def _sign_path(self, endpoint: str) -> str:
        name = endpoint.strip("/")
        return f"{SIGN_PREFIX}/{name}"

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        private: bool = False,
        cost: int | None = None,
        _retried: bool = False,
    ) -> dict[str, Any]:
        params = {key: value for key, value in (params or {}).items() if value is not None}
        encoded = urllib.parse.urlencode(params, doseq=True)
        url = f"{self.rest_base}/derivatives/api/v3/{endpoint.strip('/')}"
        data = None
        if method.upper() == "GET":
            if encoded:
                url = f"{url}?{encoded}"
            post_data = ""
        else:
            post_data = encoded
            data = encoded.encode("utf-8")
        headers = {"Accept": "application/json", "User-Agent": "fxjefe-kraken-terminal"}
        if private:
            if not self.api_key or not self.api_secret:
                raise KrakenAPIError("missing Kraken futures API key or secret")
            nonce = self.next_nonce()
            headers["APIKey"] = self.api_key
            headers["Nonce"] = nonce
            headers["Authent"] = self.sign(
                self.api_secret, post_data, nonce, self._sign_path(endpoint)
            )
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            spend = ENDPOINT_COSTS["sendorder"] if cost is None else cost
            self.budget.acquire(spend)
        elif method.upper() != "GET":
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with self._opener(request, timeout=20) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise KrakenAPIError(f"HTTP {exc.code} {endpoint}: {detail}") from exc
        payload = json.loads(raw)
        if isinstance(payload, dict) and payload.get("error") == "apiLimitExceeded":
            self.budget.note_limit_hit()
            if not _retried and self.config["rate_limit"]["backoff"]["retry_once"] is True:
                self.budget.wait_backoff()
                return self._request(
                    method, endpoint, params, private=private, cost=cost, _retried=True
                )
            raise KrakenAPIError("apiLimitExceeded")
        if isinstance(payload, dict) and payload.get("result") not in (None, "success"):
            raise KrakenAPIError(f"{endpoint} result={payload.get('result')}")
        return payload

    def public_get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("GET", endpoint, params, private=False, cost=0)

    def candles(self, symbol: str, resolution: str, count: int = 300) -> list[dict[str, Any]]:
        """Public charts API. Not a /derivatives call, so it spends no REST budget."""
        url = (
            f"{self.rest_base}/api/charts/v1/trade/{urllib.parse.quote(symbol)}/"
            f"{urllib.parse.quote(resolution)}?count={int(count)}"
        )
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "fxjefe-kraken-terminal"},
        )
        self.budget.note_public_call()
        with self._opener(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        rows = payload.get("candles") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise KrakenAPIError(f"candles payload missing candles for {symbol}")
        return rows

    def instruments(self) -> list[dict[str, Any]]:
        payload = self.public_get("instruments")
        rows = payload.get("instruments")
        if not isinstance(rows, list):
            raise KrakenAPIError("instruments payload missing instruments")
        return rows

    def instrument(self, symbol: str) -> dict[str, Any]:
        for row in self.instruments():
            if row.get("symbol") == symbol:
                return row
        raise KrakenAPIError(f"instrument not listed: {symbol}")

    def accounts(self) -> dict[str, Any]:
        return self._request("GET", "accounts", private=True, cost=ENDPOINT_COSTS["accounts"])

    def open_positions(self) -> list[dict[str, Any]]:
        payload = self._request(
            "GET", "openpositions", private=True, cost=ENDPOINT_COSTS["openpositions"]
        )
        rows = payload.get("openPositions") or []
        if not isinstance(rows, list):
            raise KrakenAPIError("openpositions payload is not a list")
        return rows

    def send_order(
        self,
        symbol: str,
        side: str,
        size: float,
        order_type: str = "mkt",
        limit_price: float | None = None,
        stop_price: float | None = None,
        reduce_only: bool = False,
        cli_ord_id: str | None = None,
        trigger_signal: str | None = None,
    ) -> dict[str, Any]:
        if order_type not in ORDER_TYPES:
            raise KrakenAPIError(f"unsupported orderType {order_type}")
        if side not in ("buy", "sell"):
            raise KrakenAPIError(f"unsupported side {side}")
        if size <= 0:
            raise KrakenAPIError("size must be > 0")
        params: dict[str, Any] = {
            "orderType": order_type,
            "symbol": symbol,
            "side": side,
            "size": self._format_size(size),
            "reduceOnly": "true" if reduce_only else "false",
        }
        if limit_price is not None:
            params["limitPrice"] = limit_price
        if stop_price is not None:
            params["stopPrice"] = stop_price
        if cli_ord_id:
            params["cliOrdId"] = cli_ord_id[:100]
        if trigger_signal:
            params["triggerSignal"] = trigger_signal
        payload = self._request(
            "POST", "sendorder", params, private=True, cost=ENDPOINT_COSTS["sendorder"]
        )
        status = (payload.get("sendStatus") or {}).get("status")
        if status not in {"placed", "attempted", "filled"}:
            # attempted is not always used; placed is the documented success.
            # filled can appear on immediate IOC. Anything else did not rest or fill.
            if status != "placed":
                raise KrakenAPIError(f"sendorder not placed: {status or payload}")
        return payload

    def cancel_all_orders(self) -> dict[str, Any]:
        return self._request(
            "POST",
            "cancelallorders",
            private=True,
            cost=ENDPOINT_COSTS["cancelallorders"],
        )

    def flatten(self, reason: str) -> list[dict[str, Any]]:
        """Cancel working orders and reduce-only the whole position book."""
        self.cancel_all_orders()
        results = []
        for position in self.open_positions():
            size = float(position.get("size") or 0)
            if size <= 0:
                continue
            side = "sell" if str(position.get("side")).lower() == "long" else "buy"
            symbol = str(position["symbol"])
            results.append(
                self.send_order(
                    symbol=symbol,
                    side=side,
                    size=size,
                    order_type="mkt",
                    reduce_only=True,
                    cli_ord_id=f"fxjefe-flat-{symbol}-{int(time.time())}",
                )
            )
        results.append({"flatten_reason": reason, "schema": SCHEMA_NAME})
        return results

    @staticmethod
    def initial_margin_fraction(instrument: dict[str, Any]) -> float:
        """Read the exchange initial-margin fraction. Do not invent one."""
        for key in ("initialMargin", "imf", "initialMarginFraction"):
            value = instrument.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                return float(value)
        levels = instrument.get("marginLevels") or instrument.get("retailMarginLevels") or []
        if isinstance(levels, list):
            for level in levels:
                if not isinstance(level, dict):
                    continue
                for key in ("initialMargin", "initialMarginFraction"):
                    value = level.get(key)
                    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                        return float(value)
        leverage = instrument.get("maxLeverage") or instrument.get("maximumLeverage")
        if isinstance(leverage, (int, float)) and not isinstance(leverage, bool) and leverage > 0:
            return 1.0 / float(leverage)
        raise KrakenAPIError(
            f"no initial margin on {instrument.get('symbol')}; refusing to size"
        )

    @staticmethod
    def contract_size(instrument: dict[str, Any]) -> float:
        for key in ("contractSize", "contractValueTradePrecision"):
            value = instrument.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 and key == "contractSize":
                return float(value)
        value = instrument.get("contractSize")
        if value in (None, 0):
            return 1.0
        return float(value)

    @staticmethod
    def size_step(instrument: dict[str, Any]) -> float:
        for key in ("contractValueTradePrecision", "tickSize"):
            # Precision is a decimal count, not a step. Prefer an explicit step.
            pass
        for key in ("minSize", "quantityStep", "sizeStep"):
            value = instrument.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 and key != "minSize":
                return float(value)
        precision = instrument.get("contractValueTradePrecision")
        if isinstance(precision, int) and not isinstance(precision, bool) and precision >= 0:
            return 10 ** (-precision)
        return float(instrument.get("minSize") or 1)

    @staticmethod
    def full_size(
        mark: float,
        available_margin: float,
        initial_margin_fraction: float,
        contract_size: float,
        size_step: float,
    ) -> float:
        """Largest size whose initial margin fits. Zero when margin cannot fit one step."""
        if mark <= 0 or available_margin <= 0 or initial_margin_fraction <= 0 or contract_size <= 0:
            return 0.0
        if size_step <= 0:
            raise KrakenAPIError("size step must be > 0")
        margin_per_step = mark * contract_size * initial_margin_fraction * size_step
        if margin_per_step <= 0:
            return 0.0
        steps = int(available_margin / margin_per_step)
        return round(steps * size_step, 10)

    def size_for_signal(
        self,
        requested: float | None,
        mark: float,
        available_margin: float,
        initial_margin_fraction: float,
        contract_size: float,
        size_step: float,
    ) -> float:
        """Take the signal's full size when margin covers it. Reduce only when it does not."""
        fitted = self.full_size(
            mark, available_margin, initial_margin_fraction, contract_size, size_step
        )
        if requested is None:
            return fitted
        if requested <= 0:
            return 0.0
        if requested <= fitted + 1e-12:
            return float(requested)
        return fitted

    @staticmethod
    def available_margin(accounts_payload: dict[str, Any]) -> tuple[float, float]:
        """Return (available_margin, portfolio_value) in the flex multi-collateral wallet."""
        accounts = accounts_payload.get("accounts") or accounts_payload
        flex = accounts.get("flex") if isinstance(accounts, dict) else None
        if not isinstance(flex, dict):
            raise KrakenAPIError("accounts payload has no flex wallet")
        available = flex.get("availableMargin")
        portfolio = flex.get("portfolioValue", flex.get("balanceValue", flex.get("collateralValue")))
        if not isinstance(available, (int, float)) or isinstance(available, bool):
            raise KrakenAPIError("flex wallet has no availableMargin")
        if not isinstance(portfolio, (int, float)) or isinstance(portfolio, bool):
            portfolio = available
        return float(available), float(portfolio)

    def classify_tier(self, candles: list[dict[str, Any]], now_utc: time.struct_time | None = None) -> dict[str, str]:
        """Switch the active API tier from candle volatility and volume.

        High volatility may spend up to 88.88% of system max.
        Everything else, including quiet hours and thin volume, stays at 66%.
        Short history stays on the low tier so a cold start cannot burst the cap.
        """
        rules = self.config["rate_limit"]["volatility"]
        period = int(rules["atr_period"])
        lookback = int(rules["lookback_bars"])
        rows = list(candles[-max(lookback, period + 2) :])
        if len(rows) < period + 2:
            self.budget.set_tier("low_volatility", "insufficient_bars")
            return {"tier": "low_volatility", "reason": "insufficient_bars"}
        closes = [float(row["close"]) for row in rows]
        highs = [float(row["high"]) for row in rows]
        lows = [float(row["low"]) for row in rows]
        volumes = [float(row.get("volume") or 0) for row in rows]
        true_ranges: list[float] = []
        for index in range(1, len(rows)):
            span = max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
            true_ranges.append(span / closes[index] if closes[index] else 0.0)
        if len(true_ranges) < period:
            self.budget.set_tier("low_volatility", "insufficient_bars")
            return {"tier": "low_volatility", "reason": "insufficient_bars"}

        def atr_ending(end: int) -> float:
            window = true_ranges[end - period : end]
            return sum(window) / period

        samples = [atr_ending(end) for end in range(period, len(true_ranges) + 1)]
        latest = samples[-1]
        ordered = sorted(samples)
        median = ordered[len(ordered) // 2]
        high_abs = float(rules["high_when_atr_pct_gte"])
        high_rel = float(rules["high_when_atr_over_median_gte"])
        if latest >= high_abs or (median > 0 and latest >= high_rel * median):
            self.budget.set_tier("high_volatility", "high_volatility")
            return {"tier": "high_volatility", "reason": "high_volatility"}
        ordered_volume = sorted(volumes)
        volume_median = ordered_volume[len(ordered_volume) // 2]
        thin = volume_median <= 0 or volumes[-1] <= float(rules["low_volume_fraction_of_median"]) * volume_median
        clock = now_utc or time.gmtime()
        quiet = clock.tm_hour in set(int(hour) for hour in rules["quiet_hours_utc"])
        if thin:
            reason = "low_volume"
        elif quiet:
            reason = "quiet_hours"
        else:
            reason = "default_low"
        self.budget.set_tier("low_volatility", reason)
        return {"tier": "low_volatility", "reason": reason}

    def rate_status(self) -> dict[str, Any]:
        return self.budget.snapshot()

    def evaluate_guards(self, equity: float, state: dict[str, Any]) -> str:
        """Return ok, daily_loss, drawdown, profit_target, or sacrifice_cap."""
        eval_cfg = self.config["eval"]
        if not eval_cfg.get("enable_dd_guard") or not eval_cfg.get("dd_auto_close"):
            raise LiveEndpointError("drawdown guard must be on and must flatten")
        day_start = float(state["day_start_equity"])
        peak = max(float(state["peak_equity"]), equity)
        state["peak_equity"] = peak
        if day_start <= 0:
            return "sacrifice_cap"
        loss_pct = (day_start - equity) / day_start * 100.0
        dd_pct = (peak - equity) / peak * 100.0
        profit_pct = (equity - day_start) / day_start * 100.0
        sacrifice = float(self.config.get("sacrifice_cap_quote", 40))
        if day_start - equity >= sacrifice:
            return "sacrifice_cap"
        if loss_pct >= float(eval_cfg["max_daily_loss_pct"]):
            return "daily_loss"
        if dd_pct >= float(eval_cfg["max_drawdown_pct"]):
            return "drawdown"
        if profit_pct >= float(eval_cfg["profit_target_pct"]):
            return "profit_target"
        return "ok"

    def load_state(self, equity: float) -> dict[str, Any]:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if self.state_path.exists():
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        else:
            state = {
                "utc_date": today,
                "day_start_equity": equity,
                "peak_equity": equity,
                "halt_entries": False,
                "failed": False,
                "target_hit": False,
            }
        if state.get("utc_date") != today and not state.get("failed"):
            state["utc_date"] = today
            state["day_start_equity"] = equity
            if not state.get("target_hit"):
                state["halt_entries"] = False
        state["peak_equity"] = max(float(state.get("peak_equity", equity)), equity)
        return state

    def save_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def decide_cycle(self, equity: float, signal_side: str, position_side: str | None) -> dict[str, Any]:
        """Decide the next live action. Does not send an order by itself."""
        state = self.load_state(equity)
        if state.get("failed") or state.get("target_hit"):
            state["halt_entries"] = True
            self.save_state(state)
            return {"action": "halt", "reason": "failed" if state.get("failed") else "profit_target", "state": state}
        verdict = self.evaluate_guards(equity, state)
        if verdict in {"daily_loss", "drawdown", "sacrifice_cap"}:
            state["failed"] = True
            state["halt_entries"] = True
            state["last_guard"] = verdict
            self.save_state(state)
            return {"action": "flatten", "reason": verdict, "state": state}
        if verdict == "profit_target":
            state["target_hit"] = True
            state["halt_entries"] = True
            state["last_guard"] = verdict
            self.save_state(state)
            return {"action": "halt", "reason": verdict, "state": state}
        self.save_state(state)
        if not self.config.get("maximize_trade_count"):
            raise LiveEndpointError("maximize_trade_count must stay on")
        # Every closed bar is a round trip: flatten anything open, then enter full size.
        return {
            "action": "flip_full_margin",
            "reason": "flip_every_closed_bar",
            "signal_side": signal_side,
            "close_first": position_side is not None,
            "state": state,
        }

    @staticmethod
    def _format_size(size: float) -> str:
        text = f"{size:.10f}".rstrip("0").rstrip(".")
        return text or "0"
