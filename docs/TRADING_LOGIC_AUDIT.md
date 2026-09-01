# Trading Logic Audit

Audit and remediation of the Angelique Trading Hub decision engine.

- **Date:** 2026-09-01
- **Branch:** `arena/01a05aa9-project-angelique`
- **Baseline commit:** `67920e7`
- **Scope:** `skills/trading_skill/`, `core/price_units.py`, `tools/`, `tests/`
- **Out of scope (deliberately untouched):** the Trading Hub UI, the home page,
  visual styling, and every non-trading skill.

---

## 1. Executive summary

The engine produced trade decisions from mathematics that did not match the
indicators it claimed to use, ranked strategies with two mutually inconsistent
scoring systems, applied FX pip assumptions to gold and crypto, and computed
monetary risk from a generic tick-value formula that is invalid for
cross-currency instruments.

Every P0 item is now fixed. The engine has one score, one authoritative
execution object, and refuses to size or send a trade it cannot prove with the
broker's own calculators.

### What actually changed, in one line each

| # | Defect | Status |
|---|---|---|
| 1 | RSI used a simple mean instead of Wilder smoothing | **Fixed** |
| 2 | ATR was an SMA of true range, not Wilder | **Fixed** |
| 3 | "ADX" was `mean(abs(up-down))/mean(TR)` with no +DI/-DI | **Fixed** |
| 4 | MACD seeded both EMAs at `values[0]` | **Fixed** |
| 5 | Indicators returned values before warm-up | **Fixed** |
| 6 | Two competing scoring systems | **Fixed** |
| 7 | Hard-coded candidate scores (SMC 8, AMD 9, ...) | **Removed** |
| 8 | Strategies hard-coded H1/M15/M5 regardless of profile | **Fixed** |
| 9 | Momentum reported READY while RSI/HTF evidence failed | **Fixed** |
| 10 | BOS = close beyond a 5-bar window high | **Fixed** |
| 11 | Liquidity sweep = poke beyond the last 5 bars | **Fixed** |
| 12 | Dealing range = max/min of the last 200 candles | **Fixed** |
| 13 | FVG displacement read from the *latest* candle | **Fixed** |
| 14 | FVG retest expiry never enforced | **Fixed** |
| 15 | Any invalidated FVG became an IFVG candidate | **Fixed** |
| 16 | AMD phases could complete out of order | **Fixed** |
| 17 | Previous-day high/low was the all-time high/low | **Fixed** |
| 18 | Instruments classified by symbol-name substring | **Fixed** |
| 19 | `loss_per_lot` fell back to `distance/tick_size*tick_value` | **Fixed** |
| 20 | Margin from a stored `margin_per_volume` scalar | **Fixed** |
| 21 | RR was distance-only; costs ignored | **Fixed** |
| 22 | `stops_level` / `freeze_level` never validated | **Fixed** |
| 23 | Spread ceilings hard-coded per bucket | **Fixed** |
| 24 | News adjusted the technical score | **Fixed** |
| 25 | Position R-multiples measured from the mid price | **Fixed** |
| 26 | Portfolio exposure treated lots as currency units | **Fixed** |
| 27 | Correlation zipped two unaligned candle lists | **Fixed** |
| 28 | `stale` conflated a closed market with a broken feed | **Fixed** |
| 29 | No `OrderCheck` before execution | **Fixed** |
| 30 | Same management rules for every strategy | **Fixed** |

---

## 2. Indicator mathematics

### 2.1 RSI

**Was:** the mean of the last *n* gains divided by the mean of the last *n*
losses — a rolling simple average, not Wilder's smoothing. The value drifts
away from every charting platform's RSI, and the divergence grows with history.

**Now:** Wilder's recursive smoothing, seeded with the first *n*-period simple
average:

```
avg_gain[t] = (avg_gain[t-1] * (n - 1) + gain[t]) / n
avg_loss[t] = (avg_loss[t-1] * (n - 1) + loss[t]) / n
RSI         = 100 - 100 / (1 + avg_gain / avg_loss)
```

