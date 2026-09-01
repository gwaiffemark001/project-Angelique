# How to read `strategy_quality_score`

## The short version

`strategy_quality_score` is a **0–100 measure of how completely a setup
satisfies its own strategy's definition.**

It is **not** a probability. It is not a win rate. It is not an edge estimate.

---

## What the number actually answers

> "The SMC strategy requires a protected-swing break, an unexpired directional
> zone, a favourable dealing-range location and higher-timeframe agreement,
> and it grades nine families of supporting evidence. How much of that is
> present right now?"

A score of 82 means: *82% of the graded evidence this strategy looks for is
present, and every hard requirement passed.*

It says nothing about whether the trade will win.

## What it explicitly does not mean

| Misreading | Reality |
|---|---|
| "82 means an 82% chance of winning" | No. Nothing in this system estimates win probability, and no historical data has been used to calibrate one. |
| "SMC at 80 and Momentum at 80 are equally good" | No. They are each 80% complete against **different** evidence models. The scores are not comparable as if they were probabilities. |
| "95 is nearly certain" | No. A perfectly formed setup can still lose. Setup quality and outcome are different things. |
| "A high score can make up for a missing requirement" | No. Hard requirements are binary gates. A score of 100 with one failed hard requirement is `NOT_EXECUTABLE`. |

## The two-gate model

Every strategy evaluation has two independent gates, and **both** must pass:

```
setup_complete = (all hard requirements met)
                 AND (quality_score >= minimum_quality_score)
                 AND (no blockers)
                 AND (a direction exists)
                 AND (data status is ready)
```

**Hard requirements** are binary and gating. Examples:

- SMC: a closed-candle break of a protected swing
- Momentum: RSI on the correct side of the midline
- Mean reversion: a non-trending regime (ADX < 20)
- Breakout: the break candle was accepted, not rejected

If any fails, the setup is not executable regardless of score. This is
enforced in code and asserted in
`tests/test_trading_strategy_scoring.py::test_a_perfect_score_cannot_override_a_failed_hard_requirement`.

**Weighted evidence** grades quality among setups that already pass the gates.

## Why correlated signals do not stack

Evidence is grouped into **families**. Within a family, the score is the
weighted *mean* of its observations, not their sum.

RSI, MACD separation and histogram slope all live in the `momentum_quality`
family. Three momentum indicators agreeing is **one** observation about
momentum, not three. Without this, a strategy could inflate its score simply
by counting the same information three times.

Independent families — structure, location, liquidity, freshness, timing —
each contribute their own weight, because they carry genuinely different
information.

## Confidence labels

| Label | Condition |
|---|---|
| `NOT_EXECUTABLE` | Any hard requirement failed, or a blocker is present |
| `BELOW_THRESHOLD` | Gates passed but the score is under the minimum |
| `QUALIFIED_SETUP_QUALITY` | At or above the minimum (default 70) |
| `STRONG_SETUP_QUALITY` | 80–89 |
| `VERY_STRONG_SETUP_QUALITY` | 90+ |

Every label says **setup quality**, never "confidence in a win". That wording
is deliberate.

## The threshold is policy, not science

`minimum_quality_score` defaults to **70**. This is a policy default chosen to
be reasonably selective. **It has not been backtested.** It should be
calibrated per strategy, per instrument and per broker once historical
performance data exists.

Do not describe 70 as "statistically validated". It is not.

## Reading an evaluation

Every evaluation serialises to:

```json
{
  "strategy_name": "SMC",
  "direction": "BUY",
  "state": "WAIT",
  "quality_score_0_100": 82,
  "minimum_quality": 70,
  "setup_complete": false,
  "confidence_label": "NOT_EXECUTABLE",
  "failed_hard_requirements": ["dealing_range_location"],
  "hard_requirements": [ ... each with satisfied + detail ... ],
  "evidence_families": { "liquidity": {"score": 1.0, "weight": 15}, ... },
  "score_meaning": "Completeness of this strategy's own setup definition. This is NOT a win probability."
}
```

Note the example: **82 with `setup_complete: false`.** The score is high, but
`dealing_range_location` failed, so the trade is not executable. That is the
system working as intended — read `failed_hard_requirements` before the score.

## Where the score comes from

`skills/trading_skill/strategy_evaluation.py` defines the single scoring
object. `skills/trading_skill/strategies.py` defines each strategy's hard
requirements and evidence families.

There is exactly one score in the system. `confluence.evaluate_confluence` is a
*view* of the selected strategy's evaluation, not a second opinion — the
previous architecture had two scores that could disagree, and that has been
removed.
