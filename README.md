# FXJEFE SaturnSyncAmen — Kraken futures runtime

Modes are live Kraken futures and Kraken Prop. Demo is not a mode. Kraken is the only terminal allowed to send live orders, and it still sends nothing until an API key is present. Prop risk uses the 30 September 2026 Starter, Intermediate, and Advanced floors in `coordinator/program_rules.json`. The plan is not guessed.

| Terminal | Class | Runtime | Live orders |
|---|---|---|---|
| Kraken futures/perps | `KrakenTerminal` | `127.0.0.1:8080` | On |
| Binance | `BinanceTerminal` | `127.0.0.1:8180` | Off |
| MetaTrader 5 | `MetaTrader5Terminal` | `127.0.0.1:8280` | Off |

Shared code is `shared/cache_arrays.py` (`RingCache`) only. Each terminal keeps its own scripts, schema, and order logic. Vendored wheels live in `wheels/` and are copied into `backbone/`.

## Kraken live profile

`terminals/kraken/config.json` is what the runtime loads.

- `trading_enabled`, `allow_live_trades`, `live_trading`: `true`
- `paper_fills`: `false`
- `rest_base`: `https://futures.kraken.com`
- `websocket_url`: `wss://futures.kraken.com/ws/v1`
- Instruments: linear perps `PF_XBTUSD`, `PF_ETHUSD`, `PF_SOLUSD`, `PF_XRPUSD`
- Bar: `1m`. Every closed bar is a full-margin flip (`frequency_mode`: `flip_every_closed_bar`)
- Size: `full_margin`. The signal size is sent whole when initial margin covers it. It is reduced only when that size would exceed available margin.
- Eval: 9% profit target stops new entries. 3% daily loss and 3% max drawdown flatten the book and halt. `dd_auto_close` and `enable_dd_guard` are `true`.
- Account cap: 40 USD. A loss of that size also flattens.

Keys are environment variables, never the repo: `KRAKEN_FUTURES_API_KEY` and `KRAKEN_FUTURES_API_SECRET`. No key means the runtime stays up and sends nothing. It does not invent a paper fill.

Kraken wire format follows the derivatives docs: Authent is SHA-256 of `postData + nonce + /api/v3/<endpoint>`, then HMAC-SHA512 with the base64-decoded secret. `mkt` is their immediate-or-cancel order with 1% price protection. Demo host `demo-futures.kraken.com` is rejected.

## Rate limit tiers

Kraken's published `/derivatives` budget is 500 cost per 10 seconds (`system_max_cost`). Public chart calls are not in that budget; they are counted and still not allowed to push private traffic into the cap. Costs used here are the published ones (`sendorder` 10, `openpositions` 2, `accounts` 2, `cancelallorders` 25).

The runtime enforces two ceilings from config:

- `rate_limit.tiers.low_volatility.max_fraction_of_system_max` = **0.66**. Quiet or thin markets, and any bar that is not high volatility, including a short history. Ceiling = 330 cost per 10 seconds.
- `rate_limit.tiers.high_volatility.max_fraction_of_system_max` = **0.8888**. High volatility only. Ceiling = 444.4 cost per 10 seconds.

A request that would pass the active ceiling, or that would reach `system_max_cost`, is not sent. The limiter waits for the window, or returns no reservation. On `apiLimitExceeded` the tier drops to low volatility, the runtime backs off for `rate_limit.backoff.api_limit_exceeded_sec` (10), and it retries that call once.

Volatility switch (`KrakenTerminal.classify_tier`):

- High when the latest ATR as a fraction of price is at least `high_when_atr_pct_gte` (0.0015), or at least `high_when_atr_over_median_gte` (1.25) times the median ATR in the lookback.
- Otherwise low. Thin volume (last bar at or under `low_volume_fraction_of_median` of the median) and `quiet_hours_utc` are recorded as the reason. They do not raise the ceiling.

`/health` on port 8080 reports the tier, ceiling, used cost, and remaining cost.

## Proof

From the repo root, after the vendored wheel install:

```bash
python3 -m venv .venv
.venv/bin/pip install --no-index --find-links wheels pandas
.venv/bin/python -m unittest tests.test_kraken_expectations
.venv/bin/python -m terminals.kraken.kraken_runtime --self-check
.venv/bin/python terminals/kraken/scripts/prove_pipeline.py
```

`prove_pipeline.py` pulls public `PF_XBTUSD` 1m candles, builds features with pandas, builds next-bar labels, builds live signals, and validates `fxjefe.kraken.futures.v1`. It does not send an order. The last proof is written to `terminals/kraken/proof/last_proof.json`.

## Boot copy

`backbone/` is the self-contained copy: sources, compiled bytecode, and wheels. It is written only after the proof, schema check, rate-tier check, live-flag check, and backbone self-check pass.

```bash
backbone/launch.sh --self-check
sudo backbone/install-boot.sh
```

`install-boot.sh` copies the backbone to `/opt/fxjefe-backbone` when it can, installs the wheels into a venv there, and installs a systemd unit so the Kraken runtime comes back on boot. Without root it installs a user unit or an `@reboot` crontab. Binance and MetaTrader 5 are not started.

The first run starts the service. Running it again is an update: the self-check has to pass, `kraken.env` is kept, the previous tree is moved aside, and the machine reboots onto the new copy. A failed self-check leaves the installed runtime where it is.
