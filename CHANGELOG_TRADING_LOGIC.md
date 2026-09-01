# Changelog — Trading Logic

All notable changes to the Angelique Trading Hub decision engine.

## [Second audit pass] — 2026-09-01

Follow-up corrections found while re-auditing the first hardening pass.

### Fixed

- **AMD (P1):** `RETRACEMENT_ENTRY` is now a hard requirement. An AMD
  ACCUMULATION → RAID → REACTION → DISTRIBUTION → DELIVERY sequence with price
  still extended away from the delivery zone is a completed *impulse*, not an
  entry. `detect_amd` no longer reports `complete=True` until price is actually
  inside the retracement zone, and `evaluate_amd` will not mark the sequence
  executable without that phase. Phase ordering now includes the entry phase.
- **Spread economics (P0):** `estimate_costs` no longer double-counts the
  spread. When gross risk/reward are produced by `order_calc_profit` from the
  actual executable Bid/Ask legs, the spread is already embedded in those
  prices; a separate 2x spread cost would overstate the transaction drag and
  make `net_rr` understate real economics. Callers pass
  `prices_are_executable=True`; the legacy two-leg spread remains available for
  midpoint/display-only calculations.
- **Trade levels (P0):** `calculate_trade_levels` no longer requires a generic
  structural-swing scan when the selected strategy already supplies both
  `stop_reference` and `target` in its `plan_context`. Previously a breakout
  measured move or mean-reversion mean could be rejected simply because the
  swing scanner had no data — even though the strategy had already defined the
  executable plan.
- **Broker metadata completeness (P0):** `InstrumentProfile.missing_metadata`
  now also flags missing `tick_value`, `tick_value_loss`, `trade_calc_mode`
  and `currency_profit`, not only the basic price/volume grid. This prevents an
  instrument with a name/mode guess from looking execution-complete when the
  broker calculator semantics cannot be verified.
- **Crypto market schedule (P1):** `analyze_structure` derives `trades_24_7`
  from the broker symbol profile, so crypto (including broker-suffixed crypto
  names) no longer inherits the FX weekend/closure model in data-quality and
  session gates.
- **Spread safety (P0):** the trading workflow now computes the authoritative
  `spread_model` gate on live Bid/Ask (instrument class, rolling observed
  distribution, spread-to-stop and spread-to-reward ratios) and passes that
  result to `validate_trade_setup`. The per-profile hard-coded pip/point
  ceilings are no longer the execution-spread decision; they remain as legacy
  fallback for callers that do not supply the gate.
- **Preflight net economics (P0):** `execution_preflight` now blocks with
  `BROKER_CALCULATION_UNAVAILABLE` if the net RR cannot be computed because the
  broker did not answer the take-profit `order_calc_profit`. Automatic
  execution no longer proceeds on gross RR alone.

### Tests added in this pass

- `tests/test_trading_structure.py::test_amd_is_incomplete_until_price_retraces_into_the_delivery_zone`
- `tests/test_trading_execution_math.py::test_executable_prices_do_not_double_count_the_spread`
- `tests/test_trading_execution_math.py::test_non_executable_prices_still_charge_the_spread`
- `tests/test_trading_hardening.py::test_strategy_plan_context_does_not_require_a_swing_scan`
- `tests/test_safety_calculations.py::test_spread_gate_is_authoritative_and_overrides_legacy_profile_ceiling`
- `tests/test_trading_execution_math.py::test_preflight_blocks_when_net_rr_cannot_be_computed`

## [Unreleased] — 2026-09-01

Complete correction of the trading decision engine: indicator mathematics,
scoring architecture, market-structure detection, and broker-side execution
validation.

**Nothing in the Trading Hub UI, the home page, or the visual styling was
changed.** No unrelated functionality was removed.

---

### Added

**New modules**

- `skills/trading_skill/instruments.py` — instrument classification from broker
  metadata (`trade_calc_mode`, `currency_base`/`currency_profit`, `path`,
  `description`), covering FX majors/crosses/exotics, metals, crypto, indices,
  energy and equities. `pip_size` is `None` for every non-FX instrument.
- `skills/trading_skill/market_structure.py` — protected-swing BOS/CHoCH state
  machine, liquidity pools, structural dealing range, per-candle displacement.
- `skills/trading_skill/fvg_engine.py` — FVG/IFVG lifecycle with enforced expiry,
  order blocks, sweep-continuation playbook.
- `skills/trading_skill/amd.py` — strictly ordered AMD phase machine.
- `skills/trading_skill/session_levels.py` — trading-day grouping, previous-day
  levels, DST-aware sessions, ICT kill zones, FX week model, crypto 24/7.
- `skills/trading_skill/strategy_evaluation.py` — the single authoritative
  `StrategyEvaluation` with hard requirements and weighted evidence families.
