from __future__ import annotations

from typing import Any


class ZoneRegistry:
    """Keep zone identity and lifecycle continuity across repeated scans."""

    def __init__(self) -> None:
        self._zones: dict[str, dict[str, Any]] = {}

    def observe(self, zone: dict[str, Any], timeframe: str | None, kind: str) -> dict[str, Any]:
        identity = f"{timeframe or '-'}:{kind}:{zone.get('formation_index')}:{zone.get('low')}:{zone.get('high')}"
        previous = self._zones.get(identity, {})
        zone = {**previous, **zone, "zone_id": identity, "timeframe": timeframe, "kind": kind}
        self._zones[identity] = zone
        return zone

    def prune(self, timeframe: str | None, current_index: int, max_age: int = 100) -> None:
        """Remove zones that are too old to be actionable for the current scan.

        Registry continuity is useful, but retaining every historical zone forever
        makes old zones look current to downstream consumers.  Age is measured in
        candles on the same timeframe.
        """
        cutoff = current_index - max(1, int(max_age))
        doomed = []
        for key, zone in self._zones.items():
            if timeframe is not None and zone.get("timeframe") != timeframe:
                continue
            try:
                formation = int(zone.get("formation_index"))
            except (TypeError, ValueError):
                continue
            if formation < cutoff:
                doomed.append(key)
        for key in doomed:
            self._zones.pop(key, None)

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self._zones.values())


def _high(candle: dict[str, Any]) -> float:
    return float(candle.get("high", 0) or 0)


def _low(candle: dict[str, Any]) -> float:
    return float(candle.get("low", 0) or 0)


def _close(candle: dict[str, Any]) -> float:
    return float(candle.get("close", 0) or 0)


def _open(candle: dict[str, Any]) -> float:
    return float(candle.get("open", 0) or 0)


def _swing_points(candles: list[dict[str, Any]], strength: int = 2) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    highs = []
    lows = []
    for index in range(strength, len(candles) - strength):
        high = _high(candles[index])
        low = _low(candles[index])
        window = candles[index - strength:index + strength + 1]
        if high >= max(_high(item) for item in window):
            highs.append((index, high))
        if low <= min(_low(item) for item in window):
            lows.append((index, low))
    return highs, lows


def _timestamp(candle: dict[str, Any]) -> str | None:
    return candle.get("time") or candle.get("timestamp")


