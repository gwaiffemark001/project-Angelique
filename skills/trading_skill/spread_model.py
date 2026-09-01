"""Instrument-aware spread measurement and execution gating.

The previous policy hard-coded a single ceiling per asset bucket (1.5 pips FX
major, 40 ticks metal, 0.10% crypto) and presented those numbers as if they were
market truth. They are not: they are *policy guesses*.

This module separates three things that were previously conflated:

1. **Measurement** -- ``raw_spread_price = ask - bid``, normalised through the
   broker's own ``point`` / ``tick_size`` / FX pip convention. This is fact.
2. **Observation** -- a rolling, session-aware distribution of the spreads this
   broker has actually shown for this symbol. This is evidence.
3. **Policy** -- configurable ceilings, expressed both absolutely and
   *relative to the trade* (spread vs stop distance, spread vs expected reward).
   These are documented as policy and are NOT claimed to be backtested.

The relative gates are the important ones: a 2-pip spread is irrelevant on a
200-pip swing stop and fatal on a 6-pip scalp stop.
"""

from __future__ import annotations

import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Deque, Iterable

from .instruments import (
    InstrumentProfile, FX_MAJOR, FX_CROSS, FX_EXOTIC, METAL, CRYPTO, INDEX,
    ENERGY, EQUITY, OTHER, build_profile,
)


# --------------------------------------------------------------------------
# Policy
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class SpreadPolicy:
    """Configurable spread limits.

    ``absolute_*`` values are a coarse sanity ceiling per instrument class and
    are expressed in the instrument's own natural unit (pips for FX, points for
    metals/indices, percent of price for crypto). ``max_spread_to_stop_ratio``
    and ``max_spread_to_reward_ratio`` are the gates that actually protect trade
    economics and apply to every instrument identically.

    NOTE: none of these numbers are statistically calibrated. They are safety
    policy defaults and must be reviewed per broker/account.
    """
    absolute_pips: float | None = None
    absolute_points: float | None = None
    absolute_percent_of_price: float | None = None
    #: Spread must not consume more than this fraction of the stop distance.
    max_spread_to_stop_ratio: float = 0.15
    #: Spread must not consume more than this fraction of the expected reward.
    max_spread_to_reward_ratio: float = 0.08
    #: Reject when the current spread exceeds this percentile of the observed
    #: rolling distribution (protects against news/rollover blowouts).
    max_observed_percentile: float = 0.90
    #: Minimum samples before the percentile gate is trusted.
    min_samples_for_percentile: int = 20
    calibrated: bool = False
    source: str = "default policy (not backtested)"


DEFAULT_SPREAD_POLICIES: dict[str, SpreadPolicy] = {
    FX_MAJOR: SpreadPolicy(absolute_pips=2.5),
    FX_CROSS: SpreadPolicy(absolute_pips=4.5),
    FX_EXOTIC: SpreadPolicy(absolute_pips=15.0),
    METAL: SpreadPolicy(absolute_points=80.0),
    CRYPTO: SpreadPolicy(absolute_percent_of_price=0.25),
    INDEX: SpreadPolicy(absolute_points=200.0),
    ENERGY: SpreadPolicy(absolute_points=100.0),
    EQUITY: SpreadPolicy(absolute_percent_of_price=0.50),
    OTHER: SpreadPolicy(),
}


def policy_for(instrument_class: str, overrides: dict[str, SpreadPolicy] | None = None) -> SpreadPolicy:
    table = {**DEFAULT_SPREAD_POLICIES, **(overrides or {})}
    return table.get(instrument_class, DEFAULT_SPREAD_POLICIES[OTHER])