**Verification:** the implementation reproduces the published StockCharts RSI-14
worked example to two decimal places (`37.77`). This is asserted in
`tests/test_trading_indicators.py::test_rsi_matches_published_wilder_reference`,
and a companion test proves the simple-average variant gives a materially
different answer, so the old behaviour cannot silently return.

### 2.2 ATR

**Was:** an SMA of true range, and the seed bar (which has no previous close)
was included with an incorrect true range.

**Now:** true range is `max(H-L, |H - C_prev|, |L - C_prev|)`, the seed bar is
dropped, and the average is Wilder-smoothed. Gaps are now measured; previously a
gap-up candle reported only its own high-low.

### 2.3 ADX / DMI

**Was:** `mean(abs(up_move - down_move)) / mean(TR)`. There were no directional
indicators at all, so the engine could not tell a strong uptrend from a strong
downtrend, and the number was not on the ADX scale.

**Now:** the full pipeline — directional movement, Wilder smoothing, +DI/-DI,
DX, and a second smoothing pass for ADX. `dmi()` returns `plus_di`, `minus_di`,
`dx` and `adx`.

ADX is also **graded rather than binary**. The old `ADX > 25 = trending` test
treated 24.9 and 5.0 identically:

| Band | Range | Meaning |
|---|---|---|
| `NO_TREND` | < 15 | No directional pressure |
| `WEAK` | 15–20 | Directional bias forming |
| `DEVELOPING` | 20–25 | Transitional — **not** a confirmed trend |
| `TRENDING` | 25–40 | Established trend |
| `STRONG_TREND` | 40–50 | Strong trend |
| `EXTREME` | > 50 | Possibly exhausted |

`DEVELOPING` is deliberately not accepted by the trend-following hard gate.

### 2.4 MACD and EMA

**Was:** both EMAs seeded at `values[0]`, so a single opening price dominated
the 26-period EMA for a long time and the histogram was wrong early in the
series.

**Now:** every EMA is seeded with the SMA of its first `period` values. MACD
additionally reports `zero_line_state`, `cross` and `histogram_slope` so the
strategy layer can grade momentum instead of only reading its sign.

### 2.5 Warm-up gating

**Was:** any indicator returned a number as soon as it had `period` candles. A
"200 EMA" computed from 205 candles is dominated by its seed, and the engine
treated it as authoritative.

**Now:** `warmup_for()` defines a convergence requirement per indicator family
and `snapshot()` returns `None` for anything not yet warmed up, plus an explicit
`readiness` map:

| Indicator | Required closed candles |
|---|---|
| EMA 20 / 50 / 200 | 30 / 75 / **300** |
| RSI 14 | 71 |
| ATR 14 | 71 |
| ADX 14 | 85 |
| MACD (12/26/9) | 87 |
| Bollinger 20 | 20 |

Wilder indicators use `5 x period` (plus a second pass for ADX); SMA-seeded EMAs
use `period + period/2`, at which point the seed's geometric influence is a few
percent. `profiles.candle_count()` is now derived from these numbers rather than
from round figures, so the engine requests enough history to answer its own
questions. Forming candles (`closed=False`) are stripped before any calculation.

---

## 3. The scoring architecture

### 3.1 The problem

There were two scoring systems:

- `strategy_engine.select_strategy` ranked strategies on **hard-coded constants**
  (SMC 8, AMD 9, TREND 7, MOMENTUM 6, BREAKOUT 6, MEAN_REVERSION 5). AMD always
  outranked SMC because 9 > 8, irrespective of what the market was doing.
- `confluence.evaluate_confluence` independently produced a 0–14 score clamped
  to 0–10 with a minimum of 7.

`analysis.py` ran both. The selector could choose AMD while confluence rated
SMC higher, and nothing reconciled them.

### 3.2 The fix

