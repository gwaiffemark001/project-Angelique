"""Fair Value Gap / Inversion FVG engine with enforced lifecycle.

Corrections relative to the previous implementation
---------------------------------------------------
P0 -- **Displacement association**: an FVG is now qualified against the
      displacement of *the candle that actually created it* (the middle candle
      of the three-candle formation), never against "the latest candle".
P0 -- **Retest expiry is enforced**: an FVG has a finite lifecycle measured in
      candles from formation. Once ``max_retest_candles`` have elapsed the zone
      is ``EXPIRED`` and a later touch cannot revive it.
P0 -- **IFVG source qualification**: an inverted FVG inherits the validity
      requirements of its source FVG. A merely *technical* gap that was blown
      through does not become a tradeable IFVG.
P0 -- **Sweep continuation** uses the most recent valid event, applies expiry,
      and requires current price to still be relevant to the level.

Every zone carries a formation index/timestamp, an expiry, an invalidation
level, and a machine-readable status so downstream consumers cannot mistake a
stale zone for a current opportunity.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Sequence

from .market_structure import (
    BULLISH, BEARISH, StructureState, closed_candles, displacement_at,
    _high, _low, _open, _close, _time,
)

# Zone statuses
UNTOUCHED = "UNTOUCHED"
PARTIALLY_MITIGATED = "PARTIALLY_MITIGATED"
FULLY_MITIGATED = "FULLY_MITIGATED"
INVALIDATED = "INVALIDATED"
EXPIRED = "EXPIRED"

# Zone classifications, in ascending order of tradeability
TECHNICAL_FVG = "TECHNICAL_FVG"       # a gap exists; nothing else is proven
QUALIFIED_FVG = "QUALIFIED_FVG"       # displacement + structure alignment
TRADEABLE_FVG = "TRADEABLE_FVG"       # qualified, unexpired, unmitigated, in play

#: Default lifecycle. Deliberately configurable -- these are strategy policy,
#: not market truth, and are documented as such.
DEFAULT_MAX_RETEST_CANDLES = 8
DEFAULT_MAX_AGE_CANDLES = 40
DEFAULT_MIN_GAP_ATR_RATIO = 0.10


@dataclass
class FairValueGap:
    type: str                      # bullish | bearish
    low: float
    high: float
    formation_index: int           # index of the *middle* (displacement) candle
    formation_timestamp: Any
    expiry_index: int
    size: float
    status: str
    classification: str
    displacement: dict[str, Any]
    aligned_with_structure: bool
    formed_after_liquidity_event: bool
    in_dealing_range: bool
    location: str | None
    invalidation_price: float
    first_touch_index: int | None
    first_touch_timestamp: Any
    mitigation_ratio: float
    price_in_zone: bool
    distance_from_price: float
    age_candles: int
    quality_score: float
    reasons: tuple[str, ...]
    timeframe: str | None = None
    zone_id: str | None = None

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2

    @property
    def tradeable(self) -> bool:
        return self.classification == TRADEABLE_FVG

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        data["midpoint"] = self.midpoint
        data["tradeable"] = self.tradeable
        # Legacy keys retained so existing consumers keep working.
        data["invalidation_status"] = INVALIDATED if self.status == INVALIDATED else "VALID"
        data["retracement_status"] = "CURRENT_RETRACEMENT" if self.price_in_zone else "AWAITING_RETRACEMENT"
        data["score"] = self.quality_score
        data["associated_displacement"] = bool(self.displacement.get("displacement"))
        return data


@dataclass
class InversionFVG:
    type: str                      # direction the IFVG now supports
    low: float
    high: float
    source_zone_id: str | None
    source_classification: str
    inversion_index: int
    inversion_timestamp: Any
    expiry_index: int
    status: str                    # IFVG_CANDIDATE | CONFIRMED_IFVG | EXPIRED
    retest_index: int | None
    retest_timestamp: Any
    price_in_zone: bool
    quality_score: float
    reasons: tuple[str, ...]
    timeframe: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


def _gap_between(first: dict[str, Any], third: dict[str, Any]) -> tuple[str, float, float] | None:
    if _high(first) < _low(third):
        return BULLISH, _high(first), _low(third)
    if _low(first) > _high(third):
        return BEARISH, _high(third), _low(first)
    return None


def detect_fair_value_gaps(
    candles: Sequence[dict[str, Any]],
    *,
    structure: StructureState | None = None,
    dealing_range: Any = None,
    liquidity_sweep: Any = None,
    atr_value: float | None = None,
    timeframe: str | None = None,
    max_retest_candles: int = DEFAULT_MAX_RETEST_CANDLES,
    max_age_candles: int = DEFAULT_MAX_AGE_CANDLES,
    min_gap_atr_ratio: float = DEFAULT_MIN_GAP_ATR_RATIO,
    lookback: int = 150,
) -> list[FairValueGap]:
    """Detect FVGs with a fully enforced lifecycle."""
    rows = closed_candles(candles)
    if len(rows) < 5:
        return []
    last_index = len(rows) - 1
    start = max(0, len(rows) - lookback)
    bias = structure.bias if structure else None
    sweep_index = getattr(liquidity_sweep, "sweep_index", None)

    gaps: list[FairValueGap] = []
    for i in range(max(start, 1), len(rows) - 1):
        first, middle, third = rows[i - 1], rows[i], rows[i + 1]
        found = _gap_between(first, third)
        if not found:
            continue
        gap_type, gap_low, gap_high = found
        size = gap_high - gap_low
        if size <= 0:
            continue

        # -- displacement of the candle that ACTUALLY formed the gap ---------
        disp = displacement_at(rows, i, lookback=20)
        disp_ok = bool(disp.get("displacement")) and disp.get("direction") == gap_type

        # -- meaningful size relative to volatility --------------------------
        size_ok = True
        if atr_value and atr_value > 0:
            size_ok = size >= atr_value * min_gap_atr_ratio

        # -- lifecycle -------------------------------------------------------
        expiry_index = i + max(1, int(max_retest_candles))
        age = last_index - i
        future = rows[i + 2:]
        first_touch_index: int | None = None
        deepest = 0.0
        invalidated_at: int | None = None
        for offset, candle in enumerate(future, start=i + 2):
            touched = _low(candle) <= gap_high and _high(candle) >= gap_low
            if touched and first_touch_index is None:
                first_touch_index = offset
            if touched:
                if gap_type == BULLISH:
                    penetration = min(1.0, max(0.0, (gap_high - max(_low(candle), gap_low)) / size))
                else:
                    penetration = min(1.0, max(0.0, (min(_high(candle), gap_high) - gap_low) / size))
                deepest = max(deepest, penetration)
            closed_through = (_close(candle) < gap_low) if gap_type == BULLISH else (_close(candle) > gap_high)
            if closed_through and invalidated_at is None:
                invalidated_at = offset

        expired = age > max(max_retest_candles, 0) and first_touch_index is None
        too_old = age > max_age_candles
        if invalidated_at is not None:
            status = INVALIDATED
        elif too_old:
            status = EXPIRED
        elif deepest >= 0.999:
            status = FULLY_MITIGATED
        elif first_touch_index is not None:
            # A touch only counts if it happened inside the retest window.
            status = PARTIALLY_MITIGATED if first_touch_index <= expiry_index else EXPIRED
        elif expired:
            status = EXPIRED
        else:
            status = UNTOUCHED

        # -- context ---------------------------------------------------------
        aligned = bias is not None and bias == gap_type
        after_sweep = sweep_index is not None and i >= sweep_index
        in_range = True
        location = None
        if dealing_range is not None:
            in_range = dealing_range.low <= gap_low and gap_high <= dealing_range.high
            midpoint = (gap_low + gap_high) / 2
            span = dealing_range.high - dealing_range.low
            if span > 0:
                position = (midpoint - dealing_range.low) / span
                location = "premium" if position > 0.55 else "discount" if position < 0.45 else "equilibrium"

        current_price = _close(rows[-1])
        price_in_zone = gap_low <= current_price <= gap_high

        reasons: list[str] = []
        if disp_ok:
            reasons.append(f"Formed by a displacement candle ({disp.get('body_multiple') or 0:.1f}x average body).")
        else:
            reasons.append("No qualifying displacement on the candle that formed the gap.")
        if not size_ok:
            reasons.append("Gap is small relative to ATR.")
        if aligned:
            reasons.append(f"Aligned with {bias} market structure.")
        if after_sweep:
            reasons.append("Formed after a valid liquidity raid.")
        if status in {EXPIRED, INVALIDATED, FULLY_MITIGATED}:
            reasons.append(f"Lifecycle status is {status}; not actionable.")

        # -- classification ---------------------------------------------------
        qualified = disp_ok and size_ok and aligned
        if qualified and status in {UNTOUCHED, PARTIALLY_MITIGATED} and in_range:
            classification = TRADEABLE_FVG
        elif qualified:
            classification = QUALIFIED_FVG
        else:
            classification = TECHNICAL_FVG

        quality = 0.0
        quality += 3.0 if disp_ok else 0.0
        quality += 2.0 if aligned else 0.0
        quality += 1.5 if after_sweep else 0.0
        quality += 1.0 if size_ok else 0.0
        quality += 1.0 if in_range else 0.0
        quality += 1.5 if status in {UNTOUCHED, PARTIALLY_MITIGATED} else 0.0

        gaps.append(FairValueGap(
            type=gap_type, low=gap_low, high=gap_high,
            formation_index=i, formation_timestamp=_time(middle),
            expiry_index=expiry_index, size=size, status=status,
            classification=classification, displacement=disp,
            aligned_with_structure=aligned, formed_after_liquidity_event=after_sweep,
            in_dealing_range=in_range, location=location,
            invalidation_price=gap_low if gap_type == BULLISH else gap_high,
            first_touch_index=first_touch_index,
            first_touch_timestamp=_time(rows[first_touch_index]) if first_touch_index is not None else None,
            mitigation_ratio=deepest, price_in_zone=price_in_zone,
            distance_from_price=abs(current_price - (gap_low + gap_high) / 2),
            age_candles=age, quality_score=round(quality, 2), reasons=tuple(reasons),
            timeframe=timeframe,
            zone_id=f"{timeframe or '-'}:FVG:{i}:{gap_low:.10g}:{gap_high:.10g}",
        ))
    return gaps


def detect_inversion_fvgs(
    candles: Sequence[dict[str, Any]],
    gaps: Sequence[FairValueGap],
    *,
    timeframe: str | None = None,
    max_retest_candles: int = DEFAULT_MAX_RETEST_CANDLES,
    require_qualified_source: bool = True,
) -> list[InversionFVG]:
    """Invert FVGs that were traded through, preserving source qualification.

    A gap only becomes an IFVG candidate when:
      * its source gap was at least ``QUALIFIED_FVG`` (unless the caller
        explicitly relaxes ``require_qualified_source``),
      * price closed fully through it (``INVALIDATED``),
      * and the inversion itself has not expired.

    Confirmation additionally requires a retest of the inverted zone from the
    new side within the retest window.
    """
    rows = closed_candles(candles)
    if not rows:
        return []
    last_index = len(rows) - 1
    out: list[InversionFVG] = []

    for gap in gaps:
        if gap.status != INVALIDATED:
            continue
        if require_qualified_source and gap.classification == TECHNICAL_FVG:
            continue
        # Locate the candle that closed through the gap.
        inversion_index = None
        for index in range(gap.formation_index + 2, len(rows)):
            candle = rows[index]
            through = (_close(candle) < gap.low) if gap.type == BULLISH else (_close(candle) > gap.high)
            if through:
                inversion_index = index
                break
        if inversion_index is None:
            continue

        flipped = BEARISH if gap.type == BULLISH else BULLISH
        expiry_index = inversion_index + max(1, int(max_retest_candles))
        retest_index = None
        for index in range(inversion_index + 1, min(len(rows), expiry_index + 1)):
            candle = rows[index]
            if _low(candle) <= gap.high and _high(candle) >= gap.low:
                retest_index = index
                break

        if last_index > expiry_index and retest_index is None:
            status = EXPIRED
        elif retest_index is not None:
            status = "CONFIRMED_IFVG"
        else:
            status = "IFVG_CANDIDATE"

        current_price = _close(rows[-1])
        reasons = [
            f"Source {gap.classification} inverted at index {inversion_index}.",
            "Source gap satisfied its own qualification requirements."
            if gap.classification != TECHNICAL_FVG else
            "Source gap was only technical; inversion is informational only.",
        ]
        quality = (3.0 if gap.classification == TRADEABLE_FVG else 2.0 if gap.classification == QUALIFIED_FVG else 0.5)
        quality += 2.0 if status == "CONFIRMED_IFVG" else 0.0

        out.append(InversionFVG(
            type=flipped, low=gap.low, high=gap.high,
            source_zone_id=gap.zone_id, source_classification=gap.classification,
            inversion_index=inversion_index, inversion_timestamp=_time(rows[inversion_index]),
            expiry_index=expiry_index, status=status,
            retest_index=retest_index,
            retest_timestamp=_time(rows[retest_index]) if retest_index is not None else None,
            price_in_zone=gap.low <= current_price <= gap.high,
            quality_score=round(quality, 2), reasons=tuple(reasons), timeframe=timeframe,
        ))
    return out


# --------------------------------------------------------------------------
# Order blocks
# --------------------------------------------------------------------------
@dataclass
class OrderBlock:
    type: str
    low: float
    high: float
    formation_index: int
    formation_timestamp: Any
    displacement_index: int
    displacement: dict[str, Any]
    status: str
    classification: str
    aligned_with_structure: bool
    price_in_zone: bool
    age_candles: int
    quality_score: float
    timeframe: str | None = None
    zone_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["score"] = self.quality_score
        data["invalidation_status"] = INVALIDATED if self.status == INVALIDATED else "VALID"
        return data


def detect_order_blocks(
    candles: Sequence[dict[str, Any]],
    *,
    structure: StructureState | None = None,
    timeframe: str | None = None,
    max_age_candles: int = DEFAULT_MAX_AGE_CANDLES,
    lookback: int = 150,
) -> list[OrderBlock]:
    rows = closed_candles(candles)
    if len(rows) < 6:
        return []
    last_index = len(rows) - 1
    bias = structure.bias if structure else None
    start = max(1, len(rows) - lookback)
    out: list[OrderBlock] = []

    for index in range(start, len(rows)):
        event = rows[index]
        origin = rows[index - 1]
        bullish = _close(event) > _open(event) and _close(origin) < _open(origin)
        bearish = _close(event) < _open(event) and _close(origin) > _open(origin)
        if not (bullish or bearish):
            continue
        block_type = BULLISH if bullish else BEARISH
        disp = displacement_at(rows, index, lookback=20)
        if not disp.get("displacement") or disp.get("direction") != block_type:
            continue
        low, high = _low(origin), _high(origin)
        invalidated = any(
            (_close(rows[j]) < low) if block_type == BULLISH else (_close(rows[j]) > high)
            for j in range(index + 1, len(rows))
        )
        touched = any(_low(rows[j]) <= high and _high(rows[j]) >= low for j in range(index + 1, len(rows)))
        age = last_index - (index - 1)
        status = (INVALIDATED if invalidated else EXPIRED if age > max_age_candles
                  else PARTIALLY_MITIGATED if touched else UNTOUCHED)
        aligned = bias is not None and bias == block_type
        classification = ("TRADEABLE_OB" if aligned and status in {UNTOUCHED, PARTIALLY_MITIGATED}
                          else "CANDIDATE_OB")
        quality = 2.0 + (2.0 if disp.get("displacement") else 0.0) + (2.0 if aligned else 0.0) \
            + (1.0 if status in {UNTOUCHED, PARTIALLY_MITIGATED} else 0.0)
        out.append(OrderBlock(
            type=block_type, low=low, high=high,
            formation_index=index - 1, formation_timestamp=_time(origin),
            displacement_index=index, displacement=disp, status=status,
            classification=classification, aligned_with_structure=aligned,
            price_in_zone=low <= _close(rows[-1]) <= high, age_candles=age,
            quality_score=round(quality, 2), timeframe=timeframe,
            zone_id=f"{timeframe or '-'}:OB:{index - 1}:{low:.10g}:{high:.10g}",
        ))
    return out


# --------------------------------------------------------------------------
# Sweep -> continuation playbook
# --------------------------------------------------------------------------
def detect_sweep_continuation(
    candles: Sequence[dict[str, Any]],
    *,
    structure: StructureState,
    liquidity_sweep: Any,
    gaps: Sequence[FairValueGap],
    atr_value: float | None = None,
    max_age_candles: int = 15,
    max_distance_atr: float = 2.0,
    timeframe: str | None = None,
) -> dict[str, Any]:
    """Current sweep -> displacement -> entry-zone opportunity, or nothing.

    Returns ``{"status": "none"}`` rather than resurrecting an old historical
    sweep. The event must be recent, must have produced a structure shift in
    the implied direction, and current price must still be within a sane
    distance of the entry zone.
    """
    rows = closed_candles(candles)
    if not rows or liquidity_sweep is None:
        return {"status": "none", "reason": "No valid liquidity event is currently in play."}
    last_index = len(rows) - 1
    age = last_index - liquidity_sweep.sweep_index
    if age > max_age_candles:
        return {"status": "expired", "reason": f"Most recent liquidity raid is {age} candles old (limit {max_age_candles})."}
    if not liquidity_sweep.valid:
        return {"status": "none", "reason": liquidity_sweep.reason}

    direction = liquidity_sweep.implied_direction
    event = structure.last_event
    shift_ok = (
        event is not None
        and event.direction == direction
        and event.break_index >= liquidity_sweep.sweep_index
    )
    if not shift_ok:
        return {
            "status": "awaiting_confirmation",
            "reason": "Liquidity was raided but no closed-candle structure shift has confirmed the reversal.",
            "sweep": liquidity_sweep.as_dict(),
        }

    candidates = [
        gap for gap in gaps
        if gap.type == direction
        and gap.formation_index >= liquidity_sweep.sweep_index
        and gap.classification in {QUALIFIED_FVG, TRADEABLE_FVG}
        and gap.status in {UNTOUCHED, PARTIALLY_MITIGATED}
    ]
    if not candidates:
        return {
            "status": "no_entry_zone",
            "reason": "Sweep and structure shift confirmed, but no unexpired qualified FVG formed in the impulse.",
            "sweep": liquidity_sweep.as_dict(),
            "structure_event": event.as_dict(),
        }

    zone = max(candidates, key=lambda g: (g.quality_score, g.formation_index))
    current_price = _close(rows[-1])
    distance = abs(current_price - zone.midpoint)
    if atr_value and atr_value > 0 and distance > atr_value * max_distance_atr:
        return {
            "status": "out_of_range",
            "reason": f"Price is {distance / atr_value:.1f} ATR away from the entry zone (limit {max_distance_atr}).",
            "sweep": liquidity_sweep.as_dict(),
            "zone": zone.as_dict(),
        }

    return {
        "status": "ready",
        "direction": "BUY" if direction == BULLISH else "SELL",
        "timeframe": timeframe,
        "sweep": liquidity_sweep.as_dict(),
        "structure_event": event.as_dict(),
        "zone": zone.as_dict(),
        "entry_zone": {"low": zone.low, "high": zone.high, "midpoint": zone.midpoint},
        "invalidation": zone.invalidation_price,
        "age_candles": age,
        "reason": "Recent liquidity raid, confirmed structure shift and an unexpired qualified entry zone.",
    }


def detect_fvg_playbook(
    candles: Sequence[dict[str, Any]],
    *,
    structure: StructureState,
    dealing_range: Any = None,
    liquidity_sweep: Any = None,
    atr_value: float | None = None,
    timeframe: str | None = None,
    max_retest_candles: int = DEFAULT_MAX_RETEST_CANDLES,
) -> dict[str, Any]:
    """One call that produces the complete, lifecycle-correct FVG picture."""
    gaps = detect_fair_value_gaps(
        candles, structure=structure, dealing_range=dealing_range,
        liquidity_sweep=liquidity_sweep, atr_value=atr_value, timeframe=timeframe,
        max_retest_candles=max_retest_candles,
    )
    inversions = detect_inversion_fvgs(candles, gaps, timeframe=timeframe, max_retest_candles=max_retest_candles)
    blocks = detect_order_blocks(candles, structure=structure, timeframe=timeframe)
    continuation = detect_sweep_continuation(
        candles, structure=structure, liquidity_sweep=liquidity_sweep,
        gaps=gaps, atr_value=atr_value, timeframe=timeframe,
    )
    return {
        "status": "ready",
        "timeframe": timeframe,
        "max_retest_candles": max_retest_candles,
        "fair_value_gaps": [gap.as_dict() for gap in gaps],
        "tradeable_gaps": [gap.as_dict() for gap in gaps if gap.tradeable],
        "inversion_fvgs": [item.as_dict() for item in inversions],
        "confirmed_inversions": [item.as_dict() for item in inversions if item.status == "CONFIRMED_IFVG"],
        "order_blocks": [block.as_dict() for block in blocks],
        "order_block": blocks[-1].as_dict() if blocks else None,
        "continuation": continuation,
    }