# --------------------------------------------------------------------------
# Measurement
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class SpreadMeasurement:
    symbol: str
    instrument_class: str
    bid: float | None
    ask: float | None
    mid: float | None
    raw_spread_price: float | None
    spread_points: float | None
    spread_ticks: float | None
    spread_pips: float | None
    spread_percent_of_price: float | None
    display_unit: str
    display_value: float | None
    timestamp: str
    source: str
    valid: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def measure_spread(
    profile: InstrumentProfile,
    bid: Any,
    ask: Any,
    *,
    source: str = "symbol_info_tick",
    now: datetime | None = None,
) -> SpreadMeasurement:
    """Derive spread from the raw bid/ask, never from a hard-coded assumption."""
    timestamp = (now or datetime.now(timezone.utc)).isoformat()

    def _f(value: Any) -> float | None:
        try:
            out = float(value)
        except (TypeError, ValueError):
            return None
        return out if out > 0 else None

    bid_value, ask_value = _f(bid), _f(ask)
    if bid_value is None or ask_value is None:
        return SpreadMeasurement(
            profile.symbol, profile.instrument_class, bid_value, ask_value, None, None,
            None, None, None, None, profile.display_unit, None, timestamp, source,
            False, "Bid/ask unavailable; spread cannot be measured.",
        )
    if ask_value < bid_value:
        return SpreadMeasurement(
            profile.symbol, profile.instrument_class, bid_value, ask_value,
            (bid_value + ask_value) / 2, None, None, None, None, None,
            profile.display_unit, None, timestamp, source,
            False, "Broker returned an inverted quote (ask < bid).",
        )

    raw = ask_value - bid_value
    mid = (bid_value + ask_value) / 2
    points = profile.to_points(raw)
    ticks = profile.to_ticks(raw)
    pips = profile.to_pips(raw)
    percent = (raw / mid * 100.0) if mid > 0 else None
    display = pips if profile.display_unit == "pips" else points if profile.display_unit == "points" else raw

    return SpreadMeasurement(
        symbol=profile.symbol, instrument_class=profile.instrument_class,
        bid=bid_value, ask=ask_value, mid=mid, raw_spread_price=raw,
        spread_points=points, spread_ticks=ticks, spread_pips=pips,
        spread_percent_of_price=percent, display_unit=profile.display_unit,
        display_value=display, timestamp=timestamp, source=source,
        valid=True, reason="Spread derived from broker bid/ask.",
    )


# --------------------------------------------------------------------------
# Rolling observation
# --------------------------------------------------------------------------
@dataclass
class SpreadStats:
    symbol: str
    session: str
    samples: int
    median: float | None
    p75: float | None
    p90: float | None
    p95: float | None
    maximum: float | None
    minimum: float | None
    unit: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class SpreadProfileStore:
    """Thread-safe rolling store of observed spreads, keyed by symbol + session."""

    def __init__(self, window: int = 500) -> None:
        self._window = max(20, int(window))
        self._samples: dict[tuple[str, str], Deque[float]] = defaultdict(lambda: deque(maxlen=self._window))
        self._units: dict[str, str] = {}
        self._lock = RLock()

    def observe(self, measurement: SpreadMeasurement, session: str = "ALL") -> None:
        if not measurement.valid or measurement.raw_spread_price is None:
            return
        with self._lock:
            self._units[measurement.symbol] = measurement.display_unit
            for key in ((measurement.symbol, "ALL"), (measurement.symbol, str(session).upper())):
                self._samples[key].append(float(measurement.raw_spread_price))

    def stats(self, symbol: str, session: str = "ALL") -> SpreadStats:
        with self._lock:
            values = sorted(self._samples.get((symbol, str(session).upper()), ()))
            unit = self._units.get(symbol, "price")
        if not values:
            return SpreadStats(symbol, str(session).upper(), 0, None, None, None, None, None, None, unit)

        def percentile(fraction: float) -> float:
            if len(values) == 1:
                return values[0]
            position = fraction * (len(values) - 1)
            low = int(position)
            high = min(low + 1, len(values) - 1)
            weight = position - low
            return values[low] * (1 - weight) + values[high] * weight

        return SpreadStats(
            symbol=symbol, session=str(session).upper(), samples=len(values),
            median=statistics.median(values), p75=percentile(0.75),
            p90=percentile(0.90), p95=percentile(0.95),
            maximum=values[-1], minimum=values[0], unit=unit,
        )

    def percentile_of(self, symbol: str, value: float, session: str = "ALL") -> float | None:
        with self._lock:
            values = sorted(self._samples.get((symbol, str(session).upper()), ()))
        if len(values) < 2:
            return None
        below = sum(1 for item in values if item <= value)
        return below / len(values)


#: Process-wide store. The workflow feeds every observed tick into it.
spread_store = SpreadProfileStore()