One class, `strategy_evaluation.StrategyEvaluation`, is now the only scoring
object. `confluence.evaluate_confluence` is a *view* of the selected strategy's
evaluation, so the two can no longer disagree. The hard-coded constants are gone.

### 3.3 Hard requirements vs weighted evidence

- A **hard requirement** is binary and gating. If any fails, `setup_complete` is
  `False` no matter what the score is. This is tested directly: a setup with a
  score of 100 and one failed hard requirement is not executable.
- **Soft evidence** grades quality inside an evidence *family*. Within a family
  the score is the weighted **mean** of its observations, not their sum, so
  correlated signals cannot each award full points. Three momentum indicators
  agreeing is one piece of evidence about momentum, not three.

### 3.4 What `strategy_quality_score` means

It answers exactly one question:

> How completely does this setup satisfy **this strategy's own** evidence
> requirements?

It is **not** a probability, and nothing in the codebase converts it into one.
70 does not mean a 70% chance of winning. Two strategies both scoring 80 are not
equally likely to win — they are each 80% complete against different evidence
models. The `score_meaning` string is attached to every serialised evaluation,
and a test asserts that no key in the payload implies a win rate.

The default `minimum_quality_score` of 70 is **policy**, not a calibrated
threshold. It has not been backtested.

### 3.5 Ranking

Complete setups always outrank incomplete ones, regardless of score. Within each
group, ranking is by score, then by how many hard requirements the strategy
enforces, then alphabetically for determinism.

---

## 4. Strategy evidence models

Every strategy reads its timeframes from the `TradingProfile`, so switching
DAY → SWING genuinely changes which data is evaluated. Previously
`_trend_following` was hard-coded to H1 and `_momentum`/`_breakout`/
`_mean_reversion` to M15 even in SWING mode.

| Strategy | DAY | SWING |
|---|---|---|
| Context | H4 | W1 |
| Trend | H1 | D1 |
| Structure / setup | M15 | H4 |
| Entry | M5 | H1 |

### 4.1 Trend following

Hard: EMA 20/50/200 stacked directionally; ADX ≥ 25 **with** the agreeing DI;
higher-timeframe agreement; a **fresh pullback** (≤ 1 ATR from the anchor EMA);
not overextended (≤ 3 ATR).

The pullback gate is the substantive addition. "A trend exists" and "there is a
low-risk entry" are different claims, and the engine previously conflated them —
it would enter 3 ATR into an extended move.

### 4.2 Momentum (P0 readiness bug)

**Was:** READY required `rsi >= 55 and histogram > 0 and trend == bullish` in the
selector, while `confluence` used its own 55/45 thresholds and listed RSI/HTF
failures in `missing` without enforcing them. A setup with bullish MACD, RSI 41,
and a bearish H1 reported READY.

**Now:** MACD regime, RSI on the correct side, RSI not exhausted, HTF context,
and entry confirmation are all **hard** requirements. RSI is additionally graded
by distance from the midline, so 66 scores better than 51 without 51 being an
automatic pass. This is covered by three dedicated tests.

### 4.3 Breakout

Hard: a genuine tested range (≥ 1 ATR wide, ≥ 3 boundary touches); a **closed**
candle beyond the boundary; displacement; **not a liquidity spike** (wick beyond
the close < 50% of the candle range); **acceptance** (close in the top/bottom 30%
of the break candle); and a target that yields at least the minimum RR.

The measured-move target computed here is passed to the trade-level builder, so
the executed target is the target that was scored.

### 4.4 Mean reversion

Hard: a **non-trending regime** (ADX < 20 and no directional HTF trend), no
opposing higher-timeframe trend, a real excursion, **price re-entering the band**,
and a viable target.

The re-entry requirement is the fix. Being outside a Bollinger band with an
extreme RSI is not a reversal — price can sit there for an entire trend. The
regime check is a hard gate specifically so a high score cannot drag the engine
into fading a strong trend.

### 4.5 SMC

Hard: a closed-candle break of a **protected swing**; an unexpired directional
FVG or order block; not being in the wrong half of the dealing range; HTF
agreement.