def _closed_candles(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Exclude an explicitly live candle; feeds without that flag remain usable."""
    if candles and candles[-1].get("closed") is False:
        return candles[:-1]
    return candles


def _structure(candles: list[dict[str, Any]]) -> dict[str, Any]:
    highs, lows = _swing_points(candles)
    labels = []
    for points, name in ((highs, "high"), (lows, "low")):
        for previous, current in zip(points, points[1:]):
            labels.append({"type": "HH" if current[1] > previous[1] else "LH" if current[1] < previous[1] else "EQ_" + name.upper(), "index": current[0], "price": current[1]})
    bullish = len(highs) >= 2 and len(lows) >= 2 and highs[-1][1] > highs[-2][1] and lows[-1][1] > lows[-2][1]
    bearish = len(highs) >= 2 and len(lows) >= 2 and highs[-1][1] < highs[-2][1] and lows[-1][1] < lows[-2][1]
    points = [
        {"index": index, "timestamp": _timestamp(candles[index]), "price": price, "timeframe": candles[index].get("timeframe"), "type": "swing_high", "strength": 2, "broken": False, "valid": True}
        for index, price in highs
    ] + [
        {"index": index, "timestamp": _timestamp(candles[index]), "price": price, "timeframe": candles[index].get("timeframe"), "type": "swing_low", "strength": 2, "broken": False, "valid": True}
        for index, price in lows
    ]
    return {"swing_highs": highs, "swing_lows": lows, "structural_points": points, "labels": labels, "bias": "bullish" if bullish else "bearish" if bearish else "sideways"}


def detect_smc(candles: list[dict[str, Any]], direction: str | None = None, timeframe: str | None = None, registry: ZoneRegistry | None = None) -> dict[str, Any]:
    """Return observable SMC evidence without treating any item as an entry signal."""
    candles = _closed_candles(candles)
    if len(candles) < 5:
        return {"status": "insufficient", "valid": False, "reason": "At least five candles are required for SMC context."}

    recent = candles[-200:]
    highs = [_high(candle) for candle in recent]
    lows = [_low(candle) for candle in recent]
    last = candles[-1]
    if registry is not None:
        zone_age = {"M1": 80, "M5": 80, "M15": 120, "M30": 140, "H1": 160, "H4": 180, "D1": 220, "W1": 260, "MN": 300}.get(str(timeframe or "").upper(), 140)
        registry.prune(timeframe, len(candles) - 1, zone_age)
    structure = _structure(recent)
    prior = candles[-6:-1]
    prior_high = max(_high(candle) for candle in prior)
    prior_low = min(_low(candle) for candle in prior)

    sweep = None
    if _high(last) > prior_high and _close(last) < prior_high:
        sweep = "buy_side_liquidity_sweep"
    elif _low(last) < prior_low and _close(last) > prior_low:
        sweep = "sell_side_liquidity_sweep"

    tolerance = max((max(highs) - min(lows)) * 0.001, 1e-8)
    equal_highs = abs(highs[-1] - highs[-2]) <= tolerance
    equal_lows = abs(lows[-1] - lows[-2]) <= tolerance

    range_high = max(highs)
    range_low = min(lows)
    equilibrium = (range_high + range_low) / 2
    location = "premium" if _close(last) > equilibrium else "discount"

    bodies = [abs(_close(candle) - _open(candle)) for candle in recent]
    average_body = sum(bodies[:-1]) / max(len(bodies) - 1, 1)
    displacement = abs(_close(last) - _open(last)) >= max(average_body * 1.5, (range_high - range_low) * 0.05)
    structure_shift = None
    if _close(last) > prior_high:
        structure_shift = "bullish_BOS"
    elif _close(last) < prior_low:
        structure_shift = "bearish_BOS"
    elif sweep and structure["bias"] in {"bullish", "bearish"}:
        structure_shift = f"{structure['bias']}_CHoCH_after_liquidity_sweep"
    for point in structure["structural_points"]:
        point["timeframe"] = timeframe
    structure_event = None
    if structure_shift:
        bullish_event = structure_shift.startswith("bullish")
        structure_event = {
            "type": "BOS" if "BOS" in structure_shift else "CHoCH",
            "direction": "bullish" if bullish_event else "bearish",
            "broken_level": prior_high if bullish_event else prior_low,
            "break_price": _close(last),
            "break_timestamp": _timestamp(last),
            "timeframe": timeframe,
            "confirmation": "close" if (bullish_event and _close(last) > prior_high) or (not bullish_event and _close(last) < prior_low) else "sweep_reaction",
        }

    fair_value_gaps: list[dict[str, Any]] = []
    fvg_candles = candles[-150:]
    for gap_index, (first, middle, third) in enumerate(zip(fvg_candles[:-2], fvg_candles[1:-1], fvg_candles[2:]), start=max(0, len(candles) - len(fvg_candles)) + 1):
        gap_low = gap_high = None
        gap_type = None
        if _high(first) < _low(third):
            gap_type, gap_low, gap_high = "bullish", _high(first), _low(third)
        elif _low(first) > _high(third):
            gap_type, gap_low, gap_high = "bearish", _high(third), _low(first)
        if gap_type:
            future_candles = candles[gap_index + 2:]
            touched = any(_low(candle) <= gap_high and _high(candle) >= gap_low for candle in future_candles)
            fully_mitigated = any((_low(candle) <= gap_low if gap_type == "bullish" else _high(candle) >= gap_high) for candle in future_candles)
            invalidated = any((_close(candle) < gap_low if gap_type == "bullish" else _close(candle) > gap_high) for candle in future_candles)
            current_price = _close(last)
            in_zone = gap_low <= current_price <= gap_high
            near_zone = gap_low - (gap_high - gap_low) <= current_price <= gap_high + (gap_high - gap_low)
            status = "INVALIDATED" if invalidated else "FULLY_MITIGATED" if fully_mitigated else "PARTIALLY_MITIGATED" if touched else "UNTOUCHED"
            associated = gap_index >= len(candles) - 20 and displacement
            qualified = associated and bool(structure_shift) and structure["bias"] == gap_type
            gap = {
                "type": gap_type, "low": gap_low, "high": gap_high,
                "formation_index": gap_index + 1, "formation_timestamp": _timestamp(middle),
                "size": gap_high - gap_low, "status": status,
                "classification": "TRADEABLE_FVG" if qualified and status not in {"FULLY_MITIGATED", "INVALIDATED"} else "QUALIFIED_FVG" if qualified else "TECHNICAL_FVG",
                "associated_displacement": associated, "associated_structure_shift": bool(structure_shift),
                "formed_after_liquidity_event": sweep is not None,
                "in_dealing_range": range_low <= gap_low <= range_high and range_low <= gap_high <= range_high,
                "aligned_with_structure": structure["bias"] == gap_type,
                "distance_from_price": abs(_close(last) - (gap_low + gap_high) / 2),
                "price_in_zone": in_zone,
                "price_near_zone": near_zone,
                "retracement_status": "CURRENT_RETRACEMENT" if in_zone else "AWAITING_RETRACEMENT",
                "invalidation_status": "INVALIDATED" if invalidated else "VALID",
                "score": 2 + (2 if associated else 0) + (1 if structure_shift else 0),
            }
            fair_value_gaps.append(registry.observe(gap, timeframe, "FVG") if registry else gap)

    order_blocks: list[dict[str, Any]] = []
    for event_index in range(2, len(candles)):
        event = candles[event_index]
        prior_bodies = [abs(_close(item) - _open(item)) for item in candles[max(0, event_index - 20):event_index]]
        event_displacement = abs(_close(event) - _open(event)) >= max((sum(prior_bodies) / max(len(prior_bodies), 1)) * 1.5, (range_high - range_low) * 0.05)
        origin = candles[event_index - 1]
        event_type = "bullish" if _close(event) > _open(event) and _close(origin) < _open(origin) else "bearish" if _close(event) < _open(event) and _close(origin) > _open(origin) else None
        if not event_displacement or not event_type:
            continue
        invalidated = any((_close(item) < _low(origin) if event_type == "bullish" else _close(item) > _high(origin)) for item in candles[event_index + 1:])
        touched = any(_low(item) <= _high(origin) and _high(item) >= _low(origin) for item in candles[event_index + 1:])
        block = {
            "type": event_type, "high": _high(origin), "low": _low(origin),
            "score": 2 + (2 if event_displacement else 0) + (1 if structure_shift else 0),
            "classification": "TRADEABLE_OB" if structure_shift and not invalidated else "CANDIDATE_OB",
            "status": "INVALIDATED" if invalidated else "PARTIALLY_MITIGATED" if touched else "UNMITIGATED",
            "formation_index": event_index - 1, "formation_timestamp": _timestamp(origin),
            "displacement_index": event_index, "displacement_timestamp": _timestamp(event),
            "price_in_zone": _low(origin) <= _close(last) <= _high(origin),
            "invalidation_status": "INVALIDATED" if invalidated else "VALID",
            "associated_displacement": True,
        }
        order_blocks.append(registry.observe(block, timeframe, "OB") if registry else block)
    order_block = order_blocks[-1] if order_blocks else None

    sweep_supports = (
        sweep == "sell_side_liquidity_sweep" and structure_shift and structure_shift.startswith("bullish")
    ) or (
        sweep == "buy_side_liquidity_sweep" and structure_shift and structure_shift.startswith("bearish")
    )
    expected_location = "discount" if structure["bias"] == "bullish" else "premium" if structure["bias"] == "bearish" else None
    directional_gap = any(gap["type"] == structure["bias"] and gap["classification"] in {"QUALIFIED_FVG", "TRADEABLE_FVG"} for gap in fair_value_gaps)
    directional_ob = isinstance(order_block, dict) and order_block["type"] == structure["bias"] and order_block["classification"] == "TRADEABLE_OB"
    setup_model = "SWEEP_REVERSAL" if sweep else "BOS_CONTINUATION"
    sequence = {"liquidity": bool(sweep), "structural_event": bool(structure_shift), "displacement": displacement, "smc_zone": directional_gap or directional_ob, "retracement": any(zone.get("status") == "PARTIALLY_MITIGATED" for zone in fair_value_gaps), "entry_confirmation": False, "complete": False}
    evidence = {
        "status": "ready",
        "valid": True,
        "equal_highs": equal_highs,
        "equal_lows": equal_lows,
        "liquidity_sweep": sweep,
        "structure_shift": structure_shift,
        "structure_event": structure_event,
        "displacement": displacement,
        "fair_value_gaps": fair_value_gaps,
        "order_block": order_block,
        "order_blocks": order_blocks,
        "dealing_range": {"high": range_high, "low": range_low, "equilibrium": equilibrium},
        "location": location,
        "preferred_location": expected_location,
        "target_liquidity": {
            "type": "buy_side_liquidity" if structure["bias"] == "bullish" else "sell_side_liquidity",
            "price": max(highs) if structure["bias"] == "bullish" else min(lows),
            "timeframe": timeframe,
            "basis": "opposing structural swing",
        },
        "structure": structure,
        "sequence": sequence,
        "setup_model": setup_model,
        "decision": "WAIT" if any(sequence.values()) and not sequence["complete"] else "NO_SETUP",
        "decision_reasons": ["SMC zones are monitoring locations, not entries.", "Wait for retracement and lower-timeframe confirmation."],
        "liquidity_sequence": {
            "event": sweep or "none",
            "reaction": "confirmed" if displacement else "not_confirmed",
            "displacement": displacement,
            "structural_confirmation": structure_shift or "none",
            "directional_support": bool(sweep_supports),
        },
    }
    if direction:
        expected = "bullish" if direction == "BUY" else "bearish"
        evidence["directional_confluence"] = (
            structure_shift in {f"{expected}_BOS", "CHoCH_after_liquidity_sweep"}
            or any(gap["type"] == expected for gap in fair_value_gaps)
            or (order_block and order_block["type"] == expected)
        )
    return evidence
