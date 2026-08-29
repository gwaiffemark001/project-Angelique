"""Market-data quality checks shared by analysis and execution."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from core.price_units import pip_size_from_specs


_TIMEFRAME_SECONDS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
    "W1": 604800,
    "MN": 2592000,
}


def _timestamp_seconds(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value / 1000 if value > 10_000_000_000 else value)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            return None
    return None


def assess_candles(candles: list[dict[str, Any]], timeframe: str, now: datetime | None = None) -> dict[str, Any]:
    """Validate candle shape, ordering, and freshness before analysis."""
    if not candles:
        return {"status": "missing", "reason": "No candles returned."}
    timestamps = []
    for index, candle in enumerate(candles):
        if not isinstance(candle, dict):
            return {"status": "invalid", "reason": f"Candle {index} is not an object."}
        try:
            open_price = float(candle["open"])
            high = float(candle["high"])
            low = float(candle["low"])
            close = float(candle["close"])
        except (KeyError, TypeError, ValueError):
            return {"status": "invalid", "reason": f"Candle {index} has invalid OHLC values."}
        if min(open_price, high, low, close) <= 0 or high < max(open_price, close) or low > min(open_price, close) or high < low:
            return {"status": "invalid", "reason": f"Candle {index} violates OHLC price bounds."}
        timestamp = _timestamp_seconds(candle.get("time", candle.get("timestamp")))
        if timestamp is None:
            return {"status": "unknown", "reason": f"Candle {index} has no valid timestamp."}
        timestamps.append(timestamp)
    if len(set(timestamps)) != len(timestamps):
        return {"status": "invalid", "reason": "Candle timestamps contain duplicates."}
    if timestamps != sorted(timestamps):
        return {"status": "invalid", "reason": "Candle timestamps are not chronological."}
    latest = timestamps[-1]
    current = (now or datetime.now(timezone.utc)).timestamp()
    interval = _TIMEFRAME_SECONDS.get(str(timeframe).upper(), 3600)
    age = max(0.0, current - latest)
    maximum_age = interval * 3
    return {
        "status": "stale" if age > maximum_age else "fresh",
        "age_seconds": age,
        "maximum_age_seconds": maximum_age,
        "latest_timestamp": latest,
        "reason": f"Latest candle is {age:.0f}s old." if age > maximum_age else "Latest candle is within freshness window.",
    }