# --------------------------------------------------------------------------
# Execution gate
# --------------------------------------------------------------------------
@dataclass
class SpreadGateResult:
    allowed: bool
    measurement: dict[str, Any]
    policy: dict[str, Any]
    stats: dict[str, Any] | None
    checks: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    spread_to_stop_ratio: float | None = None
    spread_to_reward_ratio: float | None = None
    observed_percentile: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_spread_gate(
    profile: InstrumentProfile,
    measurement: SpreadMeasurement,
    *,
    stop_distance_price: float | None = None,
    reward_distance_price: float | None = None,
    session: str = "ALL",
    policy: SpreadPolicy | None = None,
    store: SpreadProfileStore | None = None,
) -> SpreadGateResult:
    """Decide whether the current spread permits execution.

    The absolute ceilings are per instrument class and expressed in that
    class's natural unit -- an FX pip limit is never applied to XAUUSD or
    BTCUSD.
    """
    policy = policy or policy_for(profile.instrument_class)
    store = store or spread_store
    stats = store.stats(profile.symbol, session)
    result = SpreadGateResult(
        allowed=True, measurement=measurement.as_dict(), policy=asdict(policy),
        stats=stats.as_dict(),
    )

    if not measurement.valid or measurement.raw_spread_price is None:
        result.allowed = False
        result.reasons.append(measurement.reason)
        return result

    raw = measurement.raw_spread_price

    # 1. Absolute ceiling in the instrument's natural unit.
    if policy.absolute_pips is not None:
        if measurement.spread_pips is None:
            result.allowed = False
            result.reasons.append(
                f"Policy expects an FX pip ceiling but {profile.symbol} "
                f"({profile.instrument_class}) has no pip definition."
            )
        elif measurement.spread_pips > policy.absolute_pips + 1e-9:
            result.allowed = False
            result.reasons.append(
                f"Spread {measurement.spread_pips:.2f} pips exceeds the "
                f"{profile.instrument_class} ceiling of {policy.absolute_pips:.2f} pips."
            )
        else:
            result.checks.append(
                f"Spread {measurement.spread_pips:.2f} pips within {policy.absolute_pips:.2f} pip ceiling."
            )
    if policy.absolute_points is not None:
        if measurement.spread_points is None:
            result.allowed = False
            result.reasons.append("Broker point size is unavailable; spread cannot be gated in points.")
        elif measurement.spread_points > policy.absolute_points + 1e-9:
            result.allowed = False
            result.reasons.append(
                f"Spread {measurement.spread_points:.0f} points exceeds the "
                f"{profile.instrument_class} ceiling of {policy.absolute_points:.0f} points."
            )
        else:
            result.checks.append(
                f"Spread {measurement.spread_points:.0f} points within {policy.absolute_points:.0f} point ceiling."
            )
    if policy.absolute_percent_of_price is not None:
        percent = measurement.spread_percent_of_price
        if percent is None:
            result.allowed = False
            result.reasons.append("Mid price unavailable; relative spread cannot be gated.")
        elif percent > policy.absolute_percent_of_price + 1e-12:
            result.allowed = False
            result.reasons.append(
                f"Spread {percent:.3f}% of price exceeds the {profile.instrument_class} "
                f"ceiling of {policy.absolute_percent_of_price:.3f}%."
            )
        else:
            result.checks.append(f"Spread {percent:.3f}% of price within ceiling.")

    # 2. Spread relative to the actual trade -- the economically meaningful gate.
    if stop_distance_price and stop_distance_price > 0:
        ratio = raw / stop_distance_price
        result.spread_to_stop_ratio = ratio
        if ratio > policy.max_spread_to_stop_ratio + 1e-12:
            result.allowed = False
            result.reasons.append(
                f"Spread is {ratio * 100:.1f}% of the {stop_distance_price:.6g} stop distance "
                f"(limit {policy.max_spread_to_stop_ratio * 100:.0f}%)."
            )
        else:
            result.checks.append(f"Spread is {ratio * 100:.1f}% of stop distance.")
    if reward_distance_price and reward_distance_price > 0:
        ratio = raw / reward_distance_price
        result.spread_to_reward_ratio = ratio
        if ratio > policy.max_spread_to_reward_ratio + 1e-12:
            result.allowed = False
            result.reasons.append(
                f"Spread is {ratio * 100:.1f}% of the expected reward "
                f"(limit {policy.max_spread_to_reward_ratio * 100:.0f}%)."
            )
        else:
            result.checks.append(f"Spread is {ratio * 100:.1f}% of expected reward.")

    # 3. Broker-observed distribution -- rejects abnormal widening.
    percentile = store.percentile_of(profile.symbol, raw, session)
    result.observed_percentile = percentile
    if percentile is not None and stats.samples >= policy.min_samples_for_percentile:
        if percentile > policy.max_observed_percentile + 1e-12:
            result.allowed = False
            result.reasons.append(
                f"Current spread sits at the {percentile * 100:.0f}th percentile of the last "
                f"{stats.samples} observations (limit {policy.max_observed_percentile * 100:.0f}th)."
            )
        else:
            result.checks.append(
                f"Spread at the {percentile * 100:.0f}th percentile of {stats.samples} observations."
            )
    else:
        result.checks.append(
            f"Observed-spread distribution not yet significant ({stats.samples} samples); "
            "percentile gate skipped."
        )
    return result


def spread_snapshot(
    symbol: str,
    specs: dict[str, Any] | None,
    bid: Any,
    ask: Any,
    *,
    session: str = "ALL",
    record: bool = True,
) -> dict[str, Any]:
    """One-call helper returning the single authoritative spread object.

    Every UI field and every execution check must read from this object.
    """
    profile = build_profile(symbol, specs)
    measurement = measure_spread(profile, bid, ask)
    if record:
        spread_store.observe(measurement, session)
    stats = spread_store.stats(symbol, session)
    return {
        **measurement.as_dict(),
        "instrument_profile": profile.as_dict(),
        "observed": stats.as_dict(),
    }
