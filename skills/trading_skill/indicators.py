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


def snapshot(candles: list[dict[str, Any]]) -> dict[str, float | str]:
    values = _closes(candles)
    if len(values) < 2:
        return {"status": "insufficient"}
    fast = ema(values, 20)
    slow = ema(values, 50)
    middle_values = values[-20:]
    middle = sum(middle_values) / len(middle_values)
    deviation = (sum((value - middle) ** 2 for value in middle_values) / len(middle_values)) ** 0.5
    macd = ema(values, 12) - ema(values, 26)
    return {
        "status": "ready",
        "ema_20": fast,
        "ema_50": slow,
        "rsi_14": rsi(values),
        "atr_14": atr(candles),
        "bollinger_middle": middle,
        "bollinger_upper": middle + 2 * deviation,
        "bollinger_lower": middle - 2 * deviation,
        "macd": macd,
        "last_close": values[-1],
    }
