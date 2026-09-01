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
    """Detect AMD phases from a meaningful closed-candle range and liquidity raid.

    This function produces structural evidence for the AMD strategy; it does
    not by itself authorize a trade. A complete AMD setup still requires the
    structure/displacement/entry checks performed by the strategy engine.
    """
    values = _closed(candles)
    lookback = 30
    if len(values) < lookback:
        return {
            "status": "insufficient", "phase": "unclear", "complete": False,
            "trade_filter": True, "required_candles": lookback,
            "available_candles": len(values), "missing_candles": lookback - len(values),
        }
    sample = values[-lookback:]
    accumulation_len = 20
    accumulation = sample[:accumulation_len]
    post = sample[accumulation_len:]
    range_high = max(_value(c, "high") for c in accumulation)
    range_low = min(_value(c, "low") for c in accumulation)
    widths = [_value(c, "high") - _value(c, "low") for c in accumulation if _value(c, "high") >= _value(c, "low")]
    average_range = sum(widths) / max(1, len(widths))
    close_span = max(_value(c, "close") for c in accumulation) - min(_value(c, "close") for c in accumulation)
    accumulation_valid = average_range > 0 and close_span <= average_range * 3.0
    raid = None
    raid_index = None
    for idx, candle in enumerate(post, start=accumulation_len):
        high, low, close = _value(candle, "high"), _value(candle, "low"), _value(candle, "close")
        if low < range_low and close > range_low:
            raid = "sell_side"
            raid_index = idx
        elif high > range_high and close < range_high:
            raid = "buy_side"
            raid_index = idx
        if raid:
            break
    # Distribution requires directional expansion after the raid.
    distribution_direction = None
    displacement = False
    if raid_index is not None:
        follow = values[raid_index + 1:]
        if follow:
            last = follow[-1]
            body = abs(_value(last, "close") - _value(last, "open"))
            recent_ranges = [_value(c, "high") - _value(c, "low") for c in values[max(0, raid_index - 4):raid_index] if _value(c, "high") >= _value(c, "low")]
            baseline = sum(recent_ranges) / max(1, len(recent_ranges))
            displacement = baseline > 0 and body >= baseline * 1.2
            if _value(last, "close") > _value(last, "open") and _value(last, "close") > range_high:
                distribution_direction = "BUY"
            elif _value(last, "close") < _value(last, "open") and _value(last, "close") < range_low:
                distribution_direction = "SELL"
            elif raid == "sell_side" and _value(last, "close") > range_low:
                distribution_direction = "BUY"
            elif raid == "buy_side" and _value(last, "close") < range_high:
                distribution_direction = "SELL"
    complete = bool(accumulation_valid and raid and distribution_direction and displacement)
    phase = "distribution" if complete else "manipulation" if accumulation_valid and raid else "accumulation" if accumulation_valid else "unclear"
    return {
        "status": "ready",
        "phase": phase,
        "complete": complete,
        "accumulation": accumulation_valid,
        "manipulation": bool(raid),
        "distribution": bool(distribution_direction),
        "direction": "bullish" if distribution_direction == "BUY" else "bearish" if distribution_direction == "SELL" else None,
        "trade_direction": distribution_direction,
        "raid_side": raid,
        "raid_index": raid_index,
        "range_high": range_high,
        "range_low": range_low,
        "range_width": range_high - range_low,
        "displacement": displacement,
        "lookback": lookback,
        "accumulation_candles": accumulation_len,
        "trade_filter": not complete,
    }

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
    """Expose the canonical IFVG playbook through the legacy evidence API."""
    from .fvg_engine import detect_fvg_playbook
    playbook = detect_fvg_playbook(candles)
    candidates = playbook.get("ifvg", []) if isinstance(playbook, dict) else []
    return {
        "status": playbook.get("status", "ready") if isinstance(playbook, dict) else "ready",
        "candidates": candidates,
        "confirmed": [x for x in candidates if x.get("status") in {"CONFIRMED_IFVG", "TRADEABLE_IFVG"}],
        "tradeable": bool(playbook.get("tradeable_ifvg")) if isinstance(playbook, dict) else False,
        "tradeable_candidates": playbook.get("tradeable_ifvg", []) if isinstance(playbook, dict) else [],
    }

