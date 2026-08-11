from __future__ import annotations

from typing import Any


def _high(candle: dict[str, Any]) -> float:
    return float(candle.get("high", 0) or 0)


def _low(candle: dict[str, Any]) -> float:
    return float(candle.get("low", 0) or 0)


def _close(candle: dict[str, Any]) -> float:
    return float(candle.get("close", 0) or 0)


def _open(candle: dict[str, Any]) -> float:
    return float(candle.get("open", 0) or 0)


def detect_smc(candles: list[dict[str, Any]], direction: str | None = None) -> dict[str, Any]:
    """Return observable SMC evidence without treating any item as an entry signal."""
    if len(candles) < 5:
        return {"status": "insufficient", "valid": False, "reason": "At least five candles are required for SMC context."}

    recent = candles[-20:]
    highs = [_high(candle) for candle in recent]
    lows = [_low(candle) for candle in recent]
    last = candles[-1]
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

    fair_value_gaps: list[dict[str, float | str]] = []
    for first, _, third in zip(candles[-10:-2], candles[-9:-1], candles[-8:]):
        if _high(first) < _low(third):
            fair_value_gaps.append({"type": "bullish", "low": _high(first), "high": _low(third)})
        elif _low(first) > _high(third):
            fair_value_gaps.append({"type": "bearish", "low": _high(third), "high": _low(first)})

    range_high = max(highs)
    range_low = min(lows)
    equilibrium = (range_high + range_low) / 2
    location = "premium" if _close(last) > equilibrium else "discount"

    displacement = abs(_close(last) - _open(last)) > (range_high - range_low) * 0.15
    structure_shift = None
    if _close(last) > prior_high:
        structure_shift = "bullish_BOS"
    elif _close(last) < prior_low:
        structure_shift = "bearish_BOS"
    elif sweep:
        structure_shift = "CHoCH_after_liquidity_sweep"

    order_block = None
    if displacement and len(candles) >= 2:
        previous = candles[-2]
        if _close(last) > _open(last) and _close(previous) < _open(previous):
            order_block = {"type": "bullish", "high": _high(previous), "low": _low(previous)}
        elif _close(last) < _open(last) and _close(previous) > _open(previous):
            order_block = {"type": "bearish", "high": _high(previous), "low": _low(previous)}

    evidence = {
        "status": "ready",
        "valid": True,
        "equal_highs": equal_highs,
        "equal_lows": equal_lows,
        "liquidity_sweep": sweep,
        "structure_shift": structure_shift,
        "displacement": displacement,
        "fair_value_gaps": fair_value_gaps,
        "order_block": order_block,
        "dealing_range": {"high": range_high, "low": range_low, "equilibrium": equilibrium},
        "location": location,
    }
    if direction:
        expected = "bullish" if direction == "BUY" else "bearish"
        evidence["directional_confluence"] = (
            structure_shift in {f"{expected}_BOS", "CHoCH_after_liquidity_sweep"}
            or any(gap["type"] == expected for gap in fair_value_gaps)
            or (order_block and order_block["type"] == expected)
        )
    return evidence
