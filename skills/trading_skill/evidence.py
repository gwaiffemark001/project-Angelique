"""Deterministic supporting evidence for the trading decision pipeline."""

from __future__ import annotations

from typing import Any


def _value(candle: dict[str, Any], key: str) -> float:
    return float(candle.get(key, 0) or 0)


def _closed(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return candles[:-1] if candles and candles[-1].get("closed") is False else candles


def detect_candle_pattern(candles: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify the latest closed candle; never declares a trade setup."""
    values = _closed(candles)
    if not values:
        return {"status": "insufficient", "pattern": "unknown", "direction": None, "confirmation": False}
    candle = values[-1]
    open_price, high, low, close = (_value(candle, key) for key in ("open", "high", "low", "close"))
    if min(open_price, high, low, close) <= 0 or high < max(open_price, close) or low > min(open_price, close):
        return {"status": "invalid", "pattern": "unknown", "direction": None, "confirmation": False}
    body = abs(close - open_price)
    full_range = max(high - low, 1e-12)
    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low
    body_ratio = body / full_range
    direction = "bullish" if close > open_price else "bearish" if close < open_price else "neutral"
    pattern = "doji" if body_ratio <= 0.1 else "strong_bullish_body" if body_ratio >= 0.7 and direction == "bullish" else "strong_bearish_body" if body_ratio >= 0.7 and direction == "bearish" else "neutral_candle"
    if lower_wick >= body * 2 and upper_wick <= body and direction != "bearish":
        pattern = "hammer"
    elif upper_wick >= body * 2 and lower_wick <= body and direction != "bullish":
        pattern = "shooting_star"
    if len(values) >= 2:
        previous = values[-2]
        previous_open, previous_close = _value(previous, "open"), _value(previous, "close")
        if direction == "bullish" and previous_close < previous_open and open_price <= previous_close and close >= previous_open:
            pattern = "bullish_engulfing"
        elif direction == "bearish" and previous_close > previous_open and open_price >= previous_close and close <= previous_open:
            pattern = "bearish_engulfing"
        elif high <= _value(previous, "high") and low >= _value(previous, "low"):
            pattern = "inside_bar"
        elif high >= _value(previous, "high") and low <= _value(previous, "low"):
            pattern = "outside_bar"
    return {"status": "ready", "pattern": pattern, "direction": direction, "body_ratio": round(body_ratio, 6), "confirmation": pattern not in {"doji", "neutral_candle"}}


def detect_amd_phase(candles: list[dict[str, Any]]) -> dict[str, Any]:
    """Detect a conservative accumulation/manipulation/distribution phase."""
    values = _closed(candles)
    if len(values) < 12:
        return {"status": "insufficient", "phase": "unclear", "complete": False, "trade_filter": True}
    ranges = [_value(candle, "high") - _value(candle, "low") for candle in values]
    midpoint = len(values) // 2
    early, recent = ranges[-12:-4], ranges[-4:]
    average_early = sum(early) / max(len(early), 1)
    recent_range = sum(recent) / max(len(recent), 1)
    expansion = recent_range >= average_early * 1.5
    early_closes = [_value(candle, "close") for candle in values[-12:-4]]
    early_span = max(early_closes) - min(early_closes)
    accumulation = early_span <= max(average_early * 2, 1e-12)
    manipulation = expansion and any(_value(candle, "high") > max(_value(item, "high") for item in values[-12:-4]) or _value(candle, "low") < min(_value(item, "low") for item in values[-12:-4]) for candle in values[-4:])
    last_direction = "bullish" if _value(values[-1], "close") > _value(values[-1], "open") else "bearish" if _value(values[-1], "close") < _value(values[-1], "open") else "neutral"
    phase = "distribution" if accumulation and manipulation and last_direction == "bearish" else "accumulation" if accumulation else "manipulation" if manipulation else "unclear"
    return {"status": "ready", "phase": phase, "complete": False, "accumulation": accumulation, "manipulation": manipulation, "distribution": phase == "distribution", "direction": last_direction, "trade_filter": True}


def _swings(candles: list[dict[str, Any]], strength: int = 2) -> tuple[list[float], list[float]]:
    highs, lows = [], []
    for index in range(strength, len(candles) - strength):
        window = candles[index - strength:index + strength + 1]
        high, low = _value(candles[index], "high"), _value(candles[index], "low")
        if high >= max(_value(item, "high") for item in window):
            highs.append(high)
        if low <= min(_value(item, "low") for item in window):
            lows.append(low)
    return highs, lows


def detect_wave_context(candles: list[dict[str, Any]]) -> dict[str, Any]:
    """Return coarse impulse/correction/range context, not Elliott counts."""
    values = _closed(candles)
    if len(values) < 9:
        return {"status": "insufficient", "phase": "unclear", "direction": None, "supporting_only": True}
    highs, lows = _swings(values)
    if len(highs) < 2 or len(lows) < 2:
        return {"status": "ready", "phase": "unclear", "direction": None, "supporting_only": True}
    rising = highs[-1] > highs[-2] and lows[-1] > lows[-2]
    falling = highs[-1] < highs[-2] and lows[-1] < lows[-2]
    closes = [_value(candle, "close") for candle in values[-8:]]
    span = max(closes) - min(closes)
    average_range = sum(_value(candle, "high") - _value(candle, "low") for candle in values[-8:]) / 8
    phase = "impulse" if rising or falling else "range" if span <= average_range * 3 else "correction"
    return {"status": "ready", "phase": phase, "direction": "bullish" if rising else "bearish" if falling else None, "swing_highs": highs[-4:], "swing_lows": lows[-4:], "supporting_only": True}


def detect_ifvg(candles: list[dict[str, Any]], fair_value_gaps: list[dict[str, Any]]) -> dict[str, Any]:
    """Detect an IFVG only after invalidation and an opposite-side retest."""
    values = _closed(candles)
    candidates = []
    for gap in fair_value_gaps:
        if not isinstance(gap, dict) or gap.get("status") != "INVALIDATED":
            continue
        low, high = float(gap.get("low", 0) or 0), float(gap.get("high", 0) or 0)
        if low <= 0 or high <= low:
            continue
        original = gap.get("type")
        flipped = "bearish" if original == "bullish" else "bullish"
        try:
            formation_index = max(0, int(gap.get("formation_index", 0)) + 1)
        except (TypeError, ValueError):
            formation_index = 0
        post_invalidation = values[formation_index:]
        retest = any(low <= _value(candle, "close") <= high for candle in post_invalidation[-5:])
        candidates.append({"type": flipped, "low": low, "high": high, "source_fvg": gap.get("zone_id") or gap.get("formation_index"), "status": "CONFIRMED_IFVG" if retest else "IFVG_CANDIDATE", "retest": retest, "entry_confirmation": False})
    return {"status": "ready", "candidates": candidates, "confirmed": [item for item in candidates if item["status"] == "CONFIRMED_IFVG"], "tradeable": False}