- `skills/trading_skill/strategies.py` — evidence models for SMC, AMD, trend
  following, momentum, breakout and mean reversion.
- `skills/trading_skill/spread_model.py` — raw bid/ask measurement, rolling
  session-keyed spread distribution, instrument-class-aware gates.
- `skills/trading_skill/costs.py` — transaction costs and net reward-to-risk.
- `skills/trading_skill/broker_calc.py` — broker-authoritative profit, margin and
  volume solving.
- `skills/trading_skill/execution_preflight.py` — ten-stage pre-execution gate
  ending in `OrderCheck`.

**New bridge operations** (`wine_server.py`)

- `symbol_specs` — complete read-only `symbol_info` specification for a batch of
  symbols.
- `calculate_margin` — `order_calc_margin`.
- `order_preflight` — `order_check`; validates an order without sending it.

**New tools**

- `tools/audit_broker_symbols.py` — read-only broker symbol audit producing
  `docs/BROKER_SYMBOL_CALCULATION_REPORT.md`, `broker_symbol_audit.json` and
  `broker_symbol_audit.csv`. **Never sends an order.**
- `tools/validate_trade_calculations.py` — end-to-end validation of the
  calculation chain across five instrument classes.

**New tests** (131 added)

- `tests/test_trading_indicators.py` (25)
- `tests/test_trading_strategy_scoring.py` (22)
- `tests/test_trading_structure.py` (34)
- `tests/test_trading_execution_math.py` (50)

**New documentation**

- `docs/TRADING_LOGIC_AUDIT.md`, `docs/TRADING_LOGIC_AUDIT.json`
- `CHANGELOG_TRADING_LOGIC.md`

---

### Fixed — indicator mathematics (P0)

- **RSI** used a simple rolling mean of gains and losses instead of Wilder
  smoothing. Now Wilder, verified against a published worked example (37.77).
- **ATR** was an SMA of true range and included a seed bar with no previous
  close. Now Wilder-smoothed; gaps are measured correctly.
- **ADX** returned `mean(abs(up_move - down_move)) / mean(TR)` with no
  directional indicators. Now the full DM → Wilder → ±DI → DX → ADX pipeline,
  with graded bands (20–25 is `DEVELOPING`, not a confirmed trend).
- **MACD** seeded both EMAs at `values[0]`. Now SMA-seeded, and reports
  zero-line state, cross and histogram slope.
- **Warm-up** was not enforced. `snapshot()` now gates every value to `None`
  until the indicator has converged and returns an explicit readiness map.
  Candle depth in `profiles.py` is derived from these requirements.
- Forming candles (`closed=False`) are stripped before every calculation.

### Fixed — scoring architecture (P0)

- **Removed the dual scoring system.** `strategy_engine`'s hard-coded candidate
  scores (SMC 8, AMD 9, TREND 7, MOMENTUM 6, BREAKOUT 6, MEAN_REVERSION 5) are
  deleted; `confluence` is now a view of the selected strategy's own evaluation.
- **Hard requirements can never be overridden by score.** A setup scoring 100
  with one failed hard requirement is not executable.
- **Correlated evidence no longer double counts** — within an evidence family
  the score is the weighted mean, not the sum.
- The score is named `strategy_quality_score`, is on a 0–100 scale, and is
  documented and asserted **not** to be a win probability.
- **Strategies read timeframes from the `TradingProfile`.** DAY and SWING now
  genuinely evaluate different data.

### Fixed — strategy logic

- **Momentum (P0):** reported READY when MACD and the entry timeframe agreed
  even if RSI was on the wrong side and the higher timeframe disagreed. All
  four are now hard requirements, plus an RSI exhaustion guard.
- **Trend following (P1):** added fresh-pullback and not-overextended hard
  gates. A trend existing is not the same as a low-risk entry.
- **Breakout (P1):** added range-quality, closed-break, displacement,
  liquidity-spike and acceptance gates, and a measured-move target that the
  trade-level builder actually uses.
- **Mean reversion (P1):** a non-trending regime and band re-entry are now hard
  gates. A band touch with an extreme RSI is no longer treated as a reversal.

### Fixed — market structure (P0)

- **BOS/CHoCH** was `close > max(high of the last five bars)`. Now a
  closed-candle break of a confirmed **protected swing**, tracked by a forward
  state machine. Wicks never confirm.
- **Liquidity sweeps** were a poke beyond the prior five bars. Now a raid of an
  identified pool (confirmed swing, equal highs/lows, or a session/day level)
  with a required reclaim and a recency window.
- **Dealing range** was `max/min` of the last 200 candles. Now anchored to the
  impulse leg of the most recent structure event, with the basis reported.
