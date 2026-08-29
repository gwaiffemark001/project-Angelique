# Angelique Trade Decision Logic

Angelique treats SMC observations as evidence, not independent signals. An FVG,
Order Block, BOS, CHoCH, or liquidity sweep cannot create a trade plan alone.

## Decision pipeline

1. Validate candle availability and freshness.
2. Establish higher-timeframe context and meaningful swing structure.
3. Identify liquidity pools and any sweep or structural break.
4. Confirm displacement and link the move to a qualified FVG or Order Block.
5. Evaluate premium/discount location and zone mitigation.
6. Wait for retracement into an unmitigated zone.
7. Require lower-timeframe structure and displacement confirmation.
8. Derive structural invalidation, target liquidity, risk/reward, spread, costs,
   and account margin.
9. Generate a plan only when every required condition passes.

## Decision states

- `BLOCKED_BY_DATA`: required market data is missing or stale.
- `NO_SETUP`: there is no coherent directional narrative.
- `WAIT`: a thesis or candidate zone exists, but the sequence is incomplete.
- `BUY_PLAN_READY` / `SELL_PLAN_READY`: the full sequence and risk checks can
  support a plan.
- `BLOCKED_BY_RISK`: the market idea exists but risk, cost, or margin checks fail.
- `INVALID_SETUP`: the zone or structural premise has been invalidated.

Each timeframe's SMC output includes structural points, liquidity evidence,
event-linked zone metadata, mitigation status, and a `sequence` audit object.
The desktop report and canonical workflow consume the same decision state. A
candidate FVG is therefore a monitoring location; it is never an entry by itself.