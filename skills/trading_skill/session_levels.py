"""Session and daily reference levels with correct calendar/timezone handling.

Fixes the P0 bug where ``previous_day_high`` was ``max(high of every candle
before today)`` -- effectively the all-time high of the series. Previous-day
levels are now computed from the **immediately preceding trading day only**,
in an explicit timezone, and the asset's trading schedule is respected
(crypto trades 24/7 and does not inherit FX weekend behaviour).
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone, date
from typing import Any, Sequence
from zoneinfo import ZoneInfo

#: FX/metals reference day boundary. The MT5 "trading day" for FX conventionally
#: rolls at 17:00 New York, which is what most session tooling means by
#: "previous day". Configurable per call.
DEFAULT_DAY_TIMEZONE = "America/New_York"
DEFAULT_DAY_ROLLOVER_HOUR = 17

SESSIONS: dict[str, dict[str, Any]] = {
    "SYDNEY": {"timezone": "Australia/Sydney", "start": 7.0, "end": 16.0},
    "TOKYO": {"timezone": "Asia/Tokyo", "start": 9.0, "end": 18.0},
    "LONDON": {"timezone": "Europe/London", "start": 8.0, "end": 16.5},
    "NEW_YORK": {"timezone": "America/New_York", "start": 8.0, "end": 17.0},
}

#: ICT-style kill zones, in the local time of the named market centre.
KILL_ZONES: dict[str, dict[str, Any]] = {
    "ASIAN_RANGE": {"timezone": "Asia/Tokyo", "start": 0.0, "end": 5.0},
    "LONDON_OPEN": {"timezone": "Europe/London", "start": 7.0, "end": 10.0},
    "NEW_YORK_OPEN": {"timezone": "America/New_York", "start": 7.0, "end": 10.0},
    "LONDON_CLOSE": {"timezone": "Europe/London", "start": 15.0, "end": 17.0},
}


def to_datetime(value: Any) -> datetime | None:
    """Parse an MT5 epoch (s or ms) or an ISO-8601 string into aware UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 10_000_000_000:      # milliseconds
            seconds /= 1000.0
        if seconds <= 0:
            return None
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _candle_time(candle: dict[str, Any]) -> datetime | None:
    return to_datetime(candle.get("time", candle.get("timestamp")))


