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


def assess_candles(
    candles: list[dict[str, Any]],
    timeframe: str,
    now: datetime | None = None,
    *,
    minimum_candles: int | None = None,
    require_closed: bool = True,
    symbol: str = "",
    trades_24_7: bool = False,
) -> dict[str, Any]:
    """Validate candle shape, history depth, chronology, closure, and freshness."""
    if not candles:
        return {"status": "missing", "reason": "No candles returned.", "available_candles": 0, "required_candles": minimum_candles or 0}
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
        if require_closed and candle.get("closed") is False:
            return {"status": "invalid", "reason": "Analysis dataset contains a forming candle."}
        timestamps.append(timestamp)
    if len(set(timestamps)) != len(timestamps):
        return {"status": "invalid", "reason": "Candle timestamps contain duplicates."}
    if timestamps != sorted(timestamps):
        return {"status": "invalid", "reason": "Candle timestamps are not chronological."}
    available = len(candles)
    required = int(minimum_candles or 0)
    if required and available < required:
        return {
            "status": "insufficient",
            "reason": f"Insufficient closed-candle history: {available}/{required} candles.",
            "available_candles": available,
            "required_candles": required,
            "missing_candles": required - available,
        }
    # -- gaps -------------------------------------------------------------
    interval = _TIMEFRAME_SECONDS.get(str(timeframe).upper(), 3600)
    gaps: list[dict[str, Any]] = []
    for previous, current_ts in zip(timestamps, timestamps[1:]):
        delta = current_ts - previous
        if delta > interval * 1.5:
            gaps.append({"from": previous, "to": current_ts,
                         "missing_candles": int(round(delta / interval)) - 1})

    latest = timestamps[-1]
    current = (now or datetime.now(timezone.utc)).timestamp()
    age = max(0.0, current - latest)

    # -- freshness, aware of the market schedule ---------------------------
    # A four-hour-old M5 candle on a Saturday is expected, not a data fault.
    # Conflating "market is closed" with "the feed is broken" is what caused
    # the previous single `stale` status to be useless.
    schedule = market_state(symbol, now=now, trades_24_7=trades_24_7)
    maximum_age = interval * 3
    if not schedule["open"]:
        status = "market_closed"
        reason = (f"{schedule['reason']} Latest closed candle is {age:.0f}s old, which is expected "
                  "while the market is closed.")
    elif age > maximum_age:
        status = "stale"
        reason = (f"Market is open but the latest closed {timeframe} candle is {age:.0f}s old "
                  f"(limit {maximum_age:.0f}s). The data feed is behind.")
    else:
        status = "fresh"
        reason = "Latest closed candle is within the freshness window."

    if gaps and status == "fresh":
        status = "gapped"
        reason = (f"Feed is current but {len(gaps)} gap(s) are present in the history "
                  f"({sum(g['missing_candles'] for g in gaps)} missing candles).")

    return {
        "status": status,
        "tradeable": status in {"fresh", "gapped"},
        "market_open": schedule["open"],
        "market_state_reason": schedule["reason"],
        "age_seconds": age,
        "maximum_age_seconds": maximum_age,
        "latest_timestamp": latest,
        "available_candles": available,
        "required_candles": required,
        "missing_candles": max(0, required - available),
        "gaps": gaps,
        "reason": reason,
    }


#: Distinct, machine-readable data blockers. Previously every one of these
#: collapsed into a single "stale" status, which made them unactionable.
BLOCKER_CODES = {
    "missing": "NO_DATA",
    "invalid": "MALFORMED_DATA",
    "unknown": "MISSING_TIMESTAMPS",
    "insufficient": "INSUFFICIENT_HISTORY",
    "stale": "FEED_BEHIND",
    "market_closed": "MARKET_CLOSED",
    "gapped": "HISTORY_GAPS",
    "fresh": None,
}


def blocker_for(assessment: dict[str, Any]) -> str | None:
    """Map a candle assessment onto a precise, distinct blocker code."""
    return BLOCKER_CODES.get(str(assessment.get("status")), "UNKNOWN_DATA_STATE")


def market_state(symbol: str = "", now: datetime | None = None,
                 trades_24_7: bool = False) -> dict[str, Any]:
    """Whether the instrument's market should currently be quoting."""
    from .session_levels import market_open as _market_open
    return _market_open(now, trades_24_7=trades_24_7)