Nine evidence families: higher-timeframe structure, liquidity, structure break,
entry zone, dealing-range location, displacement, entry confirmation, execution
timing, freshness.

### 4.6 AMD

Every phase is a hard requirement **and so is their ordering**. See §6.

---

## 5. Market structure

### 5.1 Break of structure

**Was:** `close > max(high of candles[-6:-1])` — a close above any five-bar high.
In a quiet range this fires constantly and means nothing.

**Now:** a state machine walks the series forward maintaining bias, a protected
high and a protected low. A **protected swing** is the most recent confirmed
swing whose break changes or extends structure. Breaking it with a **closed
candle** in the direction of bias is a BOS; breaking the opposite one is a CHoCH.
Wicks never confirm. Every event carries the swing index it broke, the level, the
break index and a timestamp.

Swings themselves now require right-hand confirmation: a swing at index *i* with
strength *s* is only usable once *i + s* candles have closed.

### 5.2 Liquidity

**Was:** a poke beyond the prior five bars.

**Now:** liquidity is an identified **pool** — a confirmed swing, an
equal-highs/equal-lows cluster, or an external session/day level. A raid is only
valid when price traded through a pool *and* closed back on the origin side
within the recency window. Pools carry a strength (touch count) so an equal-highs
cluster is treated as more significant than a single swing.

### 5.3 Dealing range

**Was:** `max/min` of the last 200 candles. Premium/discount was measured against
an arbitrary window that had no relationship to what the market was trading.

**Now:** the range is anchored, in preference order, to (1) the impulse leg
created by the most recent structure event, (2) the last confirmed swing pair, or
(3) a bounded recent window, which is explicitly flagged as a fallback. The basis
is reported so the reason for a premium/discount call is auditable. The OTE band
(0.62–0.79) is oriented by which side of the leg formed last.

---

## 6. FVG, IFVG and AMD lifecycle

### 6.1 Displacement association (P0)

**Was:** `associated_displacement` was read from the flag on the **latest**
candle. A gap formed 40 candles ago was marked as displacement-backed because
the most recent candle happened to be large.

**Now:** displacement is measured on the middle candle of the three-candle
formation — the candle that actually created the gap — and stored with its own
index and timestamp.

### 6.2 Retest expiry (P0)

**Was:** never enforced. A gap from 200 candles ago was still "valid".

**Now:** every gap has `formation_index`, `expiry_index` and a status. A touch
after `expiry_index` **cannot** revive the zone; it is `EXPIRED`. Statuses:
`UNTOUCHED`, `PARTIALLY_MITIGATED`, `FULLY_MITIGATED`, `INVALIDATED`, `EXPIRED`.

Classification is separate from status: `TECHNICAL_FVG` (a gap exists),
`QUALIFIED_FVG` (displacement + structure alignment), `TRADEABLE_FVG`
(qualified, unexpired, unmitigated and in range).

### 6.3 IFVG source qualification (P0)

**Was:** any `INVALIDATED` FVG became an IFVG candidate.

**Now:** an inversion inherits its source's qualification. A merely technical gap
that was blown through does not become a tradeable IFVG. Confirmation
additionally requires a retest of the inverted zone from the new side inside the
retest window.

### 6.4 Sweep continuation

Requires a recent valid raid, a confirmed structure shift in the implied
direction that occurred **after** the raid, an unexpired qualified entry zone
formed in the impulse, and price still within a sane ATR distance of that zone.
Otherwise it returns a precise status (`expired`, `awaiting_confirmation`,
`no_entry_zone`, `out_of_range`) rather than resurrecting an old setup.

### 6.5 AMD sequencing

**Was:** a fixed 20-candle accumulation window plus a 10-candle post window, with
distribution decided from `follow[-1]` — so the last candle of the whole window
could retroactively complete the sequence even after unrelated price action.

**Now:** a strictly ordered phase machine:

```
ACCUMULATION -> MANIPULATION -> REACTION -> DISTRIBUTION
             -> STRUCTURAL_DELIVERY -> RETRACEMENT_ENTRY
```

Each phase is searched only in the window **after** the previous phase ended, so
ordering is structurally guaranteed rather than checked afterwards. Several
accumulation candidates are evaluated and the most advanced ordered sequence
wins. A candidate range can never extend into its own raid — the bug that
previously let the accumulation swallow the manipulation. Every phase carries
start/end indices, timestamps and a human-readable reason, and the completed
sequence expires after a configurable number of candles.

---

## 7. Sessions and daily levels

**Was:** `previous_day_high` was the maximum high of *every candle before today*
— effectively the all-time high of whatever history was loaded. Any strategy
using it as a liquidity target was aiming at a meaningless level.

**Now:** candles are grouped into trading days in an explicit timezone with an
explicit rollover hour (17:00 New York for FX/metals, matching the MT5 daily
bar). Previous-day levels come from the **single immediately preceding trading
day that has data**, and that day is reported so a Monday correctly shows Friday.

The regression test seeds a 500.0 spike into day 0 and asserts it does not appear
in the previous-day level on day 4.

Also added: DST-aware session windows defined in each market centre's local time
(so the London/NY overlap survives DST transitions), ICT kill zones, an FX
week-boundary model (Friday 17:00 NY → Sunday 17:00 NY closed), and a `24/7`
mode for crypto that uses plain UTC calendar days and never reports the market
closed.

---

## 8. Broker as the source of truth

### 8.1 Instrument classification

**Was:** `is_metal_symbol()` matched substrings such as `XAU` and `GOLD`. It
failed for broker-suffixed and micro symbols, and there was no crypto, index or
energy classification at all, so those instruments fell through to FX handling.

**Now:** `instruments.build_profile()` classifies from broker metadata in
priority order: `trade_calc_mode` → `currency_base`/`currency_profit` → `path` →
`description` → symbol name (last resort only).

Classes: `FX_MAJOR`, `FX_CROSS`, `FX_EXOTIC`, `METAL`, `CRYPTO`, `INDEX`,
`ENERGY`, `EQUITY`, `OTHER`.

**`pip_size` is `None` for every non-FX instrument, and `to_pips()` returns
`None`.** It is therefore structurally impossible to compare an FX pip limit
against gold. `core/price_units.py` is now a thin compatibility layer over this
module.

### 8.2 Profit and margin

**Was:** `loss_per_lot` fell back to `(distance / tick_size) * tick_value`. That
is correct only when the profit currency is the account currency. For GBPJPY on a
USD account it is wrong by the JPY/USD rate — roughly a factor of 155. Margin
came from a stored `margin_per_volume` scalar.

**Now:** `order_calc_profit` and `order_calc_margin` are the only trusted sources
for execution. When either is unavailable the engine **blocks** with
`BROKER_CALCULATION_UNAVAILABLE` or `BROKER_METADATA_INCOMPLETE`. The tick-value
path still exists for display, is labelled `authoritative=False`, and is refused
outright when `require_authoritative=True`.

`solve_volume_for_risk` asks the broker for the loss at a probe volume, divides
the budget by it, floors onto the `volume_step` grid, and then **re-asks the
broker** for the loss at the normalised volume, stepping down until the figure is
inside the ceiling. Rounding is never assumed safe.

The offline validator models the JPY→USD conversion explicitly so this class of
error is exercised rather than assumed away.

### 8.3 Stops level and freeze level

**Was:** never checked. Orders were sent and rejected with retcode 10016.

**Now:** every price is snapped to `tick_size`/`digits`, and SL/TP are validated
against the **correct side of the book** — Bid for a BUY, Ask for a SELL — with a
configurable 1.5× safety buffer over the broker's raw minimum, because brokers
widen `stops_level` intra-session. Freeze level produces a warning that
modification will be rejected while price stays that close.

### 8.4 Spread