def _f(candle: dict[str, Any], key: str) -> float:
    try:
        return float(candle.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def trading_day_of(
    moment: datetime,
    *,
    tz_name: str = DEFAULT_DAY_TIMEZONE,
    rollover_hour: int | None = DEFAULT_DAY_ROLLOVER_HOUR,
) -> date:
    """Map an instant onto its trading day in ``tz_name``.

    When ``rollover_hour`` is set (FX/metals), anything at or after that local
    hour belongs to the *next* calendar trading day, matching the MT5 daily bar.
    Pass ``rollover_hour=None`` for 24/7 assets that use plain calendar days.
    """
    local = moment.astimezone(ZoneInfo(tz_name))
    if rollover_hour is not None and local.hour >= rollover_hour:
        return (local + timedelta(days=1)).date()
    return local.date()


@dataclass(frozen=True)
class DayLevels:
    trading_day: str | None
    high: float | None
    low: float | None
    open: float | None
    close: float | None
    candle_count: int
    source_timeframe: str | None
    timezone_name: str
    rollover_hour: int | None
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def group_by_trading_day(
    candles: Sequence[dict[str, Any]],
    *,
    tz_name: str = DEFAULT_DAY_TIMEZONE,
    rollover_hour: int | None = DEFAULT_DAY_ROLLOVER_HOUR,
) -> dict[date, list[dict[str, Any]]]:
    grouped: dict[date, list[dict[str, Any]]] = {}
    for candle in candles or []:
        moment = _candle_time(candle)
        if moment is None:
            continue
        grouped.setdefault(trading_day_of(moment, tz_name=tz_name, rollover_hour=rollover_hour), []).append(candle)
    return grouped


def _levels_for(day: date | None, rows: list[dict[str, Any]], tf, tz_name, rollover_hour, reason) -> DayLevels:
    if not rows:
        return DayLevels(day.isoformat() if day else None, None, None, None, None, 0, tf, tz_name, rollover_hour, reason)
    highs = [_f(c, "high") for c in rows if _f(c, "high") > 0]
    lows = [_f(c, "low") for c in rows if _f(c, "low") > 0]
    return DayLevels(
        trading_day=day.isoformat() if day else None,
        high=max(highs) if highs else None,
        low=min(lows) if lows else None,
        open=_f(rows[0], "open") or None,
        close=_f(rows[-1], "close") or None,
        candle_count=len(rows),
        source_timeframe=tf,
        timezone_name=tz_name,
        rollover_hour=rollover_hour,
        reason=reason,
    )


def daily_levels(
    candles: Sequence[dict[str, Any]],
    *,
    timeframe: str | None = None,
    now: datetime | None = None,
    tz_name: str = DEFAULT_DAY_TIMEZONE,
    rollover_hour: int | None = DEFAULT_DAY_ROLLOVER_HOUR,
    trades_24_7: bool = False,
) -> dict[str, Any]:
    """Return current-day and *immediately preceding* trading-day levels.

    ``previous_day_high`` / ``previous_day_low`` are taken from the single most
    recent trading day that has data **before** the current one -- never from
    the whole history. Weekend/holiday gaps are handled by taking the most
    recent day that actually has candles, and that day is reported explicitly so
    the caller can see it (e.g. Friday when it is Monday).
    """
    if trades_24_7:
        tz_name, rollover_hour = "UTC", None
    grouped = group_by_trading_day(candles, tz_name=tz_name, rollover_hour=rollover_hour)
    if not grouped:
        return {
            "status": "unavailable",
            "reason": "No candle carried a parsable timestamp.",
            "current_day": _levels_for(None, [], timeframe, tz_name, rollover_hour, "no data").as_dict(),
            "previous_day": _levels_for(None, [], timeframe, tz_name, rollover_hour, "no data").as_dict(),
        }
    reference = now or datetime.now(timezone.utc)
    today = trading_day_of(reference, tz_name=tz_name, rollover_hour=rollover_hour)
    days = sorted(grouped)
    current_day = today if today in grouped else days[-1]
    earlier = [day for day in days if day < current_day]
    previous_day = earlier[-1] if earlier else None

    gap_days = (current_day - previous_day).days if previous_day else None
    previous_reason = (
        "no previous trading day in the supplied history" if previous_day is None
        else f"immediately preceding trading day with data ({gap_days} calendar day(s) back)"
    )
    return {
        "status": "ready" if previous_day else "partial",
        "timezone": tz_name,
        "rollover_hour": rollover_hour,
        "trading_days_available": [day.isoformat() for day in days[-10:]],
        "current_day": _levels_for(current_day, grouped[current_day], timeframe, tz_name, rollover_hour,
                                   "current trading day").as_dict(),
        "previous_day": _levels_for(previous_day, grouped.get(previous_day, []), timeframe, tz_name, rollover_hour,
                                    previous_reason).as_dict(),
    }


def previous_day_high_low(candles: Sequence[dict[str, Any]], **kwargs: Any) -> tuple[float | None, float | None]:
    """Convenience accessor used by the SMC/liquidity layer."""
    levels = daily_levels(candles, **kwargs)
    previous = levels.get("previous_day", {})
    return previous.get("high"), previous.get("low")


# --------------------------------------------------------------------------
# Sessions and kill zones
# --------------------------------------------------------------------------
def _local_hour(moment: datetime, tz_name: str) -> float:
    local = moment.astimezone(ZoneInfo(tz_name))
    return local.hour + local.minute / 60.0


def _window_active(moment: datetime, definition: dict[str, Any]) -> bool:
    hour = _local_hour(moment, str(definition["timezone"]))
    start, end = float(definition["start"]), float(definition["end"])
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end       # window crosses local midnight


def market_open(moment: datetime | None = None, *, trades_24_7: bool = False) -> dict[str, Any]:
    """FX/metals weekend closure model (crypto is always open)."""
    moment = moment or datetime.now(timezone.utc)
    if trades_24_7:
        return {"open": True, "reason": "Instrument trades 24/7.", "schedule": "24/7"}
    ny = moment.astimezone(ZoneInfo("America/New_York"))
    weekday = ny.weekday()          # Mon=0 ... Sun=6
    hour = ny.hour + ny.minute / 60.0
    if weekday == 4 and hour >= 17:
        return {"open": False, "reason": "FX week closed at 17:00 New York on Friday.", "schedule": "FX_WEEK"}
    if weekday == 5:
        return {"open": False, "reason": "Saturday: FX market closed.", "schedule": "FX_WEEK"}
    if weekday == 6 and hour < 17:
        return {"open": False, "reason": "Sunday before 17:00 New York: FX market closed.", "schedule": "FX_WEEK"}
    return {"open": True, "reason": "Within the FX trading week.", "schedule": "FX_WEEK"}


def current_session(now: datetime | None = None, *, trades_24_7: bool = False) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    active = [name for name, definition in SESSIONS.items() if _window_active(now, definition)]
    zones = [name for name, definition in KILL_ZONES.items() if _window_active(now, definition)]
    overlap = "LONDON" in active and "NEW_YORK" in active
    primary = "LONDON_NEW_YORK_OVERLAP" if overlap else (active[0] if active else "OFF_HOURS")
    schedule = market_open(now, trades_24_7=trades_24_7)
    return {
        "session": primary,
        "active_sessions": active,
        "kill_zones": zones,
        "in_kill_zone": bool(zones),
        "overlap": overlap,
        "market_open": schedule["open"],
        "market_state_reason": schedule["reason"],
        "schedule": schedule["schedule"],
        "utc_timestamp": now.isoformat(),
    }


def session_range(
    candles: Sequence[dict[str, Any]],
    session: str,
    *,
    on_day: date | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """High/low of a named session for a specific day (default: latest day)."""
    definition = SESSIONS.get(str(session).upper()) or KILL_ZONES.get(str(session).upper())
    if not definition:
        return {"status": "unknown_session", "session": session}
    tz_name = str(definition["timezone"])
    rows: list[dict[str, Any]] = []
    for candle in candles or []:
        moment = _candle_time(candle)
        if moment is None or not _window_active(moment, definition):
            continue
        local_day = moment.astimezone(ZoneInfo(tz_name)).date()
        if on_day is not None and local_day != on_day:
            continue
        rows.append({**candle, "_local_day": local_day})
    if not rows:
        return {"status": "no_data", "session": session, "timezone": tz_name}
    if on_day is None:
        latest = max(row["_local_day"] for row in rows)
        rows = [row for row in rows if row["_local_day"] == latest]
        on_day = latest
    highs = [_f(c, "high") for c in rows if _f(c, "high") > 0]
    lows = [_f(c, "low") for c in rows if _f(c, "low") > 0]
    return {
        "status": "ready",
        "session": str(session).upper(),
        "day": on_day.isoformat(),
        "timezone": tz_name,
        "high": max(highs) if highs else None,
        "low": min(lows) if lows else None,
        "candle_count": len(rows),
    }


def liquidity_levels_from_sessions(
    candles: Sequence[dict[str, Any]],
    *,
    now: datetime | None = None,
    trades_24_7: bool = False,
) -> list[dict[str, Any]]:
    """External liquidity levels for the market-structure engine.

    Produces previous-day high/low and the Asian-range high/low as explicit
    liquidity pools with a documented origin.
    """
    levels: list[dict[str, Any]] = []
    daily = daily_levels(candles, now=now, trades_24_7=trades_24_7)
    previous = daily.get("previous_day", {})
    if previous.get("high"):
        levels.append({"price": previous["high"], "side": "buy_side", "kind": "previous_day_high",
                       "timestamp": previous.get("trading_day"), "strength": 3})
    if previous.get("low"):
        levels.append({"price": previous["low"], "side": "sell_side", "kind": "previous_day_low",
                       "timestamp": previous.get("trading_day"), "strength": 3})
    asian = session_range(candles, "ASIAN_RANGE")
    if asian.get("status") == "ready":
        if asian.get("high"):
            levels.append({"price": asian["high"], "side": "buy_side", "kind": "asian_range_high",
                           "timestamp": asian.get("day"), "strength": 2})
        if asian.get("low"):
            levels.append({"price": asian["low"], "side": "sell_side", "kind": "asian_range_low",
                           "timestamp": asian.get("day"), "strength": 2})
    return levels