- **Swings** now require right-hand confirmation before being used.

### Fixed — FVG / IFVG / AMD (P0)

- **FVG displacement** was read from the *latest* candle's flag. Now measured on
  the candle that actually created the gap.
- **FVG retest expiry** was never enforced. Zones now carry an expiry, and a
  touch after it cannot revive them.
- **IFVG source qualification:** any invalidated FVG became an IFVG candidate.
  Inversions now inherit their source's qualification and require a retest.
- **AMD sequencing:** a fixed 20/10-candle window let a later, unrelated candle
  retroactively complete the sequence. Phases are now searched strictly after
  the previous phase ends, and an accumulation range can no longer swallow its
  own raid.
- **Sweep continuation** no longer resurrects stale events; it returns a precise
  status instead.

### Fixed — sessions (P0)

- **`previous_day_high`/`previous_day_low` returned the all-time high/low** of
  the loaded history. Now computed from the single immediately preceding trading
  day, in an explicit timezone with an explicit rollover hour, with weekend and
  holiday gaps reported.
- Added DST-aware session windows, kill zones, the FX week boundary, and 24/7
  handling for crypto.

### Fixed — broker execution (P0)

- **Instrument classification** used symbol-name substrings and had no crypto,
  index or energy classes. Now driven by broker metadata; FX pip assumptions can
  no longer reach metals or crypto.
- **`loss_per_lot`** fell back to `(distance / tick_size) * tick_value`, which is
  wrong for cross-currency instruments (roughly 155× for GBPJPY on a USD
  account). `order_calc_profit` is now authoritative; the estimate is labelled
  non-authoritative and refused for execution.
- **Margin** came from a stored scalar. `order_calc_margin` is now authoritative.
- **Execution blocks** with `BROKER_CALCULATION_UNAVAILABLE` or
  `BROKER_METADATA_INCOMPLETE` rather than guessing.
- **Volume** is floored onto the broker's grid and then **re-verified with the
  broker** at the normalised volume; rounding is never assumed safe.
- **`stops_level` / `freeze_level`** were never validated, causing retcode 10016
  rejections. Now validated against the correct side of the book with a
  configurable 1.5× safety buffer, and prices are snapped to the tick grid.
- **Spread** ceilings were hard-coded constants. Now measurement, rolling
  observation and policy are separated, with relative gates (spread vs stop
  distance, spread vs reward) that apply to every instrument.
- **Net RR** after spread, commission, swap and slippage is computed and
  enforced alongside gross RR.
- **`OrderCheck`** now runs as the final gate before every execution.

### Fixed — supporting systems

- **News (P0):** relevance is now derived from the broker's currency fields, so
  a US event is no longer "relevant" to EURGBP. News **never** adjusts the
  technical score; a relevant imminent high-impact event routes the plan to
  manual approval instead.
- **Position monitoring (P1):** R-multiples were measured from the mid price,
  overstating every long by half the spread. Positions are now valued at the
  price that would close them. Management is per-strategy — mean reversion no
  longer breaks even at +1R and scratches itself before reaching the mean.
- **Portfolio exposure (P1):** lots were treated as currency units. Exposure is
  now true notional from `contract_size` and price, aggregated across the book.
- **Correlation (P1):** two candle lists were zipped by position. Series are now
  aligned by timestamp, with sample counts reported.
- **Data quality (P1):** a single `stale` status conflated a closed market with a
  broken feed. Now distinct blocker codes, schedule-aware freshness and gap
  detection.

---

### Changed

- `core/price_units.py` is now a thin compatibility layer over
  `instruments.py`. Public signatures are unchanged; `pip_size_from_specs`
  returns `0.0` for instruments that have no pip.
- `profiles.py` gains `minimum_quality_score` (default 70) and derives
  `candle_count()` from the indicator warm-up table.
- `TradePlan.analysis_audit` gains an `authoritative` block containing every
  value the execution decision used, so the UI never recomputes anything.
- `context.py` no longer overwrites `detect_smc`'s sequenced AMD and
  lifecycle-correct IFVG results with the older heuristic detectors.

---

### Verification

- **Test suite: 165 passed, 1 skipped.**
- **`tools/validate_trade_calculations.py`: 89/89 checks** across FX major, FX
  cross, metal, crypto and index.
- One pre-existing, unrelated failure remains
  (`test_execute_tool_requires_canonical_registry`, caused by a missing
  `pytesseract` dependency in the vision skill).

### NOT verified

The live MT5 symbol audit, broker calculator agreement, a real `OrderCheck`
response, any backtest, and live or demo execution have **not** been performed.
Every threshold is a policy default and is not statistically calibrated.

**This release must not be described as production ready.** See
`docs/TRADING_LOGIC_AUDIT.md` §11 for the required steps before live use.