**Was:** hard-coded ceilings (1.5 pips DAY, 3.0 SWING, 350 points metals)
presented as if they were market truth.

**Now:** three separated concerns —

1. **Measurement:** `ask - bid`, normalised through the broker's own `point`,
   `tick_size` and FX pip convention. This is fact.
2. **Observation:** a rolling, session-keyed distribution of the spreads this
   broker has actually shown for this symbol. A spread above the 90th percentile
   of the last N observations is rejected as abnormal widening (skipped until
   there are enough samples to be meaningful).
3. **Policy:** configurable ceilings per instrument class in that class's natural
   unit, plus — more importantly — **relative** gates: spread as a fraction of
   the stop distance (default 15%) and of the expected reward (default 8%).

The relative gates are the substantive ones. A 2-pip spread is irrelevant on a
200-pip swing stop and fatal on a 6-pip scalp stop; a single absolute ceiling
cannot express that. All policy numbers are documented as **not backtested**.

### 8.5 Net reward-to-risk

**Was:** RR was `|target - entry| / |entry - stop|`. Costs were invisible.

**Now:** `costs.py` monetises spread (charged on entry and exit), commission,
swap for the expected holding period, and expected slippage, using the broker's
money-per-price-unit rather than a generic tick value. Costs are charged to
**both** sides: they increase effective risk and reduce effective reward, which
is what actually happens.

Both `gross_rr` and `net_rr` are reported from the same inputs, and net RR is
enforced at the safety gate and in preflight. In the validator, a 3.00 gross RR
becomes 2.85 net on EURUSD with a 1-pip spread and $3.50/lot/side commission —
and a 20-pip spread turns a nominal 3.00 into a rejection.

### 8.6 Order preflight

A ten-stage gate now runs immediately before execution, because everything
computed during analysis is stale by definition by the time a human clicks
execute:

1. Account and symbol trade permissions
2. Market state
3. Quote and plan freshness
4. Price drift versus the planned entry
5. Spread (recomputed on the live tick)
6. Level revalidation against the live book
7. Volume re-solved and re-verified with the broker
8. `order_calc_margin` plus the resulting margin level
9. Net economics after live costs
10. **`OrderCheck`** — the broker's own verdict

Every failure returns a machine-readable code (`MARKET_CLOSED`, `QUOTE_STALE`,
`PLAN_STALE`, `PRICE_DRIFT`, `SPREAD_UNACCEPTABLE`, `STOPS_LEVEL_VIOLATION`,
`INSUFFICIENT_MARGIN`, `MARGIN_LEVEL_TOO_LOW`, `NET_RR_BELOW_MINIMUM`,
`ORDER_CHECK_FAILED`, `BROKER_METADATA_INCOMPLETE`,
`BROKER_CALCULATION_UNAVAILABLE`, `VOLUME_OUT_OF_RANGE`, `TRADE_DISABLED`).
There is no "proceed anyway" path.

The bridge gained `symbol_specs`, `calculate_margin` and `order_preflight`
operations, and `market()` now returns the complete `symbol_info` specification
instead of a partial subset.

---

## 9. News, portfolio, monitoring, data quality

### 9.1 News relevance

**Was:** relevance was a substring test against the raw symbol, and news
adjusted the technical score by up to −2.

**Now:** relevance comes from the broker's `currency_base`/`currency_profit`
(plus asset keywords such as GOLD → XAU, BITCOIN → BTC), so a US NFP headline is
correctly **not** relevant to EURGBP. Calendar events are matched on their own
currency field.

`score_adjustment` is now **always 0**. A news release does not make a chart
pattern better or worse; it changes execution risk (spread widening, slippage,
gapping). A relevant imminent high-impact event therefore sets
`requires_manual_approval` and routes the plan to explicit human approval,
leaving the technical score untouched.

### 9.2 Portfolio exposure

**Was:** `currency_exposure` treated `volume` (lots) as a currency amount and
applied the same number to both legs.

