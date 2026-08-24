from __future__ import annotations

from typing import Any


def _closes(candles: list[dict[str, Any]]) -> list[float]:
    return [float(c.get("close", 0)) for c in candles if float(c.get("close", 0)) > 0]


def ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    alpha = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def rsi(values: list[float], period: int = 14) -> float:
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    recent = changes[-period:]
    gains = sum(change for change in recent if change > 0) / max(1, len(recent))
    losses = sum(-change for change in recent if change < 0) / max(1, len(recent))
    if losses == 0:
        return 100.0 if gains else 50.0
    return 100 - (100 / (1 + gains / losses))


def atr(candles: list[dict[str, Any]], period: int = 14) -> float:
    ranges = [float(c.get("high", 0)) - float(c.get("low", 0)) for c in candles]
    recent = [value for value in ranges[-period:] if value > 0]
    return sum(recent) / max(1, len(recent))


def _macd(values: list[float]) -> tuple[float, float, float]:
    macd_values: list[float] = []
    fast_alpha = 2 / 13
    slow_alpha = 2 / 27
    fast_value = values[0]
    slow_value = values[0]
    for value in values:
        fast_value = fast_alpha * value + (1 - fast_alpha) * fast_value
        slow_value = slow_alpha * value + (1 - slow_alpha) * slow_value
        macd_values.append(fast_value - slow_value)
    macd_value = macd_values[-1]
    signal = ema(macd_values, 9)
    return macd_value, signal, macd_value - signal


def adx(candles: list[dict[str, Any]], period: int = 14) -> float:
    if len(candles) < 2:
        return 0.0
    directional_ranges: list[float] = []
    true_ranges: list[float] = []
    for previous, current in zip(candles, candles[1:]):
        high = float(current.get("high", 0))
        low = float(current.get("low", 0))
        previous_high = float(previous.get("high", 0))
        previous_low = float(previous.get("low", 0))
        up_move = max(0.0, high - previous_high)
        down_move = max(0.0, previous_low - low)
        directional_ranges.append(abs(up_move - down_move))
        true_ranges.append(max(high - low, abs(high - previous_low), abs(low - previous_high)))
    recent_tr = true_ranges[-period:]
    recent_directional = directional_ranges[-period:]
    average_tr = sum(recent_tr) / max(1, len(recent_tr))
    if average_tr <= 0:
        return 0.0
    return min(100.0, 100 * (sum(recent_directional) / max(1, len(recent_directional))) / average_tr)


def snapshot(candles: list[dict[str, Any]]) -> dict[str, float | str]:
    values = _closes(candles)
    if len(values) < 2:
        return {"status": "insufficient"}
    fast = ema(values, 20)
    slow = ema(values, 50)
    long = ema(values, 200)
    middle_values = values[-20:]
    middle = sum(middle_values) / len(middle_values)
    deviation = (sum((value - middle) ** 2 for value in middle_values) / len(middle_values)) ** 0.5
    macd, macd_signal, macd_histogram = _macd(values)
    return {
        "status": "ready",
        "ema_20": fast,
        "ema_50": slow,
        "ema_200": long,
        "rsi_14": rsi(values),
        "atr_14": atr(candles),
        "bollinger_middle": middle,
        "bollinger_upper": middle + 2 * deviation,
        "bollinger_lower": middle - 2 * deviation,
        "macd": macd,
        "macd_signal": macd_signal,
        "macd_histogram": macd_histogram,
        "adx_14": adx(candles),
        "last_close": values[-1],
    }
