# Live Trading Readiness

Angelique's Trading Hub is designed so that the decision/approval lifecycle and MT5 bridge are deterministic and auditable, but no software-only review can guarantee a broker, terminal, network or market-data environment will never fail.

Before enabling live automatic execution on an actual account:

1. Verify that MT5 is logged into the intended live account and that the broker/company identity shown in the Trading Hub is correct.
2. Keep `TRADING_LIVE_AUTO_EXECUTION=false` until the full bridge has been verified on the actual terminal.
3. Confirm the broker's symbol specifications, minimum volume, volume step, stops level, tick size/value and filling policy are all being returned by MT5.
4. Confirm the daily/weekly loss values shown by the Trading Hub are consistent with the broker's account history.
5. Run the same strategy in demo first and inspect the journal, MT5 order history and position monitor.
6. Only then enable live automatic execution deliberately.

The execution bridge never retries an ambiguous `order_send` after a submission has been sent. This is intentional: an unknown result must be reconciled rather than resent, because blindly retrying can create a duplicate live position.