**Now:** exposure is true notional. One lot of EURUSD at 1.10 is `+100,000 EUR`
and `-110,000 USD`, derived from `contract_size` and price.
`portfolio_exposure()` aggregates net and gross exposure per currency across the
book, so three EURUSD-correlated longs are visible as one concentrated EUR bet
rather than three independent 1% risks. When contract size or price is missing,
the result is explicitly marked partial rather than reported as notional.

### 9.3 Correlation

**Was:** two candle lists were zipped by position. Different sessions, holidays
or one missed bar shift the series and the function then correlates Monday
against Tuesday.

**Now:** `align_series()` pairs closes by **timestamp** and only shared
timestamps are used. The result reports `aligned_bars`, `samples` and
`unaligned_bars_dropped`, and returns `None` below a minimum sample count instead
of a confident but meaningless number.

### 9.4 Position monitoring

**Was:** `current = market["price"]` (the mid). This overstates every long's
R-multiple by half the spread and can trigger break-even or trailing before the
move has actually happened. Break-even at +1R and an ATR trail at +2R were
hard-coded for every strategy.

**Now:** a position is valued at the price that would **close** it — Bid for a
long, Ask for a short — and the basis is reported. Management is per-strategy via
`STRATEGY_MANAGEMENT`. Notably, mean reversion has **no** break-even at +1R,
because moving to break-even routinely scratches the trade a few candles before
the mean is reached; its target is terminal instead. These are documented as
policy defaults.

### 9.5 Data quality

**Was:** one `stale` status with `maximum_age = interval * 3` and no market
schedule awareness, so a normal Saturday looked identical to a broken feed.

**Now:** distinct statuses and blocker codes — `NO_DATA`, `MALFORMED_DATA`,
`MISSING_TIMESTAMPS`, `INSUFFICIENT_HISTORY`, `FEED_BEHIND`, `MARKET_CLOSED`,
`HISTORY_GAPS`. Freshness is evaluated against the instrument's trading schedule,
and gaps in the history are detected and counted separately from staleness. The
minimum-history gate is derived from the indicator warm-up table rather than a
hard-coded 200.

---

## 10. Configuration

Every threshold is configurable and none is claimed to be statistically proven.

| Setting | Default | Where |
|---|---|---|
| `minimum_quality_score` | 70 | `profiles.py` |
| `WILDER_CONVERGENCE_MULTIPLE` | 5 | `indicators.py` |
| `DEFAULT_MAX_RETEST_CANDLES` | 8 | `fvg_engine.py` |
| `DEFAULT_MAX_AGE_CANDLES` | 40 | `fvg_engine.py` |
| `AMDConfig.*` windows | 12/60/15/6/12/20 | `amd.py` |
| `max_spread_to_stop_ratio` | 0.15 | `spread_model.py` |
| `max_spread_to_reward_ratio` | 0.08 | `spread_model.py` |
| `max_observed_percentile` | 0.90 | `spread_model.py` |
| `STOPS_LEVEL_BUFFER_MULTIPLE` | 1.5 | `trade_levels.py` |
| `max_quote_age_seconds` | 10 | `execution_preflight.py` |
| `max_plan_age_seconds` | 300 | `execution_preflight.py` |
| `max_price_drift_ratio` | 0.25 | `execution_preflight.py` |
| `minimum_margin_level_percent` | 200 | `execution_preflight.py` |
| `STRATEGY_MANAGEMENT` | per strategy | `position_monitor.py` |

---

## 11. Verification status

This section is deliberately explicit about what was and was not proven.

### Verified

| Item | Evidence |
|---|---|
| Indicator mathematics | 25 tests; RSI matches a published reference to 2 dp |
| Single-score architecture | 22 tests, incl. "score 100 + failed hard gate ⇒ not executable" |
| Structure / FVG / AMD / sessions | 34 tests, incl. the previous-day spike regression |
| Execution mathematics | 50 tests across FX major, FX cross, metal, crypto, index |
| Cross-instrument calculation chain | `tools/validate_trade_calculations.py` — **89/89** |
| Full suite | **165 passed, 1 skipped** |

