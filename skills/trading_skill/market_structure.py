"""Market-structure engine: swings, protected swings, BOS/CHoCH, liquidity, dealing range.

This module replaces the previous rolling-window heuristics:

* A break of structure is no longer ``close > max(last 5 highs)``. It is a
  **closed-candle break of a confirmed, protected swing point** produced by a
  structure state machine that tracks bias, the protected high and the
  protected low.
* A liquidity sweep is no longer "the last candle poked above the previous five
  bars". It must raid an identified **liquidity pool**: a confirmed swing, an
  equal-high/equal-low cluster, or an externally supplied session/day level.
* Premium/discount is no longer anchored to ``max/min`` of an arbitrary
  200-candle window. It is anchored to the **current dealing range**, i.e. the
  structural leg the market is actually trading inside.

Nothing in this module authorises a trade; it produces evidence with explicit
timestamps and invalidation levels.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Sequence

BULLISH = "bullish"
BEARISH = "bearish"
SIDEWAYS = "sideways"


def _f(candle: dict[str, Any], key: str) -> float:
    try:
        return float(candle.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _high(c): return _f(c, "high")
def _low(c): return _f(c, "low")
def _open(c): return _f(c, "open")
def _close(c): return _f(c, "close")


def _time(candle: dict[str, Any]) -> Any:
    return candle.get("time", candle.get("timestamp"))


def closed_candles(candles: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = list(candles or [])
    while rows and rows[-1].get("closed") is False:
        rows.pop()
    return rows


# --------------------------------------------------------------------------
# Swing detection
# --------------------------------------------------------------------------
@dataclass
class SwingPoint:
    index: int
    price: float
    kind: str            # "swing_high" | "swing_low"
    timestamp: Any
    strength: int
    #: A swing is only *confirmed* once ``strength`` candles have closed after
    #: it. Unconfirmed swings must never be used as structural references.
    confirmed: bool
    broken: bool = False
    broken_index: int | None = None
    protected: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def find_swings(candles: Sequence[dict[str, Any]], strength: int = 2) -> list[SwingPoint]:
    """Fractal swing detection with explicit right-hand confirmation.

    ``strength`` is the number of candles that must sit on each side. A swing
    at index ``i`` is confirmed only when ``i + strength`` candles exist.
    """
    rows = list(candles)
    strength = max(1, int(strength))
    points: list[SwingPoint] = []
    last = len(rows) - 1
    for index in range(strength, len(rows) - strength):
        window = rows[index - strength: index + strength + 1]
        high, low = _high(rows[index]), _low(rows[index])
        confirmed = (index + strength) <= last
        if high > 0 and high >= max(_high(item) for item in window) and high > max(
            [_high(item) for item in window if item is not rows[index]] or [0]
        ) - 1e-12:
            points.append(SwingPoint(index, high, "swing_high", _time(rows[index]), strength, confirmed))
        if low > 0 and low <= min(_low(item) for item in window):
            points.append(SwingPoint(index, low, "swing_low", _time(rows[index]), strength, confirmed))
    points.sort(key=lambda p: (p.index, p.kind))
    return points


# --------------------------------------------------------------------------
# Structure state machine (BOS / CHoCH on protected swings)
# --------------------------------------------------------------------------
@dataclass
class StructureEvent:
    type: str                # "BOS" | "CHoCH"
    direction: str           # bullish | bearish
    broken_swing_index: int
    broken_level: float
    break_index: int
    break_price: float
    break_timestamp: Any
    timeframe: str | None
    confirmation: str        # always "closed_candle" -- wicks never confirm
    previous_bias: str
    new_bias: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StructureState:
    bias: str = SIDEWAYS
    protected_high: SwingPoint | None = None
    protected_low: SwingPoint | None = None
    events: list[StructureEvent] = field(default_factory=list)
    swings: list[SwingPoint] = field(default_factory=list)
    timeframe: str | None = None

    @property
    def last_event(self) -> StructureEvent | None:
        return self.events[-1] if self.events else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "bias": self.bias,
            "timeframe": self.timeframe,
            "protected_high": self.protected_high.as_dict() if self.protected_high else None,
            "protected_low": self.protected_low.as_dict() if self.protected_low else None,
            "events": [event.as_dict() for event in self.events],
            "last_event": self.last_event.as_dict() if self.last_event else None,
            "swing_highs": [(p.index, p.price) for p in self.swings if p.kind == "swing_high"],
            "swing_lows": [(p.index, p.price) for p in self.swings if p.kind == "swing_low"],
            "structural_points": [
                {
                    "index": p.index, "price": p.price, "type": p.kind, "timestamp": p.timestamp,
                    "strength": p.strength, "valid": p.confirmed and not p.broken,
                    "confirmed": p.confirmed, "broken": p.broken, "protected": p.protected,
                    "timeframe": self.timeframe,
                }
                for p in self.swings
            ],
        }


def build_structure(
    candles: Sequence[dict[str, Any]],
    *,
    strength: int = 2,
    timeframe: str | None = None,
) -> StructureState:
    """Walk the series forward and maintain bias + protected swings.

    A **protected swing** is the most recent confirmed swing that, if broken by
    a candle *close*, changes or extends the structure. Breaking a protected
    swing in the direction of bias is a BOS; breaking the opposite protected
    swing is a CHoCH.
    """
    rows = closed_candles(candles)
    state = StructureState(timeframe=timeframe)
    if len(rows) < (strength * 2 + 2):
        return state

    swings = find_swings(rows, strength)
    state.swings = swings
    by_index: dict[int, list[SwingPoint]] = {}
    for point in swings:
        # A swing is only usable once its confirmation candles have closed.
        by_index.setdefault(point.index + point.strength, []).append(point)

    protected_high: SwingPoint | None = None
    protected_low: SwingPoint | None = None
    bias = SIDEWAYS

    for index, candle in enumerate(rows):
        close = _close(candle)

        # 1. Check breaks of the currently protected swings (closed candle only).
        if protected_high is not None and close > protected_high.price:
            previous_bias = bias
            new_bias = BULLISH
            event_type = "BOS" if previous_bias == BULLISH else "CHoCH"
            protected_high.broken = True
            protected_high.broken_index = index
            state.events.append(StructureEvent(
                type=event_type, direction=BULLISH,
                broken_swing_index=protected_high.index, broken_level=protected_high.price,
                break_index=index, break_price=close, break_timestamp=_time(candle),
                timeframe=timeframe, confirmation="closed_candle",
                previous_bias=previous_bias, new_bias=new_bias,
            ))
            bias = new_bias
            # After a bullish break the protected low becomes the last confirmed
            # low before the break (the origin of the impulse).
            candidates = [p for p in swings if p.kind == "swing_low" and p.index < index and p.confirmed]
            protected_low = candidates[-1] if candidates else protected_low
            protected_high = None

        if protected_low is not None and close < protected_low.price:
            previous_bias = bias
            new_bias = BEARISH
            event_type = "BOS" if previous_bias == BEARISH else "CHoCH"
            protected_low.broken = True
            protected_low.broken_index = index
            state.events.append(StructureEvent(
                type=event_type, direction=BEARISH,
                broken_swing_index=protected_low.index, broken_level=protected_low.price,
                break_index=index, break_price=close, break_timestamp=_time(candle),
                timeframe=timeframe, confirmation="closed_candle",
                previous_bias=previous_bias, new_bias=new_bias,
            ))
            bias = new_bias
            candidates = [p for p in swings if p.kind == "swing_high" and p.index < index and p.confirmed]
            protected_high = candidates[-1] if candidates else protected_high
            protected_low = None

        # 2. Register newly confirmed swings as the protected references.
        for point in by_index.get(index, []):
            if point.kind == "swing_high":
                if protected_high is None or point.price > protected_high.price or bias == BEARISH:
                    protected_high = point
            else:
                if protected_low is None or point.price < protected_low.price or bias == BULLISH:
                    protected_low = point

    if protected_high is not None:
        protected_high.protected = True
    if protected_low is not None:
        protected_low.protected = True
    state.bias = bias
    state.protected_high = protected_high
    state.protected_low = protected_low
    return state


# --------------------------------------------------------------------------
# Liquidity pools
# --------------------------------------------------------------------------
@dataclass
class LiquidityPool:
    side: str            # "buy_side" (above price) | "sell_side" (below price)
    price: float
    kind: str            # confirmed_swing | equal_highs | equal_lows | session_level
    index: int
    timestamp: Any
    strength: int        # how many touches / how significant
    swept: bool = False
    swept_index: int | None = None
    swept_timestamp: Any = None
    reclaimed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_liquidity_pools(
    candles: Sequence[dict[str, Any]],
    structure: StructureState,
    *,
    external_levels: Sequence[dict[str, Any]] | None = None,
    equal_tolerance_ratio: float = 0.0005,
    lookback: int = 150,
) -> list[LiquidityPool]:
    """Identify *meaningful* liquidity, not any random recent extreme."""
    rows = closed_candles(candles)
    if len(rows) < 10:
        return []
    window_start = max(0, len(rows) - lookback)
    span = max(_high(c) for c in rows[window_start:]) - min(_low(c) for c in rows[window_start:])
    tolerance = max(span * equal_tolerance_ratio, 1e-9)

    pools: list[LiquidityPool] = []

    confirmed_highs = [p for p in structure.swings if p.kind == "swing_high" and p.confirmed and p.index >= window_start]
    confirmed_lows = [p for p in structure.swings if p.kind == "swing_low" and p.confirmed and p.index >= window_start]

    for point in confirmed_highs:
        pools.append(LiquidityPool("buy_side", point.price, "confirmed_swing", point.index, point.timestamp, point.strength))
    for point in confirmed_lows:
        pools.append(LiquidityPool("sell_side", point.price, "confirmed_swing", point.index, point.timestamp, point.strength))

    # Equal highs / equal lows clusters carry more resting liquidity.
    for points, side, kind in ((confirmed_highs, "buy_side", "equal_highs"), (confirmed_lows, "sell_side", "equal_lows")):
        used: set[int] = set()
        for i, first in enumerate(points):
            if i in used:
                continue
            cluster = [first]
            for j in range(i + 1, len(points)):
                if abs(points[j].price - first.price) <= tolerance:
                    cluster.append(points[j])
                    used.add(j)
            if len(cluster) >= 2:
                latest = cluster[-1]
                pools.append(LiquidityPool(
                    side, max(p.price for p in cluster) if side == "buy_side" else min(p.price for p in cluster),
                    kind, latest.index, latest.timestamp, len(cluster),
                ))

    for level in external_levels or []:
        try:
            price = float(level.get("price"))
        except (TypeError, ValueError):
            continue
        side = str(level.get("side") or ("buy_side" if price > _close(rows[-1]) else "sell_side"))
        pools.append(LiquidityPool(
            side, price, str(level.get("kind") or "session_level"),
            int(level.get("index", len(rows) - 1)), level.get("timestamp"), int(level.get("strength", 1)),
        ))

    # Mark which pools have already been raided and whether price reclaimed.
    for pool in pools:
        for index in range(pool.index + 1, len(rows)):
            candle = rows[index]
            if pool.side == "buy_side" and _high(candle) > pool.price:
                pool.swept = True
                pool.swept_index = index
                pool.swept_timestamp = _time(candle)
                pool.reclaimed = _close(candle) < pool.price
                break
            if pool.side == "sell_side" and _low(candle) < pool.price:
                pool.swept = True
                pool.swept_index = index
                pool.swept_timestamp = _time(candle)
                pool.reclaimed = _close(candle) > pool.price
                break
    return pools


@dataclass
class LiquiditySweep:
    side: str                 # buy_side / sell_side raid
    pool: LiquidityPool
    sweep_index: int
    sweep_timestamp: Any
    reclaim_index: int | None
    reclaim_timestamp: Any
    #: Direction the sweep *implies* if a structure shift follows.
    implied_direction: str
    age_candles: int
    valid: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["pool"] = self.pool.as_dict()
        return data


def detect_liquidity_sweep(
    candles: Sequence[dict[str, Any]],
    pools: Sequence[LiquidityPool],
    *,
    max_age_candles: int = 12,
    require_reclaim: bool = True,
) -> LiquiditySweep | None:
    """Return the most recent *valid* raid of a meaningful liquidity pool.

    A raid is only valid when:
      1. price traded through an identified pool,
      2. price closed back on the origin side within ``max_age_candles``
         (reclaim), when ``require_reclaim`` is set,
      3. the event is still recent enough to be actionable.
    """
    rows = closed_candles(candles)
    if not rows or not pools:
        return None
    last_index = len(rows) - 1
    best: LiquiditySweep | None = None

    for pool in pools:
        if not pool.swept or pool.swept_index is None:
            continue
        age = last_index - pool.swept_index
        if age > max_age_candles:
            continue
        reclaim_index = None
        for index in range(pool.swept_index, min(len(rows), pool.swept_index + max_age_candles + 1)):
            close = _close(rows[index])
            if pool.side == "buy_side" and close < pool.price:
                reclaim_index = index
                break
            if pool.side == "sell_side" and close > pool.price:
                reclaim_index = index
                break
        reclaimed = reclaim_index is not None
        valid = reclaimed or not require_reclaim
        candidate = LiquiditySweep(
            side=pool.side,
            pool=pool,
            sweep_index=pool.swept_index,
            sweep_timestamp=pool.swept_timestamp,
            reclaim_index=reclaim_index,
            reclaim_timestamp=_time(rows[reclaim_index]) if reclaim_index is not None else None,
            implied_direction=BEARISH if pool.side == "buy_side" else BULLISH,
            age_candles=age,
            valid=valid,
            reason=(
                f"{pool.kind} at {pool.price} was raided and reclaimed."
                if reclaimed else f"{pool.kind} at {pool.price} was raided without a reclaim close."
            ),
        )
        if best is None:
            best = candidate
            continue
        # Prefer valid, then most recent, then strongest pool.
        rank = (candidate.valid, candidate.sweep_index, candidate.pool.strength)
        current = (best.valid, best.sweep_index, best.pool.strength)
        if rank > current:
            best = candidate
    return best


# --------------------------------------------------------------------------
# Dealing range (premium / discount) anchored to the traded structural leg
# --------------------------------------------------------------------------
@dataclass
class DealingRange:
    high: float
    low: float
    equilibrium: float
    high_index: int
    low_index: int
    basis: str
    #: 0.0 at the range low, 1.0 at the range high.
    position: float
    location: str            # premium | discount | equilibrium
    ote_zone: tuple[float, float] | None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ote_zone"] = list(self.ote_zone) if self.ote_zone else None
        return data


def build_dealing_range(
    candles: Sequence[dict[str, Any]],
    structure: StructureState,
    *,
    fallback_lookback: int = 60,
) -> DealingRange | None:
    """Anchor premium/discount to the leg the market is currently trading.

    Preference order:
      1. The impulse leg created by the most recent structure event
         (swing origin -> break extreme).
      2. The last confirmed swing high / swing low pair.
      3. A bounded recent window (explicitly flagged as a fallback).
    """
    rows = closed_candles(candles)
    if len(rows) < 5:
        return None
    close = _close(rows[-1])

    high = low = None
    high_index = low_index = 0
    basis = "fallback_window"

    event = structure.last_event
    if event is not None:
        start = min(event.broken_swing_index, event.break_index)
        leg = rows[max(0, start - 1): len(rows)]
        offset = max(0, start - 1)
        if leg:
            high = max(_high(c) for c in leg)
            low = min(_low(c) for c in leg)
            high_index = offset + max(range(len(leg)), key=lambda i: _high(leg[i]))
            low_index = offset + min(range(len(leg)), key=lambda i: _low(leg[i]))
            basis = f"impulse_leg_from_{event.type}_{event.direction}"

    if high is None or low is None or high <= low:
        highs = [p for p in structure.swings if p.kind == "swing_high" and p.confirmed]
        lows = [p for p in structure.swings if p.kind == "swing_low" and p.confirmed]
        if highs and lows:
            high, high_index = highs[-1].price, highs[-1].index
            low, low_index = lows[-1].price, lows[-1].index
            basis = "last_confirmed_swing_pair"

    if high is None or low is None or high <= low:
        window = rows[-fallback_lookback:]
        offset = len(rows) - len(window)
        high = max(_high(c) for c in window)
        low = min(_low(c) for c in window)
        high_index = offset + max(range(len(window)), key=lambda i: _high(window[i]))
        low_index = offset + min(range(len(window)), key=lambda i: _low(window[i]))
        basis = "fallback_window"

    span = high - low
    if span <= 0:
        return None
    equilibrium = (high + low) / 2
    position = (close - low) / span
    location = "premium" if position > 0.55 else "discount" if position < 0.45 else "equilibrium"

    # Optimal Trade Entry: the 0.62-0.79 retracement of the leg, oriented by
    # which side of the leg formed last.
    bullish_leg = low_index < high_index
    if bullish_leg:
        ote = (high - span * 0.79, high - span * 0.62)
    else:
        ote = (low + span * 0.62, low + span * 0.79)

    return DealingRange(
        high=high, low=low, equilibrium=equilibrium,
        high_index=high_index, low_index=low_index, basis=basis,
        position=position, location=location, ote_zone=(min(ote), max(ote)),
    )


# --------------------------------------------------------------------------
# Displacement
# --------------------------------------------------------------------------
def displacement_at(
    candles: Sequence[dict[str, Any]],
    index: int,
    *,
    lookback: int = 20,
    body_multiple: float = 1.5,
    atr_multiple: float = 1.0,
) -> dict[str, Any]:
    """Measure displacement for a *specific* candle (never "the latest candle").

    A displacement candle must have both an outsized body relative to recent
    bodies and an outsized range relative to recent volatility.
    """
    rows = closed_candles(candles)
    if not (0 <= index < len(rows)):
        return {"displacement": False, "reason": "index out of range"}
    candle = rows[index]
    prior = rows[max(0, index - lookback):index]
    if len(prior) < 5:
        return {"displacement": False, "reason": "insufficient prior candles"}
    body = abs(_close(candle) - _open(candle))
    total_range = _high(candle) - _low(candle)
    average_body = sum(abs(_close(c) - _open(c)) for c in prior) / len(prior)
    average_range = sum(_high(c) - _low(c) for c in prior) / len(prior)
    range_ok = average_range > 0 and total_range >= average_range * atr_multiple
    if average_body > 0:
        body_ok = body >= average_body * body_multiple
    else:
        # Every prior candle was a doji, so "N times the average body" is
        # undefined. Fall back to sizing the body against recent RANGE, which
        # is always meaningful. Returning False here would let a genuine
        # expansion out of a flat period go undetected.
        body_ok = average_range > 0 and body >= average_range * body_multiple
    body_ratio = body / total_range if total_range > 0 else 0.0
    return {
        "displacement": bool(body_ok and range_ok and body_ratio >= 0.5),
        "index": index,
        "timestamp": _time(candle),
        "direction": BULLISH if _close(candle) > _open(candle) else BEARISH,
        "body": body,
        "range": total_range,
        "body_ratio": body_ratio,
        "average_body": average_body,
        "average_range": average_range,
        # When the prior window was all dojis, express the body relative to
        # recent RANGE so downstream grading still has a usable number.
        "body_multiple": (body / average_body) if average_body > 0
        else ((body / average_range) if average_range > 0 else None),
        "body_multiple_basis": "average_body" if average_body > 0 else "average_range",
        "range_multiple": (total_range / average_range) if average_range > 0 else None,
    }
