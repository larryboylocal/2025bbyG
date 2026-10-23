# Coordinator

Modes are `live` and `propfirm`. A demo mode is refused. This process does not send an order.

Kraken Prop numbers are the 30 September 2026 rules: Starter, Intermediate, and Advanced. Daily loss is 3% of the 00:30 UTC balance, excluding open positions. Drawdown floors are static. BTC, Nasdaq 100, and S&P 500 leverage is 10x. ETH is 5x. The daily swap of 0.033% is charged six times.

`plan` is required for a prop risk check. It is not inferred.

The two architecture notes (enterprise pipeline and the implementation guide) map onto this tree as: candle features in `terminals/kraken/scripts/generate_features.py`, the regime and confidence gate in `gate_signal`, and the prop equity floors in `assess`. Half-Kelly sizing is capped and is not a claim about win rate.