### NOT verified

| Item | Why |
|---|---|
| **Live MT5 symbol audit** | No MT5 terminal is reachable from this environment. `tools/audit_broker_symbols.py` is written and read-only but **has not been run against a real broker**. |
| **Broker calculator agreement** | `order_calc_profit`/`order_calc_margin` were exercised against a deterministic fixture, not a live terminal. Run `tools/validate_trade_calculations.py --live`. |
| **`OrderCheck` against a real server** | The code path and blocker handling are tested; no real `order_check` response has been observed. |
| **Backtest / expectancy** | No historical backtest was run. No win rate, expectancy or profit factor is claimed anywhere. |
| **Live or demo execution** | No order has been placed. |
| **Threshold calibration** | Every threshold in §10 is a policy default. None is statistically derived. |

**This system is not certified production ready.** The logic is correct and
tested; broker agreement and market performance are unverified. Before live use:

1. Run `python tools/audit_broker_symbols.py --mode demo` and confirm every
   symbol you intend to trade is `execution_safe`.
2. Run `python tools/validate_trade_calculations.py --live --mode demo`.
3. Backtest and calibrate the thresholds in §10.
4. Run on demo, comparing every displayed value against the MT5 terminal.

---

## 11.1 Second audit pass (remaining gaps found after the first pass)

The first pass fixed the original P0 set. A second pass found the following
remaining gaps, all corrected in this branch:

| # | Severity | Module | Defect | Correction |
|---|---|---|---|---|
| 34 | P1 | `amd.py` / `strategies.py` | AMD could be `complete=True` without `RETRACEMENT_ENTRY`; a completed impulse was labelled an executable entry | Entry/retracement phase is now a hard requirement in `detect_amd` and `evaluate_amd`; phase ordering includes it |
| 35 | P0 | `costs.py` / `execution_preflight.py` | Net RR charged the spread twice when gross money already used executable Bid/Ask legs | `prices_are_executable=True` in executable callers; spread component is 0 with an explicit note |
| 36 | P0 | `trade_levels.py` | `calculate_trade_levels` required a swing scan even when strategy `plan_context` supplied both stop and target; breakout/mean-reversion plans could be rejected without data | Full strategy levels now bypass the swing scan; swings remain the fallback |
| 37 | P0 | `instruments.py` | `metadata_complete` ignored `tick_value`, `tick_value_loss`, `trade_calc_mode`, `currency_profit`, so a guessed classification looked execution-complete | Added to `REQUIRED_EXECUTION_FIELDS` and `missing_metadata` |
| 38 | P1 | `analysis.py` | Crypto inherited the FX weekend model because `trades_24_7` was only passed when a caller selected it | `analyze_structure` derives `trades_24_7` from the broker `InstrumentProfile` |
| 39 | P0 | `workflow.py` / `safety.py` | Execution-spread decision still depended on per-profile hard-coded pip/point ceilings | Workflow computes `spread_model` gate on live Bid/Ask and passing it to `validate_trade_setup` as authoritative |
| 40 | P0 | `execution_preflight.py` | Automatic execution could proceed with only gross RR when the broker failed to return a TP profit figure | New `require_net_rr` gate: missing net RR blocks with `BROKER_CALCULATION_UNAVAILABLE` |

**Test result for this pass (trading modules):** `164 passed, 1 skipped` on the
trading/financial test files. The remaining non-trading test that imports the
whole `core/tools` stack depends on optional vision dependencies
(`pytesseract`/`cv2`) and is outside this audit's scope.

---

## 12. Pre-existing unrelated failure

`tests/test_live_trading_guards.py::test_execute_tool_requires_canonical_registry`
fails both before and after this work. It imports `core/tools.py`, which imports
`skills/vision/camera_tools.py`, which requires `pytesseract`. It is unrelated to
trading logic and was not introduced here.
