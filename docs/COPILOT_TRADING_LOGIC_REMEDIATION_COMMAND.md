# Copilot Command — Trading Hub Logic Remediation

Use the block below as a Copilot (or other coding agent) command to finish /
verify the Angelique Trading Hub hardening. It includes the items already
corrected in this branch and the strict live-broker audit that has NOT been
possible in the current sandbox.

---

```text
TASK: FINISH AND VERIFY THE ANGELIQUE TRADING HUB TRADING ENGINE — PRODUCTION-GRADE LOGIC ONLY

You are working in /home/user/project-Angelique on branch
arena/01a05ba2-project-angelique. Do NOT redesign the Trading Hub UI, the home
page, or any visual styling. Do NOT remove unrelated functionality.

The tick life is: broker MT5 metadata -> raw bid/ask -> instrument profile ->
strategy evidence -> single 0-100 setup-quality score -> trade levels ->
broker-solved risk/margin -> instrument-aware spread gate -> net RR ->
OrderCheck -> broker order.

MANDATORY BROKER DATA AUDIT (read-only, NO orders):
1. Run `python tools/audit_broker_symbols.py --mode demo --broker Valetax` (or
   the broker name from core.config). If no MT5/Wine bridge is reachable, print
   UNVERIFIED and stop claiming execution safety.
2. Enumerate ALL broker symbols. For EVERY symbol persist: name, path,
   description, visible, selected, currency_base/profit/margin,
   trade_calc_mode, trade_mode, trade_exemode, filling_mode, digits, point,
   trade_tick_size, trade_tick_value, trade_tick_value_profit,
   trade_tick_value_loss, trade_contract_size, volume_min/max/step/limit,
   trade_stops_level, trade_freeze_level, spread, spread_float, swap_long,
   swap_short, swap_mode, bid, ask, last, time, time_msc.
3. Derive raw_spread_price = ask-bid, spread_points, spread_ticks, FX pip
   where a pip is real, mid. Classify into FX_MAJOR / FX_CROSS / FX_EXOTIC /
   METAL / CRYPTO / INDEX / ENERGY / EQUITY / OTHER from broker metadata, never
   from the symbol string alone (EURUSD.VX, EURUSDm, XAUUSD.a, BTCUSD_a must
   resolve correctly).
4. For representatives in every class, test order_calc_profit (BUY and SELL)
   and order_calc_margin (BUY and SELL) at entry +/- tick(s), and compare to the
   local tick-value approximation. Broker result is authoritative. Report
   divergence per symbol. NEVER force Tester to match the broker.
5. Produce data/broker_symbol_audit_<server>_<timestamp>.json and .csv and a
   fully populated docs/BROKER_SYMBOL_CALCULATION_REPORT.md. Record orders_sent=0.

IMPLEMENTATION RULES (already fixed in this branch, verify + keep in sync):
- RSI/ATR/ADX/MACD/Bollinger must be textbook; no simple-mean substitutes; no
  forming candles; no "ready" before warm-up. Keep the existing reference tests.
- ONE scoring engine. strategy_quality_score means completeness of the
  strategy's own setup, NOT win probability. Hard requirements can never be
  out-scored. Strategy timeframes come from TradingProfile.
- Momentum cannot be READY while RSI/HTF/entry evidence fails. Trend needs a
  real pullback, not just an EMA stack. Breakout needs range quality + closed
  break + displacement + acceptance. Mean reversion needs a non-trending regime
  + real band re-entry, not merely a band touch plus extreme RSI.
- SMC: BOS/CHoCH from confirmed protected swings; liquidity sweep from real
  liquidity pools (confirmed swing / equal highs-lows / prior day/session);
  dealing range anchored to the structural leg; FVG qualified by the
  displacement candle that formed it.
- FVG: enforce retest expiry; an expired zone must never be revived; IFVG must
  inherit the source FVG qualification; sweep-continuation picks the most recent
  valid event with expiry + price relevance.
- AMD must be strictly ordered ACCUMULATION -> RAID -> REACTION -> DISTRIBUTION
  -> STRUCTURAL DELIVERY -> RETRACEMENT/ENTRY. RETRACEMENT_ENTRY is a HARD gate:
  a completed impulse is not an entry.
- Previous-day high/low must be the immediately preceding trading day in the
  configured timezone / market schedule; crypto is 24/7 and must never inherit
  the FX weekend model.
- Spread: derive from raw bid/ask, normalize per instrument class, use rolling
  observed distribution, spread-to-stop and spread-to-reward ratios. Remove
  universal hard-coded pip/point assumptions from execution safety.
- Net RR: use gross risk/reward from broker calculators using actual executable
  Bid/Ask legs; DO NOT double count the spread. Charge commission and swap
  where known. Block on unsafe net RR where data is sufficient.
- Trade levels: validate tick_size/digits/stops_level/freeze_level and correct
  side (BUY SL/TP vs Bid, SELL SL/TP vs Ask). If a strategy supplies both
  stop_reference and target, do not require a generic swing scan.
- Risk/margin: MT5 order_calc_profit / order_calc_margin are the only execution
  sources. Solve volume, floor to broker volume grid, RE-VERIFY with the broker,
  never exceed the risk budget, and block with
  BROKER_METADATA_INCOMPLETE / BROKER_CALCULATION_UNAVAILABLE instead of using a
  generic fallback.
- News: relevant currencies/assets from broker metadata; a high-impact event that
  is not relevant to the instrument must not force manual review; news never
  changes the technical score.
- Portfolio/correlation: align return series by timestamp; exposure must be real
  notional/account-currency exposure, not lots.
- Position monitor: BUY closes at Bid; SELL closes at Ask; trailing/break-even
  respect tick grid, stops_level and freeze_level.

VERIFICATION DELIVERABLES:
- pytest (trading modules), python -m compileall
- docs/TRADING_LOGIC_AUDIT.md + docs/TRADING_LOGIC_AUDIT.json (item: defect,
  severity, correction, formula, test)
- CHANGELOG_TRADING_LOGIC.md
- BROKER_SYMBOL_CALCULATION_REPORT.md + broker JSON/CSV ONLY if the live audit
  actually ran
- Final report MUST explicitly state whether: broker audit was performed,
  broker calculations were observed, expectancy/backtest was run, live/demo
  execution was tested. If any of these were NOT done, say "UNVERIFIED" and do
  not call the system production-ready.
```
